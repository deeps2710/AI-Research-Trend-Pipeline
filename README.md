# AI Research Trend & Paper Intelligence Pipeline

A B.Tech Data Engineering project intended to collect scholarly metadata,
track AI research trends, and help explore research papers using OpenAlex.

## Current status: Stage 3 — dlt + DuckDB ingestion

The current flow is **OpenAlex → Raw JSONL → dlt → DuckDB**. Stage 2 provides
bounded cursor pagination, retries, raw JSONL, and provenance sidecars.
Stage 3 loads those local files into a persistent warehouse using
`dlt[duckdb]`, alongside the existing `requests` and `python-dotenv` dependencies.

Stage 1 establishes the Python project and retrieves one page of Machine
Learning works published in **2025**. The exploration script displays the
total matching count and up to 10 works with their title, year, citation
count, type, and primary topic. Missing optional fields display as Unknown.
This Stage 1 exploration command still prints results without saving data.

Analytical transformations, curated warehouse modeling, Pandas, Matplotlib,
Streamlit, ML, embeddings, and dashboards belong to later stages and are
not implemented.

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
  load/
    __init__.py
    openalex_dlt.py       # Streaming JSONL resource and DuckDB pipeline
scripts/
  __init__.py
  explore_openalex.py     # Terminal exploration entry point
  extract_openalex.py     # Bounded raw extraction CLI
  load_openalex.py        # Load existing JSONL, without OpenAlex requests
  inspect_warehouse.py    # Read-only table/count/sample inspection
tests/                   # Offline standard-library unit tests
data/raw/openalex/        # Generated JSONL and provenance; Git-ignored
data/warehouse/           # DuckDB file and local dlt state; Git-ignored
.env.example             # API key placeholder
.gitignore               # Secrets, caches, and local data exclusions
requirements.txt         # requests, python-dotenv, dlt[duckdb]
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
API credentials belong in commits.

## Load into DuckDB

Install the updated dependencies in the active virtual environment:

```bash
python -m pip install -r requirements.txt
python -m scripts.load_openalex
python -m scripts.inspect_warehouse
```

The loader prints the selected file. By default it finds the newest `.jsonl`
by modification time in `data/raw/openalex`, requiring a matching final
`.metadata.json` sidecar so interrupted Stage 2 runs are excluded. It fails
if none exists. To choose a particular extraction:

```bash
python -m scripts.load_openalex --input-file data/raw/openalex/YOUR_EXTRACTION.jsonl
```

Replace `YOUR_EXTRACTION.jsonl` with the actual filename printed by Stage 2.
An explicitly chosen JSONL does not require a sidecar. Metadata JSON and
`.inprogress` files are never accepted as Works input. The loader reads UTF-8
one record at a time, skips blank lines, and reports filename/line number for
malformed JSON, non-object records, and missing or empty Work IDs. It does
not call OpenAlex, load `.env`, or require an API key.

The pipeline is `openalex_pipeline`, the dataset/schema is `openalex_data`,
and the root resource/table is `works`. The default persistent database is
`data/warehouse/research_trends.duckdb`; the schema name differs from the
database catalog name to avoid ambiguous SQL references. Both CLIs accept
`--database`:

```bash
python -m scripts.load_openalex --input-file data/raw/openalex/YOUR_EXTRACTION.jsonl --database data/warehouse/test.duckdb
python -m scripts.inspect_warehouse --database data/warehouse/test.duckdb
```

[dlt](https://dlthub.com/docs/general-usage/destination-tables) infers columns
and types, normalizes nested objects/lists, and manages loading. Nested lists
create child tables; their names depend on the input, so the inspector
discovers tables rather than assuming a fixed schema. DuckDB stores the
result in a local file that persists after Python exits. No SQL tables are
manually created, and no analytical transformations are performed.

The resource uses `primary_key="id"` and `write_disposition="merge"` from the
first load. The OpenAlex Work ID identifies the same paper across extractions.
Loading the same file twice therefore leaves one root row per ID instead of
doubling the rows: this is idempotency here. Loading newer metadata for the
same ID updates fields such as citation counts. Replaying an older extraction
can overwrite newer metadata; no freshness ordering is implemented yet.
Root-key propagation is explicitly enabled on the source so dlt can replace
nested descendants belonging to updated Works. See [dlt merge loading](https://dlthub.com/docs/general-usage/merge-loading).

`_dlt_loads`, `_dlt_pipeline_state`, and `_dlt_version` support load, state, and
schema tracking and must be retained. Repeat loads can add tracking records
even when the Works count stays unchanged. dlt may also maintain a staging
schema. The inspector lists schemas, discovered dataset tables, internal
tables, root count, and up to five Works using available sample columns.

Local dlt working state is stored beside the database under
`.dlt_pipelines/<database-filename>/`, keeping overridden databases separate.
That state, raw data, warehouse files, and credentials are Git-ignored.
Load failures return a nonzero exit code; keep dlt state for diagnosis/retry
and do not treat a failed run as a successful warehouse refresh. Close other
processes holding the database if a file-lock error occurs.

Stage 3 validation used the existing five-record Stage 2 extraction. Two
separate CLI loads both left **5 Works / 5 distinct IDs**. With dlt 1.30.0 and
DuckDB 1.5.5, this input generated the following dataset tables:

```text
works
works__topics
works__keywords
works__authorships
works__authorships__affiliations
works__authorships__affiliations__institution_ids
works__authorships__countries
works__authorships__institutions
works__authorships__institutions__lineage
works__authorships__raw_affiliation_strings
works__primary_location__source__host_organization_lineage
works__primary_location__source__host_organization_lineage_names
works__primary_location__source__issn
_dlt_loads
_dlt_pipeline_state
_dlt_version
```

This is an observed inventory, not a fixed schema contract. dlt warned that
`primary_location__pdf_url` and `primary_location__source` had no values from
which to infer a type. Such fields can remain unmaterialized until typed
values arrive; this did not fail the load. Nested source properties that had
values were still normalized.

## Local checks

```bash
python -m compileall -q src scripts tests
python -m unittest discover -s tests -v
git check-ignore .env data/raw/openalex/example.jsonl data/warehouse/research_trends.duckdb
git status --short
```

Tests use mocked HTTP responses and real temporary DuckDB databases. They
check repeat-load root/child counts, updated citations, removal of obsolete
nested records, input validation, and warehouse inspection. They do not call
OpenAlex. Stage 1 exploration and Stage 2 extraction still require network
access; Stage 3 reads local files only.
