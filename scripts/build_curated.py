"""Rebuild and validate the local curated warehouse model."""
import argparse
from pathlib import Path
import sys
import duckdb
from src.transform.curated import DEFAULT_DATABASE, CuratedError, build_curated


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", "--database", dest="database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args(argv)
    try:
        counts = build_curated(args.database)
    except CuratedError as error:
        print(f"Build failed: {error}", file=sys.stderr)
        return 1
    except (duckdb.Error, OSError):
        print("Build failed: incompatible warehouse/SQL or database access error. "
              "Previous curated data was preserved.", file=sys.stderr)
        return 1
    print("Quality checks passed. Curated row counts:")
    for table, count in counts.items():
        print(f"  {table}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
