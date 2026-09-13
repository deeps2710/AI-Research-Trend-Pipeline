"""Display small, ordered analytical samples without Pandas."""

import argparse
from pathlib import Path
import sys

import duckdb

from src.transform.analytics import DEFAULT_DATABASE, VIEW_NAMES
from src.transform.curated import columns


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args(argv)
    if not args.database.is_file():
        print("Warehouse absent; build Stages 4 and 5 first.", file=sys.stderr)
        return 1
    try:
        with duckdb.connect(str(args.database), read_only=True) as connection:
            if not columns(connection, "analytics", "overview_kpis"):
                print("Analytics absent; run scripts.build_analytics first.", file=sys.stderr)
                return 1
            for name in VIEW_NAMES:
                fields = columns(connection, "analytics", name)
                if not fields:
                    print(f"\n{name}: unavailable")
                    continue
                if "citation_rank" in fields:
                    ordering = "citation_rank"
                elif "publication_year" in fields and "paper_count" in fields:
                    ordering = "publication_year DESC" + (", topic_id" if "topic_id" in fields else "")
                elif "paper_count" in fields:
                    key = next(key for key in ("topic_id", "author_id", "institution_id", "oa_status") if key in fields)
                    ordering = f"paper_count DESC, {key}"
                else:
                    ordering = "1"
                result = connection.execute(f"SELECT * FROM analytics.{name} ORDER BY {ordering} LIMIT 5")
                print(f"\n{name}:")
                names = [column[0] for column in result.description]
                for row in result.fetchall():
                    print(dict(zip(names, row)))
    except (duckdb.Error, OSError):
        print("Cannot inspect analytics; check database access and rebuild Stage 5 after schema changes.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
