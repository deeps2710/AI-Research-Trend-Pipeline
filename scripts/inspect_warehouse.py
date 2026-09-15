"""Inspect the local warehouse without Pandas or a database GUI."""

import argparse
from pathlib import Path
import sys

import duckdb

from src.load.openalex_dlt import DATASET_NAME, DEFAULT_DATABASE


def inspect_warehouse(database_path):
    path = Path(database_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Warehouse not found: {path}. Run the loader first.")
    print(f"Database: {path}")
    with duckdb.connect(str(path), read_only=True) as connection:
        schemas = connection.execute(
            "SELECT schema_name FROM information_schema.schemata ORDER BY schema_name"
        ).fetchall()
        print("Schemas: " + ", ".join(sorted({row[0] for row in schemas})))
        tables = [row[0] for row in connection.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = ? ORDER BY table_name", [DATASET_NAME]
        ).fetchall()]
        print(f"Tables in {DATASET_NAME}: " + (", ".join(tables) or "(none)"))
        print("dlt internal tables: " + (
            ", ".join(name for name in tables if name.startswith("_dlt_")) or "(none)"
        ))
        if "works" not in tables:
            print("No works table yet.")
            return
        count = connection.execute("SELECT count(*) FROM openalex_data.works").fetchone()[0]
        print(f"Works row count: {count}")
        available = {row[0] for row in connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = ? AND table_name = 'works'", [DATASET_NAME]
        ).fetchall()}
        columns = [name for name in ("id", "title", "publication_year", "cited_by_count")
                   if name in available]
        if columns:
            print("Sample fields: " + ", ".join(columns))
            # Column names are selected only from the fixed allowlist above.
            for row in connection.execute(
                f"SELECT {', '.join(columns)} FROM openalex_data.works LIMIT 5"
            ).fetchall():
                print(row)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", "--database", dest="database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args(argv)
    try:
        inspect_warehouse(args.database)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 1
    except (duckdb.Error, OSError):
        print("Cannot inspect warehouse. Check the database file, permissions, "
              "and other processes using it.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
