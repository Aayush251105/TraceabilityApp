"""
Shared fixtures.  Database tests use the disposable traceability_test database
and `test_app_`-prefixed tables only — never the dev database.
"""

from __future__ import annotations

import os

import pytest

from traceability.config import TraceabilityConfig

TEST_PREFIX = "test_app_"
APP_TABLES = ("overrides", "review_items", "run_events", "run_stages", "runs")


def make_cfg() -> TraceabilityConfig:
    return TraceabilityConfig(
        pg_dbname=os.getenv("TEST_PG_DBNAME", "traceability_test"),
        pg_user=os.getenv("TEST_PG_USER", "postgres"),
        pg_password=os.getenv("TEST_PG_PASSWORD", ""),
    )


def pg_available() -> bool:
    try:
        import psycopg2
        psycopg2.connect(make_cfg().build_dsn()).close()
        return True
    except Exception:
        return False


requires_pg = pytest.mark.skipif(not pg_available(), reason="PostgreSQL test database not reachable")


@pytest.fixture()
def run_store():
    from tracelight.orchestrator.state import RunStore

    cfg = make_cfg()
    assert cfg.pg_dbname != "traceability_dev", "tests must not touch the dev database"
    store = RunStore(cfg, prefix=TEST_PREFIX)
    with store._cursor() as cur:
        for name in APP_TABLES:
            assert (TEST_PREFIX + name).startswith("test_")
            cur.execute(f"DROP TABLE IF EXISTS {TEST_PREFIX}{name} CASCADE")
    store.init_schema()
    yield store
    store.close()
