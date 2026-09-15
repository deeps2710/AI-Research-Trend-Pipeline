"""Inspect local operational state without writing or starting Streamlit."""
import argparse
from pathlib import Path
import sys

import duckdb
from src.config import DEFAULT_DATABASE, RAW_DIRECTORY
from src.orchestration.status import report_status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db-path', '--database', dest='database', type=Path, default=DEFAULT_DATABASE)
    parser.add_argument('--raw-directory', type=Path, default=RAW_DIRECTORY)
    args = parser.parse_args(argv)
    try:
        return report_status(args.database, args.raw_directory)
    except (duckdb.Error, OSError):
        print('Status unavailable; check warehouse access and operational schema.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
