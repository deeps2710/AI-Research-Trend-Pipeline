# Core release v1.0.0

Validated on 2026-09-15. This release marks the completed data-engineering core. See the [README](../README.md) for setup and commands, [architecture](architecture.md) for recovery behavior, and [demo guide](demo.md) for the local 5–8 minute walkthrough.

## Release scope

The core includes OpenAlex exploration; bounded cursor extraction with retry/backoff and JSONL provenance; dlt normalization and Work-ID merge into DuckDB; seven curated entity/bridge tables; eight schema-dependent analytical views; Matplotlib exports; five Streamlit pages; SHA-256 file incrementality; run/pending state; persisted quality gates; rotating logs; centralized configuration; and a private-copy benchmark. No application architecture or dependency changes were needed for release validation.

## Validation evidence

Validation used Python **3.13.4 on Windows**. The syntax/dependency floor is Python 3.11; other interpreters were not tested. Installed versions were requests 2.34.2, python-dotenv 1.2.3, dlt 1.30.0, DuckDB 1.5.5, Pandas 3.0.5, Matplotlib 3.11.2, Streamlit 1.63.0 and Ruff 0.16.7. This records the tested environment, not a dependency lockfile.

| Check | Result |
| --- | --- |
| Full unittest suite | 81 passed, 0 failed, 0 skipped; 115.023 seconds |
| Ruff | Configured `F` / `E9` checks passed |
| Compile/imports | All maintained modules in `src`, `scripts` and `dashboard` imported; compileall passed |
| Dependencies | Required stack imports and `pip check` passed |
| CLI/documentation | All 13 CLI help commands passed; database aliases, documented modules, paths and relative links checked |
| Tracked-file audit | No tracked credentials, raw JSONL, databases, environments, logs, generated figures or temporary artifacts found; ignore rules verified |
| Dashboard | Server health and all five pages passed; dynamic paper KPI, filters, empty state, one-year messaging, coverage warning and absence of dlt columns checked |
| Failure behavior | Temporary-fixture tests passed for rejected raw data, quality gates, rollback, interrupted runs, lock release and retry recovery |

Expected test output includes Streamlit's bare-mode/cache messages and deliberately triggered quality warnings/errors from negative fixtures. These were not test failures and no checks were suppressed.

### Local warehouse snapshot

The available warehouse held **250 distinct Works / 250 curated papers, all from 2025**. The real quality CLI reported **62 PASS, 4 WARN, 0 FAIL**. Warnings were DOI coverage (99.6%), identified authors (95.6%), institution links (96.0%) and a single publication year. Title, primary-topic and known OA coverage were 100%.

The real orchestrator recorded a successful unchanged run: four completed raw files discovered, four skipped, zero processed. Status showed four known processed files, zero pending raw files, and both downstream/visualization flags false. Last-success time and age appeared correctly; a no-op success does not indicate a new source extraction or satisfy a production freshness SLA.

These are validation observations from a bounded local dataset, not fixed expectations for a new clone, global research totals or evidence of longitudinal growth.

### Reproducibility and idempotency

A separate checkout containing only tracked files was created from Git, without `.env`, pre-existing data, local dlt state or `PYTHONPATH`. Using the existing validated interpreter/dependencies and the three-Work, two-year offline fixture, it successfully executed:

```powershell
python -m scripts.run_pipeline
python -m scripts.run_pipeline
python -m scripts.run_pipeline --force --skip-visualizations
python -m scripts.run_pipeline --rebuild-downstream
python -m scripts.run_pipeline --rebuild-downstream
python -m scripts.check_data_quality
python -m scripts.pipeline_status
```

The unchanged run processed zero files. Forced replay retained three root rows and three distinct Work IDs. Both downstream rebuilds produced identical rows across all curated tables and analytics views, successful run records and clear pending flags. All nine supported chart filenames remained stable across regeneration. Existing tests also verify stale-chart cleanup when data becomes insufficient.

The full suite verifies bounded extraction and exploration with mocked HTTP, merge updates and nested replacement, filter behavior, missing data and multi-year logic. Stage 12 made no live OpenAlex extraction. A new virtual environment and fresh online dependency installation were not repeated; unpinned runtime dependencies remain a reproducibility limitation. The tracked-only checkout validates repository completeness using the tested installed stack.

### Representative benchmark

The real `python -m scripts.benchmark_pipeline` command rebuilt a private copy of the 250-paper warehouse:

| Operation | Time |
| --- | ---: |
| Curated build | 2,075.00 ms |
| Analytics build | 1,235.07 ms |
| Quality check/persistence | 2,105.54 ms |
| Top topics query | 38.29 ms |
| Top papers query | 6.58 ms |
| Filtered papers query | 11.66 ms |
| Authors query | 30.81 ms |
| Institutions query | 29.01 ms |

Query values are medians of three warm executions after warm-up; build/check values are single executions. They include result fetching and exclude database copy time. These are local diagnostics, not a scale claim. No optimization was warranted for this validation workload.

## Handoff boundaries and future work

The completed core is ready for a local demonstration with prepared data. Source metadata coverage, OpenAlex topic assignments, citation-age bias, full-count attribution and bounded extraction constrain interpretation. File hashes provide local incrementality, not API CDC: source deletion handling and update chronology are absent, and older replayed records can overwrite newer metadata. Runtime dependencies are not locked; local DuckDB writers must be coordinated with dashboard use. Source synchronization may require eligible paid API access.

Stage 13 remains separate: screenshot capture, README visual insertion and the academic/project report have not been started. Optional later work could add semantic search, embeddings/vector retrieval, recommendations, clustering, LLM summaries, RAG, citation/author graph analysis or richer scheduling/deployment. None is part of v1.0.0 or required to demonstrate this data-engineering release.
