# Tracelight (TraceabilityApp)

Upload an SRS document and a Python codebase (ZIP, local folder or GitHub URL);
Tracelight generates docstrings (DocAgent), extracts requirements (SRS Agent),
pauses for a human review of uncertain requirements, then searches, maps and
verifies each requirement against the code and shows the results.

```
Frontend (React)  ──HTTP + live events──►  Backend API (FastAPI)
                                              │
                                     Orchestrator (pipeline runner)
                 ┌──────────────┬─────────────┼───────────────────────┐
           DocAgent        SRS Agent    traceability package     PostgreSQL
        (subprocess,     (subprocess,   (imported: ingest,       (data + run state
         own venv)        own venv)      search, map, verify)     + progress)
```

## Layout

```
TraceabilityApp/
  backend/
    tracelight/
      settings.py            paths (agents, venvs, data dir) + user settings (models, thresholds)
      orchestrator/
        state.py             run state in PostgreSQL (app_* tables)
        agents.py            launch DocAgent / SRS Agent subprocesses, parse their events, cancel
        source.py            fetch code: ZIP (safe extract) / folder / https Git shallow clone + SHA;
                             counts files and components (ast, never executes code)
        review.py            review checkpoint: build items (uncertain / flagged / incomplete /
                             split-duplicate) and apply keep / edit / discard / merge / rename
        ollama.py            Ollama reachable? models pulled?
        runner.py            Orchestrator: lanes in parallel, review pause, search/map/verify,
                             cancel, resume, recovery after a restart
        cli.py               the pipeline from the terminal
      api/
        app.py               FastAPI routes (runs, live stream, review, settings, health)
        progress.py          elapsed / ETA / overall % / stage rail from the stored stages
        __main__.py          python -m tracelight.api  (127.0.0.1:8000)
      runners/               wrapper scripts run with each agent's own Python (stdlib only)
        docagent_runner.py   DocAgent unchanged; its terminal visualizers → JSON progress events
        srs_runner.py        SRS Agent unchanged; modes: extract | detect | extract-candidates
    tests/
  frontend/                  (later step)
  data/                      run data — uploads, working copies, outputs (git-ignored)
```

The sibling folders `DocAgent/`, `SRSAgent/` and `SRS_to_code_traceability/`
stay separate projects with their own virtual environments.

## Setup

The backend runs in the traceability virtual environment (it already has
psycopg2, pgvector and sentence-transformers):

```powershell
cd DOC_Agent
SRS_to_code_traceability\.venv\Scripts\python.exe -m pip install -e "TraceabilityApp/backend[test]"
```

Database credentials come from the traceability environment variables
(`TRACEABILITY_PG_*`).  Run state lives in the same database in `app_*` tables.

## Tests

```powershell
cd TraceabilityApp\backend
..\..\SRS_to_code_traceability\.venv\Scripts\python.exe -m pytest -q
```

Database tests use `traceability_test` with `test_app_*` tables (password from
`TEST_PG_PASSWORD`); they are skipped when that database is unreachable.
Set `TRACELIGHT_NETWORK_TESTS=1` to include a real clone from GitHub.

## Run the pipeline from the terminal

```powershell
cd TraceabilityApp\backend
$py = "..\..\SRS_to_code_traceability\.venv\Scripts\python.exe"
& $py -m tracelight.orchestrator.cli init
& $py -m tracelight.orchestrator.cli run --srs ..\..\library_traceability_dataset\srs\SRS_Library_Management_System.docx --folder ..\..\library_traceability_dataset\codebase
& $py -m tracelight.orchestrator.cli review 1          # open review items
& $py -m tracelight.orchestrator.cli continue 1        # apply the review, run search → map → verify
& $py -m tracelight.orchestrator.cli status 1
```

Other sources: `--zip code.zip`, `--git https://github.com/owner/repo [--ref main]`.
Useful flags: `--auto-approve` (no pause; open items kept as unreviewed),
`--sequential` (SRS lane, then code lane — faster on a small GPU),
`--docagent-test-mode placeholder` (no LLM docstrings, for a quick smoke run),
`--model-docagent / --model-srs / --model-judge / --model-verifier` (per-run models).
Ctrl+C cancels; `resume N` continues a failed or interrupted run from the
first unfinished stage.  Run data is written to `TraceabilityApp/data/runs/run-N/`
(input, source, work, docagent, srs, logs) and the database rows use
`run-N-<name>` as document and repository IDs.

## API server

```powershell
cd TraceabilityApp\backend
..\..\SRS_to_code_traceability\.venv\Scripts\python.exe -m tracelight.api      # http://127.0.0.1:8000/docs
```

Local and single-user: it binds to 127.0.0.1, has no authentication and can
read local folders, so do not expose it on a network.  Interactive API docs
are at `/docs`.  Main endpoints:

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/inspect` | size check of a ZIP / folder / URL (New run warnings) |
| POST | `/api/runs` | create a run (multipart: `srs` + `zip` / `folder` / `git_url`) and start it |
| GET | `/api/runs`, `/api/runs/{id}` | list; detail with stages, lanes, rail, ETA |
| GET | `/api/runs/{id}/stream` | live updates (server-sent events `log` and `run`) |
| POST | `/api/runs/{id}/cancel`, `/resume` | |
| DELETE | `/api/runs/{id}` | run state, files and its traceability rows |
| GET | `/api/runs/{id}/review`, `/document`, `/review/targets?item=` | review checkpoint |
| PUT / DELETE | `/api/runs/{id}/review/items/{key}` | resolve / undo one item |
| POST | `/api/runs/{id}/review/bulk`, `/skip-remaining`, `/complete` | |
| GET / PUT | `/api/settings` | models per agent, thresholds, limits |
| GET | `/api/health` | database, Ollama, pulled models, agents |

## Run stages

| Stage            | Lane | What it does                                              |
|------------------|------|-----------------------------------------------------------|
| fetch            | A    | unpack ZIP / copy folder / shallow-clone GitHub (record SHA) |
| docstrings       | A    | DocAgent: parse components + generate docstrings          |
| index_code       | A    | ingest the code graph, embeddings                         |
| extract          | B    | SRS Agent: parse, detect, judge, extract requirements     |
| prepare_review   | B    | build the review items (uncertain, flagged, incomplete, duplicates) |
| review           |      | **pauses** until the user resolves the items              |
| index_srs        |      | ingest the reviewed requirements                          |
| search, map, verify |   | search agent → mapping agent → verifier agent            |
| results          |      | summary counts per verdict                                |
