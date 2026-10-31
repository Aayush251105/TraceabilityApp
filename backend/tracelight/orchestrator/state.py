"""
Run state in PostgreSQL.

Everything the UI shows about a run (status, stage progress, the activity log,
review decisions, verdict overrides) is stored here, so a run survives a
server restart and can be resumed.  The tables live in the same database as
the traceability tables, prefixed `app_` (tests use `test_app_`).

Tables
------
app_runs          one row per run: inputs, status, the settings it ran with,
                  the run's document_id / repo_id in the traceability tables
app_run_stages    one row per (run, stage): status, done/total, timings, detail
app_run_events    append-only activity log (what the lanes show)
app_review_items  review checkpoint items and the user's resolution
app_overrides     human verdict overrides on the results (append-only)
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Sequence

import psycopg2
import psycopg2.extras

from traceability.config import TraceabilityConfig

RUN_STATUSES = ("queued", "running", "paused", "completed", "failed", "cancelled")
STAGE_STATUSES = ("queued", "running", "waiting", "done", "failed", "skipped", "cancelled")


@dataclass(frozen=True)
class StageDef:
    key: str
    lane: Optional[str]        # 'A' (code), 'B' (SRS) or None (sequential part)
    group: str                 # the step shown in the stage rail
    label: str
    unit: str = ""             # what done/total counts


STAGES: Sequence[StageDef] = (
    StageDef("fetch", "A", "ingest", "Fetch source", "files"),
    StageDef("docstrings", "A", "ingest", "Parse code and generate docstrings", "components"),
    StageDef("index_code", "A", "ingest", "Index code for search", "components"),
    StageDef("extract", "B", "ingest", "Extract requirements", "requirements"),
    StageDef("prepare_review", "B", "ingest", "Prepare review", "items"),
    StageDef("review", None, "review", "Review requirements", "items"),
    StageDef("index_srs", None, "search", "Index requirements", "requirements"),
    StageDef("search", None, "search", "Search agent", "requirements"),
    StageDef("map", None, "map", "Mapping agent", "requirements"),
    StageDef("verify", None, "verify", "Verifier agent", "requirements"),
    StageDef("results", None, "results", "Results", ""),
)
STAGE_KEYS = tuple(s.key for s in STAGES)
STAGE_BY_KEY = {s.key: s for s in STAGES}


def _schema(p: str) -> List[str]:
    return [
        f"""
        CREATE TABLE IF NOT EXISTS {p}runs (
            run_id          BIGSERIAL   PRIMARY KEY,
            name            TEXT        NOT NULL,
            status          TEXT        NOT NULL DEFAULT 'queued',
            source_kind     TEXT        NOT NULL,        -- zip | folder | git
            source_ref      TEXT        NOT NULL,        -- file name, path or URL
            git_ref         TEXT,                        -- branch/tag requested (git)
            commit_sha      TEXT,
            srs_filename    TEXT        NOT NULL,
            document_id     TEXT,
            repo_id         TEXT,
            workdir         TEXT        NOT NULL,
            settings        JSONB       NOT NULL DEFAULT '{{}}'::jsonb,
            summary         JSONB       NOT NULL DEFAULT '{{}}'::jsonb,
            error           TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            started_at      TIMESTAMPTZ,
            finished_at     TIMESTAMPTZ,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        f"""
        CREATE TABLE IF NOT EXISTS {p}run_stages (
            run_id          BIGINT      NOT NULL REFERENCES {p}runs(run_id) ON DELETE CASCADE,
            stage           TEXT        NOT NULL,
            position        INT         NOT NULL,
            lane            TEXT,
            status          TEXT        NOT NULL DEFAULT 'queued',
            done            INT         NOT NULL DEFAULT 0,
            total           INT,
            detail          JSONB       NOT NULL DEFAULT '{{}}'::jsonb,
            error           TEXT,
            started_at      TIMESTAMPTZ,
            finished_at     TIMESTAMPTZ,
            PRIMARY KEY (run_id, stage)
        )""",
        f"""
        CREATE TABLE IF NOT EXISTS {p}run_events (
            event_id        BIGSERIAL   PRIMARY KEY,
            run_id          BIGINT      NOT NULL REFERENCES {p}runs(run_id) ON DELETE CASCADE,
            ts              TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            stage           TEXT,
            lane            TEXT,
            level           TEXT        NOT NULL DEFAULT 'info',   -- info | ok | warn | error
            message         TEXT        NOT NULL,
            data            JSONB       NOT NULL DEFAULT '{{}}'::jsonb
        )""",
        f"CREATE INDEX IF NOT EXISTS {p}run_events_run_idx ON {p}run_events (run_id, event_id)",
        f"""
        CREATE TABLE IF NOT EXISTS {p}review_items (
            run_id          BIGINT      NOT NULL REFERENCES {p}runs(run_id) ON DELETE CASCADE,
            item_key        TEXT        NOT NULL,
            position        INT         NOT NULL,
            category        TEXT        NOT NULL,   -- uncertain | flagged | incomplete | split
            requirement_id  TEXT,
            payload         JSONB       NOT NULL DEFAULT '{{}}'::jsonb,
            resolution      TEXT,                   -- kept | edited | discarded | merged | unreviewed
            resolution_data JSONB       NOT NULL DEFAULT '{{}}'::jsonb,
            resolved_at     TIMESTAMPTZ,
            PRIMARY KEY (run_id, item_key)
        )""",
        f"""
        CREATE TABLE IF NOT EXISTS {p}overrides (
            override_id     BIGSERIAL   PRIMARY KEY,
            run_id          BIGINT      NOT NULL REFERENCES {p}runs(run_id) ON DELETE CASCADE,
            requirement_id  TEXT        NOT NULL,
            status          TEXT        NOT NULL,
            note            TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
    ]


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


class RunStore:
    """Thin data access layer for run state.  One connection per instance (autocommit)."""

    def __init__(self, config: TraceabilityConfig, prefix: str = "app_") -> None:
        self.prefix = prefix
        self._conn = psycopg2.connect(config.build_dsn())
        self._conn.autocommit = True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "RunStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @contextmanager
    def _cursor(self) -> Iterator[psycopg2.extras.RealDictCursor]:
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur

    @contextmanager
    def transaction(self) -> Iterator[psycopg2.extras.RealDictCursor]:
        self._conn.autocommit = False
        try:
            with self._cursor() as cur:
                yield cur
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            self._conn.autocommit = True

    def init_schema(self) -> None:
        with self._cursor() as cur:
            for stmt in _schema(self.prefix):
                cur.execute(stmt)

    def t(self, name: str) -> str:
        return f"{self.prefix}{name}"

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    def create_run(self, *, name: str, source_kind: str, source_ref: str, srs_filename: str,
                   workdir: str, settings: Dict[str, Any], git_ref: Optional[str] = None) -> int:
        with self.transaction() as cur:
            cur.execute(
                f"""INSERT INTO {self.t('runs')} (name, source_kind, source_ref, git_ref, srs_filename,
                                                  workdir, settings)
                    VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING run_id""",
                (name, source_kind, source_ref, git_ref, srs_filename, workdir, _json(settings)))
            run_id = cur.fetchone()["run_id"]
            for i, s in enumerate(STAGES):
                cur.execute(
                    f"""INSERT INTO {self.t('run_stages')} (run_id, stage, position, lane)
                        VALUES (%s, %s, %s, %s)""", (run_id, s.key, i, s.lane))
        return run_id

    def update_run(self, run_id: int, **fields: Any) -> None:
        if not fields:
            return
        cols, vals = [], []
        for key, value in fields.items():
            if key in ("settings", "summary"):
                value = _json(value)
            cols.append(f"{key} = %s")
            vals.append(value)
        with self._cursor() as cur:
            cur.execute(f"UPDATE {self.t('runs')} SET {', '.join(cols)}, updated_at = now() "
                        f"WHERE run_id = %s", (*vals, run_id))

    def set_run_status(self, run_id: int, status: str, *, error: Optional[str] = None) -> None:
        assert status in RUN_STATUSES, status
        extra = ""
        if status == "running":
            extra = ", started_at = COALESCE(started_at, now()), finished_at = NULL, error = NULL"
        elif status in ("completed", "failed", "cancelled"):
            extra = ", finished_at = now()"
        with self._cursor() as cur:
            cur.execute(f"UPDATE {self.t('runs')} SET status = %s, updated_at = now(){extra}"
                        + (", error = %s" if error is not None else "") + " WHERE run_id = %s",
                        (status, error, run_id) if error is not None else (status, run_id))

    def get_run(self, run_id: int) -> Optional[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(f"SELECT * FROM {self.t('runs')} WHERE run_id = %s", (run_id,))
            return cur.fetchone()

    def list_runs(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(f"SELECT * FROM {self.t('runs')} ORDER BY run_id DESC LIMIT %s", (limit,))
            return cur.fetchall()

    def runs_with_status(self, statuses: Sequence[str]) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(f"SELECT * FROM {self.t('runs')} WHERE status = ANY(%s) ORDER BY run_id",
                        (list(statuses),))
            return cur.fetchall()

    def delete_run(self, run_id: int) -> None:
        with self._cursor() as cur:
            cur.execute(f"DELETE FROM {self.t('runs')} WHERE run_id = %s", (run_id,))

    # ------------------------------------------------------------------
    # Stages
    # ------------------------------------------------------------------

    def stages(self, run_id: int) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(f"SELECT * FROM {self.t('run_stages')} WHERE run_id = %s ORDER BY position",
                        (run_id,))
            return cur.fetchall()

    def stage(self, run_id: int, stage: str) -> Dict[str, Any]:
        with self._cursor() as cur:
            cur.execute(f"SELECT * FROM {self.t('run_stages')} WHERE run_id = %s AND stage = %s",
                        (run_id, stage))
            return cur.fetchone()

    def update_stage(self, run_id: int, stage: str, *, status: Optional[str] = None,
                     done: Optional[int] = None, total: Optional[int] = None,
                     detail: Optional[Dict[str, Any]] = None, error: Optional[str] = None,
                     reset: bool = False) -> None:
        """Update a stage.  `detail` is merged into the stored detail (not replaced)."""
        sets, vals = [], []
        if reset:
            sets += ["done = 0", "total = NULL", "detail = '{}'::jsonb", "error = NULL",
                     "started_at = NULL", "finished_at = NULL"]
        if status is not None:
            assert status in STAGE_STATUSES, status
            sets.append("status = %s")
            vals.append(status)
            if status == "running":
                sets += ["started_at = COALESCE(started_at, now())", "finished_at = NULL", "error = NULL"]
            elif status in ("done", "failed", "skipped", "cancelled"):
                sets.append("finished_at = now()")
        if done is not None:
            sets.append("done = %s")
            vals.append(done)
        if total is not None:
            sets.append("total = %s")
            vals.append(total)
        if detail:
            sets.append("detail = detail || %s::jsonb")
            vals.append(_json(detail))
        if error is not None:
            sets.append("error = %s")
            vals.append(error)
        if not sets:
            return
        with self._cursor() as cur:
            cur.execute(f"UPDATE {self.t('run_stages')} SET {', '.join(sets)} "
                        f"WHERE run_id = %s AND stage = %s", (*vals, run_id, stage))

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def add_event(self, run_id: int, message: str, *, stage: Optional[str] = None,
                  lane: Optional[str] = None, level: str = "info",
                  data: Optional[Dict[str, Any]] = None) -> int:
        with self._cursor() as cur:
            cur.execute(
                f"""INSERT INTO {self.t('run_events')} (run_id, stage, lane, level, message, data)
                    VALUES (%s, %s, %s, %s, %s, %s) RETURNING event_id""",
                (run_id, stage, lane, level, message, _json(data or {})))
            return cur.fetchone()["event_id"]

    def events(self, run_id: int, *, after: int = 0, limit: int = 500,
               lane: Optional[str] = None) -> List[Dict[str, Any]]:
        where, vals = "run_id = %s AND event_id > %s", [run_id, after]
        if lane:
            where += " AND lane = %s"
            vals.append(lane)
        with self._cursor() as cur:
            cur.execute(f"SELECT * FROM {self.t('run_events')} WHERE {where} "
                        f"ORDER BY event_id LIMIT %s", (*vals, limit))
            return cur.fetchall()

    def last_events(self, run_id: int, lane: Optional[str], limit: int = 40) -> List[Dict[str, Any]]:
        lane_sql = "lane = %s" if lane else "lane IS NULL"
        vals: List[Any] = [run_id] + ([lane] if lane else []) + [limit]
        with self._cursor() as cur:
            cur.execute(f"SELECT * FROM (SELECT * FROM {self.t('run_events')} "
                        f"WHERE run_id = %s AND {lane_sql} ORDER BY event_id DESC LIMIT %s) e "
                        f"ORDER BY event_id", vals)
            return cur.fetchall()

    # ------------------------------------------------------------------
    # Review items
    # ------------------------------------------------------------------

    def replace_review_items(self, run_id: int, items: List[Dict[str, Any]]) -> None:
        """Store freshly built items (resolutions already present on items are kept as given)."""
        with self.transaction() as cur:
            cur.execute(f"DELETE FROM {self.t('review_items')} WHERE run_id = %s", (run_id,))
            for i, it in enumerate(items):
                cur.execute(
                    f"""INSERT INTO {self.t('review_items')} (run_id, item_key, position, category,
                            requirement_id, payload, resolution, resolution_data, resolved_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                                CASE WHEN %s IS NULL THEN NULL ELSE now() END)""",
                    (run_id, it["key"], i, it["category"], it.get("requirement_id"),
                     _json(it.get("payload", {})), it.get("resolution"),
                     _json(it.get("resolution_data", {})), it.get("resolution")))

    def review_items(self, run_id: int) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(f"SELECT * FROM {self.t('review_items')} WHERE run_id = %s ORDER BY position",
                        (run_id,))
            return cur.fetchall()

    def resolve_review_item(self, run_id: int, item_key: str, resolution: Optional[str],
                            data: Optional[Dict[str, Any]] = None) -> bool:
        with self._cursor() as cur:
            cur.execute(
                f"""UPDATE {self.t('review_items')}
                    SET resolution = %s, resolution_data = %s,
                        resolved_at = CASE WHEN %s IS NULL THEN NULL ELSE now() END
                    WHERE run_id = %s AND item_key = %s""",
                (resolution, _json(data or {}), resolution, run_id, item_key))
            return cur.rowcount == 1

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------

    def add_override(self, run_id: int, requirement_id: str, status: str, note: Optional[str]) -> int:
        with self._cursor() as cur:
            cur.execute(
                f"""INSERT INTO {self.t('overrides')} (run_id, requirement_id, status, note)
                    VALUES (%s, %s, %s, %s) RETURNING override_id""",
                (run_id, requirement_id, status, note))
            return cur.fetchone()["override_id"]

    def latest_overrides(self, run_id: int) -> Dict[str, Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(
                f"""SELECT DISTINCT ON (requirement_id) * FROM {self.t('overrides')}
                    WHERE run_id = %s ORDER BY requirement_id, override_id DESC""", (run_id,))
            return {r["requirement_id"]: r for r in cur.fetchall()}

    def override_history(self, run_id: int, requirement_id: str) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(f"SELECT * FROM {self.t('overrides')} WHERE run_id = %s AND requirement_id = %s "
                        f"ORDER BY override_id DESC", (run_id, requirement_id))
            return cur.fetchall()
