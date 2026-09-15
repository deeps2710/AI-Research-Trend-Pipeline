"""Streaming local JSONL ingestion through dlt's DuckDB destination."""

import json
from collections.abc import Iterator
from pathlib import Path

import dlt
from src.load.files import discover


from src.config import DEFAULT_DATABASE as DEFAULT_DATABASE, RAW_DIRECTORY as RAW_DIRECTORY, PathLike, resolve_path
DATASET_NAME = "openalex_data"
PIPELINE_NAME = "openalex_pipeline"


class InvalidWorkFile(ValueError):
    """A safe input diagnostic that excludes raw record contents."""


def resolve_input(input_file=None, raw_directory=RAW_DIRECTORY) -> Path:
    """Find an explicit JSONL or the newest completed Stage 2 extraction."""
    if input_file is None:
        candidates = discover(raw_directory)
        if not candidates:
            raise FileNotFoundError(
                f"No completed JSONL extraction in {raw_directory}; run Stage 2 first."
            )
        input_file = max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name))
    path = resolve_path(input_file)
    if path.suffix.lower() != ".jsonl":
        raise InvalidWorkFile("Input must be a .jsonl file, not a metadata sidecar.")
    if not path.is_file():
        raise FileNotFoundError(f"JSONL input not found: {path}")
    return path


def read_jsonl(input_file: PathLike) -> Iterator[dict]:
    """Yield validated dictionaries one line at a time; never flatten records."""
    path = Path(input_file)
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                raise InvalidWorkFile(
                    f"{path}, line {line_number}: malformed JSON"
                ) from None
            if not isinstance(record, dict):
                raise InvalidWorkFile(f"{path}, line {line_number}: expected a JSON object")
            if not isinstance(record.get("id"), str) or not record["id"].strip():
                raise InvalidWorkFile(
                    f"{path}, line {line_number}: missing or invalid Work id"
                )
            yield record


@dlt.resource(name="works", primary_key="id", write_disposition="merge")
def works(input_file):
    yield from read_jsonl(input_file)


@dlt.source(name="openalex", root_key=True)
def openalex_source(input_file):
    """Propagate root IDs to all nested child tables from the first load."""
    return works(input_file)


def create_pipeline(database_path: PathLike = DEFAULT_DATABASE):
    database_path = resolve_path(database_path)
    if database_path.stem.casefold() == DATASET_NAME.casefold():
        raise ValueError(f"Database filename must differ from dataset {DATASET_NAME}")
    database_path.parent.mkdir(parents=True, exist_ok=True)
    # Separate local state per database, including when --database is overridden.
    state_directory = database_path.parent / ".dlt_pipelines" / database_path.name
    return dlt.pipeline(
        pipeline_name=PIPELINE_NAME,
        pipelines_dir=str(state_directory),
        destination=dlt.destinations.duckdb(str(database_path)),
        dataset_name=DATASET_NAME,
        dev_mode=False,
    )


def load_file(input_file: PathLike, database_path: PathLike = DEFAULT_DATABASE):
    """Load raw Works; dlt owns schema inference and nested merge behavior."""
    input_file = resolve_input(input_file)
    pipeline = create_pipeline(database_path)
    info = pipeline.run(openalex_source(str(input_file)))
    info.raise_on_failed_jobs()
    return info
