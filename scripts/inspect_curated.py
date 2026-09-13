"""Show curated grains and small samples without a GUI."""
import argparse
from pathlib import Path
import sys
import duckdb
from src.transform.curated import DEFAULT_DATABASE, TABLE_KEYS


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args(argv)
    if not args.database.is_file():
        print("Warehouse absent; run Stage 3 first.", file=sys.stderr)
        return 1
    try:
        with duckdb.connect(str(args.database), read_only=True) as connection:
            print(f"Database: {args.database.resolve()}")
            for table in TABLE_KEYS:
                count = connection.execute(f"SELECT count(*) FROM curated.{table}").fetchone()[0]
                print(f"\n{table}: {count} rows")
                result = connection.execute(f"SELECT * FROM curated.{table} ORDER BY 1 LIMIT 3")
                print([column[0] for column in result.description])
                for row in result.fetchall():
                    print(row)
    except duckdb.Error:
        print("Cannot inspect curated tables; run build_curated and check database access.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
