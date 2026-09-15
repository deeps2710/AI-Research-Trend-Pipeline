"""Benchmark local builds and queries on a temporary copy; no network requests."""
import argparse
from pathlib import Path
import sys
import duckdb
from src.config import DEFAULT_DATABASE
from src.benchmark import benchmark


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db-path','--database',dest='database',type=Path,default=DEFAULT_DATABASE)
    parser.add_argument('--explain',action='store_true',help='Print EXPLAIN ANALYZE plans after query timing')
    args = parser.parse_args(argv)
    try:
        benchmark(args.database,explain=args.explain)
    except (OSError,ValueError,duckdb.Error):
        print('Benchmark failed; check local warehouse access, source schema and quality.',file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
