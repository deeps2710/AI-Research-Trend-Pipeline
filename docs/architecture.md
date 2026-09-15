# Architecture and recovery

[Back to README](../README.md)

## Ownership and execution

Extraction (`src/extract/`) uses a requests session, bounded cursor pagination and retries for transient failures. It streams selected Work objects to JSONL, preserving nested structures. Files and provenance first receive `.inprogress` suffixes. The final `.metadata.json` sidecar is published last as the completion marker; the two renames are not a single atomic transaction. Interrupted extraction is not automatically resumed.

`src/load/files.py` discovers top-level completed JSONL files. `src/load/openalex_dlt.py` streams validated objects into dlt pipeline `openalex_pipeline`, dataset `openalex_data`, root table `works`. The resource has primary key `id`, merge disposition and root-key propagation for replacement of nested descendants. dlt owns normalized children, its internal `_dlt_` tables and `openalex_data_staging` when used by loading. Child-table presence depends on the source data. Keep dlt tracking tables and local `.dlt_pipelines/<database-filename>/` state.

`src/transform/` inspects available source columns and runs the ordered SQL in `sql/curated/` and `sql/analytics/`. Curated tables are rebuilt transactionally; analytical view definitions are built in their own transaction. Failed builds roll back that layer. Analytics queries current curated rows; refresh both layers after ingestion or schema changes. Optional source columns can be absent rather than merely null, so dependent projections or views are omitted.

`src/visualization/` reads analytics into Pandas for Matplotlib export. `dashboard/` is a separate read-only consumer: it does not load raw files, invoke the pipeline or write figures. Its queries use explicit projections, parameterized values and allowlisted sort choices. Cached results include database path, modification time/size, SQL and parameters; connections are not cached.

## Incremental state

| Table | Stored state |
| --- | --- |
| `ops.pipeline_runs` | Run UUID, start/end, running/success/failed status, discovered/processed file counts and safe failure stage/summary |
| `ops.processed_files` | Normalized path, SHA-256, byte size, processing time, submitted record count and run UUID |
| `ops.pipeline_state` | Singleton row with downstream and visualization pending flags |
| `ops.data_quality_results` | Execution UUID, optional run UUID, check/layer/status, observed aggregate, expected condition, details and check time |

File identity is the normalized path plus the content hash. Repository-local paths are stored relatively; external paths are absolute. Renaming a file makes it eligible again. Metadata-only edits do not change its JSONL fingerprint. `records_loaded` counts submitted records, not newly inserted Works.

The orchestrator snapshots each pending raw file privately, validates it and its sidecar, then merges the snapshot. Its recorded hash therefore describes loaded bytes. Successful processing advances the fingerprint; downstream work is marked pending before loading. Files are processed in lexicographic path order. For repeated Work IDs, later processed data wins; this is not source-update chronology, and missing Works do not trigger deletion.

## Failure and retry behavior

1. Raw FAIL results are persisted before ingestion and block loading that file.
2. A failed load does not advance its fingerprint. Successfully processed earlier files remain recorded.
3. Curated and analytics gates stop dependent work on FAIL; optional coverage WARN results continue.
4. Pending flags retain incomplete downstream work. After correcting the cause, rerun `python -m scripts.run_pipeline`.
5. A crash after merge but before fingerprint recording can replay the file next time. Work-ID merge makes this at-least-once behavior safe for duplicate identity; there is no transaction spanning the entire pipeline.

An OS advisory companion lock prevents overlapping orchestrators and releases on process exit. On acquiring it, a new run marks abandoned `running` records failed/interrupted. Independent stage CLIs and other applications do not honor this lock; stop them before writing. Failures before database access cannot be recorded in ops.

| Situation | Action |
| --- | --- |
| No new files and no pending state | Normal run records success and skips loading/builds |
| Corrected failed input or downstream issue | Rerun normally; inspect quality/status/logs |
| Warehouse changed through independent stage commands | Run `--rebuild-downstream` to rebuild and reassess |
| Intentionally reprocess every discovered file | Use `--force`; this still merges rather than appends |
| Defer charts | Use `--skip-visualizations`; the next enabled run catches up |
| Missing/empty raw directory | Successful no-op if no downstream work is pending; inspect the configured path |

## Quality and observability boundaries

Raw checks require nonempty valid JSONL, nonblank string Work IDs and consistent available provenance counts. Curated checks validate all seven key structures and bridge references. Known citations must be finite/nonnegative; known years must be 1500 through the current UTC year plus one. Analytics checks reconcile paper-grain counts, OA percentages, entity counts and deterministic citation ranking.

Coverage checks compare available DOI, title, primary topic, identified authors, institutions and known OA metadata to all curated papers. Full coverage passes; partial coverage warns, with no minimum acceptance threshold. Fewer than two known publication years warns. Empty datasets have unavailable coverage percentages.

The standalone quality command reads curated/analytics, then writes only ops history. It does not revalidate every stored raw file. A fully unchanged orchestrator run does not rerun gates; explicitly check quality or rebuild when reassessment is needed.

Status shows the latest quality execution, or the whole run's checks when linked to a pipeline run. Quality time, processing success time and extraction time mean different things. Last-success age is informational and can refer to a no-op run; it is not API freshness. Logs contain safe stage summaries, counts, hashes and durations, with rotating files under `logs/`. Neither logs nor local state belong in Git.

## Why these boundaries?

Raw replay separates API availability from downstream development. dlt handles ingestion normalization while project SQL defines business grains. Transactional layer rebuilds preserve the previous valid snapshot on failure. Views centralize metric definitions without duplicate materialized outputs. Independent presentation keeps refresh work explicit. File fingerprints provide useful local incrementality without a scheduler or source CDC implementation.
