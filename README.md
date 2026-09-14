# AI Research Trend & Paper Intelligence Pipeline

A B.Tech Data Engineering project intended to collect scholarly metadata,
track AI research trends, and help explore research papers using OpenAlex.

## Current status: Stage 7 — interactive research dashboard

The current flow is **OpenAlex → Raw JSONL → dlt → DuckDB**. Stage 2 provides
bounded cursor pagination, retries, raw JSONL, and provenance sidecars.
Stage 3 loads those local files into a persistent warehouse using
`dlt[duckdb]`, alongside the existing `requests` and `python-dotenv` dependencies.
Stage 4 rebuilds a separate `curated` schema from those ingestion tables using
DuckDB SQL. No additional dependencies are needed.
Stage 5 adds reusable SQL views in `analytics`, derived only from `curated`.
Stage 6 reads those views into Pandas and saves static Matplotlib charts.
Stage 7 adds a read-only Streamlit dashboard over the same warehouse.

Stage 1 establishes the Python project and retrieves one page of Machine
Learning works published in **2025**. The exploration script displays the
total matching count and up to 10 works with their title, year, citation
count, type, and primary topic. Missing optional fields display as Unknown.
This Stage 1 exploration command still prints results without saving data.

ML, embeddings, recommendations, and scheduling are not implemented.

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
  transform/
    __init__.py
    curated.py            # Schema compatibility, SQL orchestration, quality checks
    analytics.py          # Analytical view build and KPI validation
  visualization/
    __init__.py
    charts.py             # Reusable DataFrame-to-PNG plotting functions
    generate.py           # Read-only analytical queries and batch generation
scripts/
  __init__.py
  explore_openalex.py     # Terminal exploration entry point
  extract_openalex.py     # Bounded raw extraction CLI
  load_openalex.py        # Load existing JSONL, without OpenAlex requests
  inspect_warehouse.py    # Read-only table/count/sample inspection
  build_curated.py        # Transactional curated rebuild
  inspect_curated.py      # Small samples from the seven curated tables
  build_analytics.py      # Build eight analytical views and validate KPIs
  inspect_analytics.py    # Up to five ordered rows per available view
  generate_visualizations.py # Headless chart generation CLI
sql/curated/              # Ordered SQL transformations, 01 through 07
sql/analytics/            # Analytical SQL, 01 through 08
tests/                   # Offline standard-library unit tests
data/raw/openalex/        # Generated JSONL and provenance; Git-ignored
data/warehouse/           # DuckDB file and local dlt state; Git-ignored
outputs/figures/          # Generated report PNGs; Git-ignored
.env.example             # API key placeholder
.gitignore               # Secrets, caches, and local data exclusions
requirements.txt         # requests, python-dotenv, dlt[duckdb], pandas, matplotlib
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


## Curated model (Stage 4)

The flow is raw JSONL → dlt-normalized `openalex_data` → SQL → `curated`.
`openalex_data` and its `_dlt_` tables remain owned by dlt. Stage 4 never
changes those tables. The new schema is a current snapshot, rebuilt after
new Stage 3 loads; it is not refreshed automatically.

```bash
python -m scripts.build_curated
python -m scripts.inspect_curated
```

Both commands accept `--database data/warehouse/research_trends.duckdb`.
They operate locally without an API key. Run all module commands from the
repository root. SQL files are located relative to the Python module.

| Curated table | Grain / business key | Validated local rows |
| --- | --- | ---: |
| `papers` | One Work / `paper_id` | 250 |
| `topics` | One Topic / `topic_id` | 300 |
| `paper_topics` | One `(paper_id, topic_id)` pair | 719 |
| `authors` | One Author / `author_id` | 1582 |
| `paper_authors` | One `(paper_id, author_id)` pair | 1614 |
| `institutions` | One Institution / `institution_id` | 804 |
| `paper_institutions` | One `(paper_id, institution_id)` pair | 1004 |

These counts describe the local warehouse used for validation, not fixed
expectations for other extractions. Actual source tables were inspected with
DuckDB metadata and DESCRIBE before writing the transformations:
`works`, `works__topics`, `works__authorships`, and
`works__authorships__institutions`, all in `openalex_data`.

OpenAlex IDs are the public business keys. Internal joins use topic and
authorship `_dlt_parent_id` to Work `_dlt_id`; institutions join through their
parent authorship before reaching the Work. Those technical lineage keys
are excluded from curated outputs. Missing/blank entity IDs are not invented:
those entities are omitted while their identified paper remains.

Papers preserve available DOI, title, year, date, type, citations, open-access
status, primary topic, and primary source ID/name. Dates retain the source
representation. Topics include the available subfield/field/domain hierarchy.
Author bridges retain available position and corresponding-author attributes.
Institution bridges deduplicate affiliations shared by multiple authors on
the same paper. The observed warehouse supports all requested optional
paper/topic/author/institution attributes; null values remain null. Separate
source and keyword dimensions are outside this required seven-table model.

