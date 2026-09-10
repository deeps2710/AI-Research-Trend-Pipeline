# AI Research Trend & Paper Intelligence Pipeline

A B.Tech Data Engineering project intended to collect scholarly metadata,
track AI research trends, and help explore research papers using OpenAlex.

## Current status: Stage 1

Stage 1 establishes the Python project and retrieves one page of Machine
Learning works published in **2025**. The exploration script displays the
total matching count and up to 10 works with their title, year, citation
count, type, and primary topic. Missing optional fields display as Unknown.
Results are printed only; no data is saved.

dlt, DuckDB, Pandas transformations, analytics, Matplotlib, Streamlit, ML,
embeddings, and dashboards are planned for later stages and intentionally
not implemented yet.

## Setup and run

Prerequisites: Python 3.10 or newer, Git, and an internet connection for
dependency installation and live API calls. Run commands from the repository root.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and replace `your_openalex_api_key_here` with your own key from
[OpenAlex API settings](https://openalex.org/settings/api). Never commit or
share this file. Existing environment variables take precedence over `.env`.
For small anonymous development requests, omit the key, leave it blank, or
leave the example placeholder unchanged; the client sends no key in those cases.
Anonymous access is subject to OpenAlex's current limits; see
[authentication documentation](https://help.openalex.org/api/authentication/).

Run the exploration:

```bash
python -m scripts.explore_openalex
```

If PowerShell activation is restricted, use `.\.venv\Scripts\python.exe`
in place of `python` for installation and execution.

## Project structure

```text
src/
  __init__.py
  extract/
    __init__.py
    openalex_client.py    # Session-based Works API client
scripts/
  __init__.py
  explore_openalex.py     # Terminal exploration entry point
tests/                   # Offline standard-library unit tests
.env.example             # API key placeholder
.gitignore               # Secrets, caches, and local data exclusions
requirements.txt         # requests and python-dotenv only
```

`OpenAlexClient.fetch_works()` accepts a keyword slug (default
`machine-learning`), an optional publication year, and `per_page` from 1 to
100. It uses `keywords.id:machine-learning`, combines a supplied year with
a comma-separated filter, and selects only the requested project metadata.
Requests use a 30-second timeout and check HTTP status before decoding JSON.
Call `close()` after using the client. Avoid logging request exceptions or
URLs, which can contain the `api_key` query parameter.

## Local checks

```bash
python -m compileall -q src scripts tests
python -m unittest discover -s tests -v
git check-ignore .env
git status --short
```

Tests run offline with mocked HTTP responses. A successful test suite does
not prove live API availability. The exploration command requires network
access and reports a safe error if the API cannot be reached.
