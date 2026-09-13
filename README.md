# AI Research Trend & Paper Intelligence Pipeline

A B.Tech Data Engineering project intended to collect scholarly metadata,
track AI research trends, and help explore research papers using OpenAlex.

## Current status: Stage 2 — Reliable OpenAlex Extraction

Stage 2 adds bounded cursor pagination, transient-error retries, streamed raw
JSONL files, and provenance sidecars. Only `requests` and `python-dotenv` are
required; all other functionality uses Python's standard library.

Stage 1 establishes the Python project and retrieves one page of Machine
Learning works published in **2025**. The exploration script displays the
total matching count and up to 10 works with their title, year, citation
count, type, and primary topic. Missing optional fields display as Unknown.
This Stage 1 exploration command still prints results without saving data.

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
  extract_openalex.py     # Bounded raw extraction CLI
tests/                   # Offline standard-library unit tests
data/raw/openalex/        # Generated JSONL and provenance; Git-ignored
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

## Raw extraction

```bash
python -m scripts.extract_openalex --keyword machine-learning --year 2025 --max-records 250
```

These are also the defaults. For a small development check:

```bash
python -m scripts.extract_openalex --keyword machine-learning --year 2025 --max-records 5 --per-page 5
```

Use `--output-dir data/raw/openalex` to choose a local destination. Keywords
must be lowercase hyphen-separated slugs. Record limits must be positive
integers, years must be 1–9999, and page sizes must be 1–100.

`iter_works()` starts with `cursor="*"` and follows `meta.next_cursor`, so it
can go beyond the 10,000-result limit of numbered pages. It yields individual
Work dictionaries and holds only one page in memory. It stops on an empty
page, a null cursor, or the requested record limit. The library accepts
`max_records=None` to iterate until exhaustion; the CLI always uses a positive
bound. A page size of 100 reduces requests, and the last request is reduced
to the remaining record allowance. See [OpenAlex paging](https://help.openalex.org/api/paging/).

Both retrieval methods share a request helper. By default, transient HTTP
429/500/502/503/504 responses, timeouts, and connection failures get at most
three retries after the initial attempt, waiting 1, 2, then 4 seconds.
Set `OpenAlexClient(max_retries=...)` to change this, or use 0 for no retries.
Other HTTP errors and invalid JSON fail immediately. Each request has a
30-second timeout. Retry warnings contain a status or failure category,
never a request URL or key.

The client exposes the latest available `X-RateLimit-Limit`,
`X-RateLimit-Remaining`, `X-RateLimit-Credits-Used`, and `X-RateLimit-Reset`
headers through `client.rate_limits`; this is informational, not a scheduler.
See [OpenAlex usage headers](https://help.openalex.org/api/authentication/).

Files use names such as `machine-learning_2025_20260913T120000000000Z.jsonl`.
Each UTF-8 line is one raw selected Work object, with no analytical
transformations. The matching `.metadata.json` records source, entity,
keyword, year, UTC start/completion timestamps, requested and actual record
counts, configured page size, and authentication usage as a boolean only.

Data and metadata are first written with `.inprogress` suffixes and renamed
after extraction succeeds. The final metadata sidecar is published last and
signals completion. A failure returns a nonzero exit code; leftover files
without a final sidecar must be treated as incomplete. Interrupted runs are
not resumed automatically. The two renames are not a single atomic operation.

Raw files, sidecars, and interrupted files are intentionally Git-ignored,
including JSONL/sidecars written to custom output directories. No raw data or
API credentials belong in commits. dlt, DuckDB, transformations, analytics,
and Streamlit remain later-stage work.

## Local checks

```bash
python -m compileall -q src scripts tests
python -m unittest discover -s tests -v
git check-ignore .env data/raw/openalex/example.jsonl
git status --short
```

Tests run offline with mocked HTTP responses. A successful test suite does
not prove live API availability. The exploration command requires network
access and reports a safe error if the API cannot be reached.
