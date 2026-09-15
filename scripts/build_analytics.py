"""Create analytical views and validate local KPI calculations."""

import argparse
from pathlib import Path
import sys

import duckdb

from src.transform.analytics import AnalyticsError, DEFAULT_DATABASE, build_analytics
from src.transform.curated import CuratedError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", "--database", dest="database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args(argv)
    try:
        _, kpis = build_analytics(args.database)
    except (AnalyticsError, CuratedError) as error:
        print(f"Analytics build failed: {error}", file=sys.stderr)
        return 1
    except (duckdb.Error, OSError):
        print("Analytics build failed: check SQL, warehouse compatibility, and file access. "
              "Previous analytics definitions were preserved.", file=sys.stderr)
        return 1
    print("Analytics checks passed. Overview KPIs:")
    for name, value in kpis.items():
        print(f"  {name}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
