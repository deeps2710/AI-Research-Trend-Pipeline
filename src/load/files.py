"""Completed raw-file discovery and stable identity without importing dlt."""
import hashlib
from pathlib import Path
from src.config import PROJECT_ROOT as ROOT, PathLike


def fingerprint(path: PathLike) -> str:
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def file_key(path: PathLike) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def discover(raw_directory: PathLike) -> list[Path]:
    # Stage 2 publishes the final sidecar last, as its completion marker.
    return sorted((p.resolve() for p in Path(raw_directory).glob('*.jsonl')
                   if p.is_file() and p.with_suffix('.metadata.json').is_file()),
                  key=lambda p: p.as_posix())