Python inspects materialized source columns and substitutes only available
projections into the SQL templates. An absent optional column is omitted,
not filled with fabricated values. Absent nested tables yield empty key-only
curated dimensions/bridges. Nested tables without entity IDs still retain
lineage internally, allowing identified institutions to survive an unknown
author. A missing root table or required lineage column is incompatible.

Dimension labels use a deterministic representative from the earliest
lexicographic Work ID, with lineage/row content as tie breakers; no claim is
made that this is the newest label. Duplicate authorship pairs use the lowest
technical authorship ID's attributes. Duplicate topic pairs retain the maximum
score. Primary-topic flags compare the relationship's topic ID with the Work's
primary topic ID; unknown primary topics produce null flags.

The bridges represent separate many-to-many relationships. Combining authors,
topics, and institutions into one flat table would multiply rows: two authors
and three topics can produce six rows for one paper. Summing citations over
that join would overcount. Citation counts remain at paper grain; Stage 5 must
choose the relationship grain deliberately when it adds analytics.

SQL runs in filename order using `CREATE OR REPLACE TABLE` inside one transaction.
Checks reject null/blank or duplicate business keys, duplicate bridge pairs,
broken bridge references, and orphan source lineage. Non-null publication years
must be between 1500 and the current UTC year plus one; this project policy
allows forthcoming works but rejects obviously invalid years. Historical
collections before 1500 require an explicit policy adjustment. Null years are
allowed. A failed build rolls back, preserving the previous curated snapshot.
Running twice against unchanged ingestion data leaves counts unchanged.

Tests use small local DuckDB fixtures and cover repeat builds, missing nested
structures, key uniqueness, references, invalid years, and rollback. No API
extraction is needed. The inspector prints counts and at most three rows per
table. Raw files and the shared DuckDB warehouse remain Git-ignored. Stage 5
uses this layer for the analytical views described below.

## Analytical SQL and KPIs (Stage 5)

`openalex_data` retains ingestion and dlt state; `curated` retains entity and
relationship grains; `analytics` provides derived query results. Stage 5
creates views, not a second copy of the curated model. It adds no dependencies
and makes no OpenAlex requests.

```bash
python -m scripts.build_analytics
python -m scripts.inspect_analytics
```

Both accept `--database data/warehouse/research_trends.duckdb`. Avoid database
filenames `analytics.duckdb` and `curated.duckdb`, which conflict with schema
names in DuckDB. Build Stage 4 first. After reloading Stage 3, rebuild Stage 4
to refresh its snapshot, then rebuild Stage 5 to revalidate the views.

| View in `analytics` | Grain and purpose |
| --- | --- |
| `overview_kpis` | One row: papers, citations, mean/median citations, OA count/share, unique entities, year range |
| `publication_trends` | One observed non-null publication year: paper/citation totals and growth |
| `topic_summary` | One linked topic: distinct papers, citations, mean/median citations, OA share |
| `topic_yearly_trends` | One linked topic and observed year: paper/citation totals and growth |
| `top_papers` | Every paper, with citation rank and available descriptive fields |
| `author_summary` | One linked author: distinct authored papers, citations, average and OA measures |
| `institution_summary` | One linked institution: distinct affiliated papers and citation measures |
| `open_access_summary` | One OA status, including `unknown`: papers and share of all papers |

The builder validates all seven Stage 4 key structures before running the
ordered SQL files. Simple `-- if` blocks include optional metrics only when
their underlying columns exist. Missing year or OA-status columns omit the
corresponding whole views; other missing fields omit only their metrics.
The current warehouse supports all eight views and all requested KPIs.
No unavailable-source metrics were filled with invented values.

