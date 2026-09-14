"""Central, non-secret dashboard configuration."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def database_path():
    return Path(os.getenv("RESEARCH_WAREHOUSE_PATH", str(
        PROJECT_ROOT / "data/warehouse/research_trends.duckdb"
    ))).expanduser().resolve()


COVERAGE = (
    "Current warehouse contains a bounded OpenAlex dataset. Counts reflect loaded "
    "records, not complete global research output. Extraction coverage has not been verified."
)
