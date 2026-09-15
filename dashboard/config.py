"""Central, non-secret dashboard configuration."""
import os
from pathlib import Path
from src.config import DEFAULT_DATABASE, PROJECT_ROOT as PROJECT_ROOT, resolve_path



def database_path() -> Path:
    return resolve_path(os.getenv("RESEARCH_WAREHOUSE_PATH", str(DEFAULT_DATABASE)))


COVERAGE = (
    "Current warehouse contains a bounded OpenAlex dataset. Counts reflect loaded "
    "records, not complete global research output. Extraction coverage has not been verified."
)
