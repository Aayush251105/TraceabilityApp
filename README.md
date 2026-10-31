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
