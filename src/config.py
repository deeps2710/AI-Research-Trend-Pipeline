"""Non-secret, repository-anchored defaults shared by every stage."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIRECTORY = PROJECT_ROOT / 'data/raw/openalex'
DEFAULT_DATABASE = PROJECT_ROOT / 'data/warehouse/research_trends.duckdb'
DEFAULT_OUTPUT = PROJECT_ROOT / 'outputs/figures'
LOG_DIRECTORY = PROJECT_ROOT / 'logs'
PathLike = str | Path


def resolve_path(path: PathLike) -> Path:
    """Explicit relative overrides use the caller's cwd; defaults are absolute."""
    return Path(path).expanduser().resolve()
