# Demonstration guide (5–8 minutes)

[Back to README](../README.md)

## Prepare before the demonstration

Complete the README setup and activate the virtual environment from the repository root. Prefer existing local JSONL and provenance; a fresh clone intentionally contains no data or database. If needed, prepare a small bounded extraction **before** the presentation:

```powershell
python -m scripts.extract_openalex --keyword machine-learning --year 2025 --max-records 5 --per-page 5
python -m scripts.run_pipeline
python -m scripts.check_data_quality
python -m scripts.pipeline_status
```

Confirm that the checks have no FAIL results. Explain WARN results instead of hiding them. A five-paper or one-year sample can leave charts unavailable. Do not promise growth charts or fixed counts. Stop warehouse users before running CLI writers; launch Streamlit only after the CLI portion. Keep `.env` and credential-bearing terminals out of the presentation.

## Walkthrough

| Time | Show and explain |
| --- | --- |
| 0:00–1:00 | README architecture: OpenAlex → replayable raw files → dlt/DuckDB → curated → analytics → presentation. Introduce the bounded-dataset caveat immediately. |
| 1:00–2:00 | Show one completed raw file and its provenance. Explain query, extracted count, cap, known/unknown source count and completion marker. No live API request is needed. |
| 2:00–3:00 | Rerun the orchestrator below. With unchanged completed inputs and no pending work, loading/builds are skipped. Run quality and status to distinguish successful execution from optional coverage warnings. |
| 3:00–4:00 | Inspect curated/analytics outputs. Use the ER diagram to explain paper grain, independent bridges and why citation totals are not summed across authors. |
| 4:00–6:30 | Launch the dashboard. Show Overview, the single-year/growth explanation in Research Trends, one topic, Paper Explorer filters, and Authors & Institutions. Keep coverage captions visible. |
| 6:30–7:30 | Close with design choices: replayable JSONL, dlt normalization, local DuckDB, SQL metrics, merge, independent dashboard and fingerprint-based recovery. State the source/coverage and local-system limitations. |

Commands for the local CLI portion:

```powershell
Get-ChildItem data/raw/openalex -Filter *.jsonl
$provenance = Get-ChildItem data/raw/openalex -Filter *.metadata.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Get-Content -LiteralPath $provenance.FullName
python -m scripts.run_pipeline
python -m scripts.check_data_quality
python -m scripts.pipeline_status
python -m scripts.inspect_curated
python -m scripts.inspect_analytics
streamlit run dashboard/app.py
```

Use the matching JSONL filename to show a selected Work if helpful; do not dump the full dataset. The commands assume preparation produced a sidecar. An unchanged pipeline success does not mean new OpenAlex data was fetched. If a rebuild is needed, prepare it with `python -m scripts.run_pipeline --rebuild-downstream` before the timed demonstration.

In Paper Explorer, select an associated topic, adjust citation/year/OA filters and show the bounded row limit. Clarify that filters apply only to that page. For a one-year sample, explicitly demonstrate that the application declines to infer growth. Static figures can be shown from `outputs/figures/` when available; they remain local, generated artifacts.

## Expected outcome

The audience should be able to trace a record from source to analytical output, identify the grain of each relationship, understand a skipped incremental run, and distinguish data-quality warnings from pipeline failures. Actual counts and available charts depend on the prepared data; there is no fixed result to reproduce and no claim of complete worldwide research coverage.