Views use [CREATE OR REPLACE VIEW](https://duckdb.org/docs/current/sql/statements/create_view)
inside a transaction. They query current curated rows when read. Failure
rolls back definition changes; repeated builds do not append data. Optional
view definitions are removed if their required fields disappear. After a
curated schema change, rebuild analytics before querying it. Unchanged data,
schema, and reference year produce unchanged results.

Yearly views exclude null publication years; their paper counts therefore
reconcile to papers with known years, not necessarily the overview total.
`LAG` finds the previous observed year/count (partitioned by topic for topic
trends). A prior count is exposed only when that year is the immediately
preceding calendar year. Growth is `100 * (current - previous) / previous`,
with `NULLIF(previous, 0)` protecting division. The first year, missing-year
gaps, or zero denominators yield null growth. Missing years are not invented
as zero-volume observations. No fastest-growing topic ranking is created.

Citation sums use available citation values; averages and medians exclude
null citation counts. Empty/all-null citation groups return null aggregates,
not fabricated zero citations. Confirmed-open-access percentages divide the
number of `is_open_access=true` papers by **all** papers in that group, including
unknown flags in the denominator. They measure confirmed OA coverage, not
the closed share. Missing/blank OA status is grouped as `unknown`, never
inferred to be closed. Empty-group percentages are null.

Each domain independently joins one distinct bridge to papers. There is no
paper × topic × author × institution intermediate table. Citation totals use
full counting: a paper's full citations are attributed to each associated
topic, author, and institution rather than divided among them. Thus domain
totals must not be summed across entities to estimate unique corpus citations.
Unlinked dimension entities remain in overview unique-entity counts but do
not appear in relationship-based summaries.

Top papers use `ROW_NUMBER` ordered by citations descending, nulls last, then
paper ID ascending for deterministic ties. The view has no permanent top-N
limit. Consumers must explicitly order by `citation_rank` and choose a limit.

Raw citations favor older papers. `citations_per_year_since_publication` is
a **project-derived heuristic**, not an official OpenAlex metric or bibliometric
standard: `cited_by_count / max(1, reference_year - publication_year + 1)`.
`citation_reference_year` is the current database-session calendar year at
query time. Null/future publication years yield null, and missing citation
counts remain null. This calendar-year approximation does not account for
exact publication dates or field differences; with only one publication year
it provides no additional ranking distinction over raw citations.

Validation checks reconcile overview and yearly counts, OA category counts,
and distinct paper counts per topic/author/institution. They reject negative
counts, shares outside 0–100, non-finite division results, invalid ranking,
and broken curated keys/references. Growth percentages can legitimately be
negative or above 100; only finiteness is required for those percentages.
Fixture tests cover consecutive years, gaps, unknown years/OA, tied citations,
empty input, missing optional fields, full counting, and repeat builds.

The inspected local snapshot contains **250 papers**, all from **2025**, with
**53,488 citations**, mean **213.952**, median **87.5**, and **192 confirmed OA
papers (76.8%)**. It has **1,582 authors**, **300 topics**, and **804 institutions**.
These describe this bounded extraction, not the global OpenAlex corpus.
Year-over-year growth is unavailable because only one year is present.
Stage 6 visualizes these analytical views as described below.

## Research visualizations (Stage 6)

Install updated dependencies and generate figures from the existing analytics:

```bash
python -m pip install -r requirements.txt
python -m scripts.generate_visualizations
python -m scripts.generate_visualizations --db-path data/warehouse/research_trends.duckdb --output-dir outputs/figures --top-n 10
```

If analytics is absent or stale, run `python -m scripts.build_analytics` after
refreshing curated data. Chart generation never calls OpenAlex, reads raw
JSONL, or accesses ingestion/curated rows directly. It opens DuckDB read-only
and closes the connection after the batch. No API key is required.

Pandas is introduced only as the small tabular input to plotting functions.
Business aggregations remain in Stage 5 SQL. Ranked queries fetch only the
requested top N; topic trends fetch at most five topics' yearly results.
The citation histogram reads the full single citation column so it represents
all available papers rather than a silently sampled subset.

| PNG filename | Chart | Current 250-paper, 2025-only dataset |
| --- | --- | --- |
| `publications_over_time.png` | Ordered publication counts, with markers | Generated; one-year annotation |
| `year_over_year_growth.png` | Bars using Stage 5 growth percentages | Skipped: multi-year data required |
| `top_topics.png` | Top N topics by distinct paper count | Generated |
| `topic_trends.png` | Up to five topics over time | Skipped: multi-year data required |
| `citation_distribution.png` | Citation histogram with mean/median lines | Generated |
| `top_cited_papers.png` | Top N papers by citation count | Generated |
| `open_access_distribution.png` | OA category counts | Generated |
| `top_authors.png` | Top N authors by distinct authored papers | Generated |
| `top_institutions.png` | Top N institutions by distinct affiliated papers | Generated |

Outputs default to `outputs/figures/`. Stable filenames are overwritten on
rerun; if a chart becomes unsupported, its old batch output is removed to
avoid presenting stale trends. Other files are preserved. The entire
`outputs/` directory is Git-ignored; keep custom output directories beneath
it or add an appropriate ignore rule yourself.

Charts are 12 inches wide at 220 DPI, with restrained colors, integer count
axes, wrapped labels, and constrained layout. Titles longer than 145 characters
are shortened with an ellipsis; full titles remain in `analytics.top_papers`.
Ties use business ID ascending. `--top-n` accepts 1–30 (default 10); topic
time series deliberately stay capped at five, ranked by total observed yearly
paper volume. Individual series require at least two years. Missing calendar
years remain gaps rather than invented zero counts.

Functions in `src.visualization.charts` accept a DataFrame and output path,
return the saved Path or None when data is insufficient, and leave the input
unchanged. Ranked functions expose `top_n`; `plot_topic_trends` also accepts
explicit `topic_ids` (at most five). Rendering uses Matplotlib's
[Agg canvas](https://matplotlib.org/stable/gallery/user_interfaces/canvasagg.html)
without `plt.show()` or GUI windows. Figures are not registered with pyplot
and are cleared after saving.

Citation counts are strongly right-skewed. The default histogram bins
`log(1 + citations)` and labels its ticks with original citation counts,
including zero. Bin heights are paper counts, not density. Mean and median
are calculated in original citation units and displayed separately. Nothing
is winsorized or clipped. Pass `log_spacing=False` to the histogram function
for linear spacing. Top cited papers use a linear axis by default; their
function also accepts `log_scale=True` for a labeled symmetric-log axis.
Null/non-finite/negative histogram inputs are excluded; zero citations remain.

All charts say **current dataset** and carry a bounded-coverage caption.
The repository does not establish complete yearly OpenAlex coverage. These
plots must not be described as global AI/ML totals or global growth. One year
cannot demonstrate temporal change, and null growth is never plotted as zero.
Even future multi-year bounded extracts require comparable coverage before
interpreting count changes as research growth.

Unknown OA status remains unknown, never closed. Author and institution plots
use distinct paper counts and Stage 5's full-counting semantics: a shared paper
can count for multiple entities, so entity bars are not additive corpus totals.

Tests cover all plotting functions, empty/null data, one/multiple years, long
labels, tied top-N selection, citation skew/zeros, unknown OA, and repeatable
batch output including stale-chart cleanup. No pixel comparisons or API calls
are required. Stage 7 consumes this foundation in an interactive dashboard.

## Stage 7: interactive Streamlit dashboard

Install `requirements.txt` (the only new direct dependency is `streamlit`),
then run from the repository root with the virtual environment activated:

```powershell
streamlit run dashboard/app.py
```

Alternatively use `.venv\Scripts\python.exe -m streamlit run dashboard/app.py`.
Build Stages 3–5 first using the existing CLI commands if the warehouse is
missing. The dashboard never starts ingestion or rebuilds data.
`dashboard/config.py` resolves the default
`data/warehouse/research_trends.duckdb` relative to the repository. Set
`RESEARCH_WAREHOUSE_PATH` to override it; no credentials are needed by the UI.

The sidebar switches between five pages:

- **Overview:** corpus KPIs, publication counts, top topics, and OA distribution.
- **Research Trends:** yearly counts, available year-over-year change, and up to
  five selected topic series. A single year displays an explanatory message.
- **Topic Intelligence:** selected topic metrics, yearly counts, and its 20 most
  cited associated papers.
- **Paper Explorer:** publication year, associated topic, minimum citations,
  OA status, citation/year/title sorting, and a 10–200 row limit. Filters affect
  this page only; a zero minimum includes unknown citation counts.
- **Authors & Institutions:** ranked charts and tables with a top-5 to top-30
  control and explicit full-counting interpretation.

The eight Stage 5 views consumed are `overview_kpis`, `publication_trends`,
`topic_summary`, `topic_yearly_trends`, `top_papers`, `open_access_summary`,
`author_summary`, and `institution_summary`. The only curated access is
`curated.paper_topics` for an `EXISTS` filter: repeated topic links cannot
multiply paper rows. No raw or ingestion tables are read.

Queries use short-lived read-only DuckDB connections and parameterized filter
values; identifiers and sort choices have fixed allowlists. `st.cache_data`
caches DataFrames for 30 seconds, with at most 128 entries. Keys include the
resolved database path, file modification time and size, SQL, and all filter
parameters. Connections are never cached. Stop warehouse writers before
opening the dashboard; after a CLI refresh, rerun the page to read new data.

Stage 6 chart functions also accept `output_path=None` and return an in-memory
Matplotlib Figure. The dashboard renders it with `st.pyplot`, then clears it;
no temporary PNGs are written. A shared lock protects concurrent rendering.
Existing file export commands retain their behavior.

Coverage warnings and the loaded paper count/year range remain visible.
The current bounded sample has 250 papers from 2025, so temporal growth cannot
be inferred. Unknown OA remains unknown. Missing files/schema, absent optional
views, null metrics, and empty filter results produce friendly messages.
Topic selectors are bounded to the top 500 topics. Work type is not exposed
because the existing analytical paper view does not contain it. Charts and
rankings describe the current sample, not complete global AI research.

`tests/test_dashboard.py` checks filters, query safety, result bounds, topic
fanout, missing/empty data, in-memory rendering, and all five pages with
Streamlit AppTest. Run the full suite with `python -m unittest discover -s tests`.
There is no deployment, scheduled refresh, recommendation engine, or Stage 8.
