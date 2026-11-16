# Running Tracelight

Tracelight traces the requirements in an SRS document to the Python code that
implements them. It runs entirely on your machine: local models through
Ollama, data in PostgreSQL.

- [Quick start](#1-quick-start-already-set-up): if everything is installed
- [Folder layout](#2-folder-layout-before-you-run-anything): what must exist before you run anything
- [First-time setup](#3-first-time-setup-step-by-step): from a clean Windows machine
- [Your first run](#4-your-first-run-in-the-app): a guided first trace
- [Without the UI](#5-running-the-pipeline-from-the-terminal-no-ui) · [Tests](#6-running-the-tests) · [Troubleshooting](#7-troubleshooting) · [Where data lives](#8-where-data-lives-and-how-to-reset)

Commands are for **Windows PowerShell**. Run them from the folder shown at the
top of each block.

---

## 1. Quick start (already set up)

You need **two terminals**: one for the backend, one for the frontend. Ollama
and PostgreSQL must be running.

**Terminal 1: backend (API)**

```powershell
cd DOC_Agent\TraceabilityApp\backend
..\..\SRS_to_code_traceability\.venv\Scripts\python.exe -m tracelight.api
```

Leave it running. It listens on http://127.0.0.1:8000; the interactive API
docs are at http://127.0.0.1:8000/docs.

**Terminal 2: frontend (UI)**

```powershell
cd DOC_Agent\TraceabilityApp\frontend
npm run dev
```

Open **http://127.0.0.1:5173** in your browser.

To stop: press `Ctrl+C` in each terminal.

---

## 2. Folder layout before you run anything

All four projects sit **side by side** in one parent folder (here
`DOC_Agent`). Tracelight finds the agents by these folder names, and each
Python project has its own virtual environment in a `.venv` folder.

```
DOC_Agent\
├── DocAgent\                      # generates docstrings for the code
│   ├── .venv\                     #   its own Python environment
│   ├── generate_docstrings.py
│   ├── config\
│   └── src\
├── SRSAgent\                      # extracts requirements from the SRS
│   ├── .venv\                     #   its own Python environment
│   ├── .env                       #   model settings (copied from .env.example)
│   ├── app.py
│   └── ...
├── SRS_to_code_traceability\      # search, mapping and verification ("traceability" package)
│   ├── .venv\                     #   shared by this package AND the Tracelight backend
│   ├── cli.py
│   └── ...
├── TraceabilityApp\               # Tracelight: orchestrator, API and UI
│   ├── backend\                   #   Python package "tracelight"
│   ├── frontend\                  #   React app
│   │   └── node_modules\          #     created by npm install
│   ├── data\                      #   created on first run: uploads, run folders, settings.json
│   ├── README.md
│   └── RUNCODE.md                 #   this file
└── library_traceability_dataset\  # optional: a sample SRS + codebase to try it on
    ├── srs\SRS_Library_Management_System.docx
    └── codebase\library_system\
```

Rules that matter:

- **Folder names must match**: `DocAgent`, `SRSAgent`, `SRS_to_code_traceability`,
  `TraceabilityApp`. To use other locations, set `TRACELIGHT_DOCAGENT_DIR` and
  `TRACELIGHT_SRSAGENT_DIR` (and `..._PYTHON` for their interpreters).
- **Each `.venv` stays inside its project.** DocAgent and the SRS Agent run in
  their own environments. Tracelight launches them; it never imports them.
- **The Tracelight backend has no `.venv` of its own.** It is installed into
  `SRS_to_code_traceability\.venv`, which already has PyTorch and the
  embedding model.

---

## 3. First-time setup, step by step

Plan about 30–60 minutes, most of it downloads. You need about 20 GB of free
disk space for the models.

### 3.1 Install the prerequisites

| Tool | Version | Notes |
|---|---|---|
| Windows | 10 or 11 | macOS/Linux work too; change the paths and use `bin/python` instead of `Scripts\python.exe` |
| Python | 3.12 (3.10 or newer) | https://www.python.org/downloads/ (tick **"Add python.exe to PATH"**) |
| Node.js | 20 or newer (tested on 24) | https://nodejs.org/ (LTS installer) |
| Git | any recent | https://git-scm.com/download/win |
| PostgreSQL | 16 or newer (tested on 18) | https://www.postgresql.org/download/windows/ (remember the `postgres` password you choose) |
| pgvector | 0.7 or newer (tested on 0.8.1) | the PostgreSQL extension for vectors; see 3.3 |
| Ollama | recent | https://ollama.com/download |
| GPU | optional | NVIDIA with 6 GB or more makes the models usable; CPU-only works but is very slow |

Check them in a new terminal:

```powershell
python --version
node --version
git --version
ollama --version
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" --version   # adjust 18 to your version
```

### 3.2 Get the code

```powershell
mkdir DOC_Agent
cd DOC_Agent
git clone https://github.com/Aayush251105/DocAgent_Major_Project.git DocAgent
git clone https://github.com/Aayush251105/SRSAgent_Major_Project.git SRSAgent
git clone https://github.com/nandhra702/SRS_to_code_traceability.git SRS_to_code_traceability
git clone https://github.com/Aayush251105/TraceabilityApp.git TraceabilityApp
```

Use the branch the team works on. The current work lives on `Aayush`:

```powershell
cd SRSAgent; git checkout Aayush; cd ..
cd SRS_to_code_traceability; git checkout Aayush; cd ..
cd TraceabilityApp; git checkout Aayush; cd ..
```

The sample dataset (`library_traceability_dataset`) is optional. Copy it from
a teammate if you want to try the app on known data.

### 3.3 Set up PostgreSQL and pgvector

1. Install pgvector for your PostgreSQL version.
   - On Windows it is built from source with the Visual Studio C++ build
     tools. Follow the "Windows" section of https://github.com/pgvector/pgvector#windows.
     Run the commands in an **"x64 Native Tools Command Prompt for VS"** as
     administrator.
2. Create the database (you are asked for the `postgres` password):

   ```powershell
   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -c "CREATE DATABASE traceability_dev;"
   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -d traceability_dev -c "CREATE EXTENSION IF NOT EXISTS vector;"
   ```

   The second command must succeed. If it says the extension is not
   available, pgvector is not installed for this PostgreSQL version.

3. (Only if you will run the tests.) Create a separate test database the
   same way:

   ```powershell
   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -c "CREATE DATABASE traceability_test;"
   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -d traceability_test -c "CREATE EXTENSION IF NOT EXISTS vector;"
   ```

### 3.4 Set the environment variables

Database credentials come **only** from environment variables. They are never
written in a file. Set them once for your user, then **close and reopen every
terminal** (and VS Code), because new values only reach new terminals:

```powershell
setx TRACEABILITY_PG_PASSWORD "your-postgres-password"
setx TEST_PG_PASSWORD "your-postgres-password"        # only for the tests
```

Optional; these are the defaults:

| Variable | Default | Meaning |
|---|---|---|
| `TRACEABILITY_PG_HOST` | `localhost` | database host |
| `TRACEABILITY_PG_PORT` | `5432` | database port |
| `TRACEABILITY_PG_DBNAME` | `traceability_dev` | database name |
| `TRACEABILITY_PG_USER` | `postgres` | database user |
| `TRACELIGHT_DATA_DIR` | `TraceabilityApp\data` | where runs are stored |

### 3.5 Pull the Ollama models

Make sure Ollama is running (its icon is in the system tray; or run
`ollama serve` in a terminal). Then:

```powershell
ollama pull yi-coder:9b         # docstrings (DocAgent)      ~5 GB
ollama pull llama3.1            # requirement extraction     ~5 GB
ollama pull qwen2.5:3b          # candidate judge            ~2 GB
ollama pull qwen2.5-coder:7b    # verification               ~5 GB
ollama list                     # all four should be listed
```

These are the defaults. You can pick other pulled models later in **Settings**
or per run.

### 3.6 Create the Python environments

**DocAgent**

```powershell
cd DOC_Agent\DocAgent
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e ".[all]"
cd ..
```

**SRS Agent**

```powershell
cd DOC_Agent\SRSAgent
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
cd ..
```

**Traceability package + Tracelight backend.** These share one environment.
This step downloads PyTorch, so it takes a while.

```powershell
cd DOC_Agent\SRS_to_code_traceability
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\python.exe -m pip install -e "..\TraceabilityApp\backend[test]"
cd ..
```

### 3.7 Create the database tables and download the embedding model

The search uses a small local embedding model (`all-MiniLM-L6-v2`, about
90 MB). Downloads are off by default, so allow it **once** for this terminal:

```powershell
cd DOC_Agent\SRS_to_code_traceability
$env:EMBED_ALLOW_DOWNLOAD = "1"
.venv\Scripts\python.exe -m traceability.cli init-schema
cd ..\TraceabilityApp\backend
..\..\SRS_to_code_traceability\.venv\Scripts\python.exe -m tracelight.orchestrator.cli init
cd ..\..
```

You should see `Run-state tables ready`. The model is now cached (in
`%USERPROFILE%\.cache\huggingface`), and later runs work offline.

### 3.8 Install the frontend

```powershell
cd DOC_Agent\TraceabilityApp\frontend
npm install
cd ..\..
```

If PowerShell says `npm.ps1 cannot be loaded because running scripts is
disabled`, run this once and try again:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

### 3.9 Start it

Follow [Quick start](#1-quick-start-already-set-up): the backend in one
terminal, `npm run dev` in another, then open http://127.0.0.1:5173.

---

## 4. Your first run in the app

1. **Check Settings first** (left sidebar → *Settings*).
   - *Local models*: "Connected", with every model **Ready**. A "Not pulled"
     model shows the `ollama pull …` command to run.
   - *Database*: "Connected", with a pgvector version.
   - *Agents*: DocAgent and SRS Agent both **Ready**.
2. **Start a run** (*New run*).
   - *Requirements document*: drop your SRS (`.docx`, `.pdf`, `.md` or
     `.txt`), or use *Paste text*. Sample:
     `library_traceability_dataset\srs\SRS_Library_Management_System.docx`.
   - *Codebase*: choose **Folder** and paste a full path. Sample:
     `C:\...\DOC_Agent\library_traceability_dataset\codebase`. You can also
     upload a **ZIP**, or use a public **GitHub URL**.
   - Wait for the size check ("Ready: N Python files, M components").
   - **On a GPU with 8 GB or less**, open *Advanced* and choose **"SRS first,
     then code"**. Running both lanes at once makes Ollama keep swapping
     models, which is slower.
   - Click **Start traceability run**.
3. **Watch the pipeline.**
   - Two lanes run: *Code* (DocAgent writes docstrings, about 40 s per
     component) and *SRS* (requirements are extracted). Timers and ETAs update
     live.
   - You can close the browser; the run continues in the backend.
4. **Review** (the run pauses once).
   - Resolve the flagged items with **Keep / Discard / Edit / Merge / Fix ID**.
     Keyboard: ↑ ↓ to move, K D E M to act.
   - Then click **Continue tracing**. If nothing was flagged, just continue.
5. **Results.**
   - When verification finishes (about 20 s per requirement), open
     *Results*: how many requirements are supported, partially supported, not
     supported or not found.
   - Click any requirement to see its claims, the exact cited code lines and
     the mapping graph. You can accept or override a verdict there.
6. **Explore.**
   - *Search*: type a feature in your own words ("renew a loan") to find the
     requirement and the code that implements it.
   - *Code view*: browse files; see which code is traced and which is not.
   - Export from *Results → Export* (CSV, JSON, or print to PDF).

A full run on the sample library dataset (41 components, 39 requirements)
takes roughly 45–90 minutes on a 6 GB laptop GPU. Most of that is docstring
generation.

---

## 5. Running the pipeline from the terminal (no UI)

The same pipeline runs from the command line. This is useful for scripted
experiments:

```powershell
cd DOC_Agent\TraceabilityApp\backend
$py = "..\..\SRS_to_code_traceability\.venv\Scripts\python.exe"

& $py -m tracelight.orchestrator.cli run --sequential `
    --srs ..\..\library_traceability_dataset\srs\SRS_Library_Management_System.docx `
    --folder ..\..\library_traceability_dataset\codebase

& $py -m tracelight.orchestrator.cli list            # all runs
& $py -m tracelight.orchestrator.cli status 1        # stages and recent events of run 1
& $py -m tracelight.orchestrator.cli review 1        # open review items
& $py -m tracelight.orchestrator.cli continue 1      # finish the review, run search → map → verify
& $py -m tracelight.orchestrator.cli resume 1        # after a failure or a stopped server
```

Useful options for `run`:
- `--git https://github.com/owner/repo [--ref main]` or `--zip code.zip`
  instead of `--folder`;
- `--auto-approve`, which doesn't pause for review;
- `--model-docagent / --model-srs / --model-judge / --model-verifier` to
  choose models for this run;
- `--docagent-test-mode placeholder`, a quick smoke test with fake
  docstrings. Its results are not meaningful.

Runs started from the terminal appear in the UI too.

---

## 6. Running the tests

The tests use the separate `traceability_test` database (see 3.3 and 3.4) and
never touch your real data.

```powershell
# backend (about 2 minutes)
cd DOC_Agent\TraceabilityApp\backend
..\..\SRS_to_code_traceability\.venv\Scripts\python.exe -m pytest -q

# frontend
cd ..\frontend
npm test
npm run typecheck
```

---

## 7. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| The UI says **"Cannot reach the Tracelight server"** | The backend is not running. Start it (section 1, terminal 1). |
| **"Ollama unreachable"** in the sidebar or Settings | Start Ollama (`ollama serve`, or the tray app). Check the endpoint in Settings and click *Test connection*. |
| A model shows **"Not pulled"** | Run the `ollama pull <model>` command shown next to it, or choose another model in Settings. |
| **`password authentication failed`** or a database error on startup | `TRACEABILITY_PG_PASSWORD` is missing or wrong. Set it with `setx` (3.4), then **open a new terminal**. |
| **`extension "vector" is not available`** | pgvector is not installed for this PostgreSQL version (3.3). |
| **Embedding model not found locally** / downloads disabled | Run step 3.7 once with `$env:EMBED_ALLOW_DOWNLOAD = "1"`. |
| Settings → Agents shows **"Folder not found"** or **".venv missing"** | The folder layout differs from section 2, or a `.venv` was not created (3.6). |
| A run **fails at "Parse code and generate docstrings"** | Open the run's pipeline page: the error is shown there. The full log is in `TraceabilityApp\data\runs\run-N\logs\docagent.log`. Usually the model is not pulled or Ollama stopped. |
| **Port 8000 or 5173 already in use** | Another copy is still running. Close the old terminal, or start on another port: `python -m tracelight.api --port 8001`, and point the proxy in `frontend\vite.config.ts` at it. |
| `npm.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then reopen the terminal. |
| Everything is **very slow** | Use "SRS first, then code" (New run → Advanced, or Settings → Pipeline). Check that Ollama uses the GPU: `ollama ps` should show `GPU`. |
| The server stopped while a run was going | On restart the run is marked failed. Open it and click **Resume run**; finished stages are not repeated. |

---

## 8. Where data lives and how to reset

- **Run files** (uploaded SRS, copies of the code, agent outputs, logs):
  `TraceabilityApp\data\runs\run-N\`.
- **Settings you saved in the UI:** `TraceabilityApp\data\settings.json`.
  Delete it to go back to the defaults.
- **Everything else** (requirements, code graph, embeddings, links, verdicts,
  run state) is in the `traceability_dev` database.
- **To delete a run:** *Runs* page → ✕ on the row. This removes its files
  and its database rows.
- `TraceabilityApp\data\` is not committed to git.
