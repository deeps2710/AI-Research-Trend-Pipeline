"""Load an existing Stage 2 JSONL extraction into persistent DuckDB."""

import argparse
from pathlib import Path
import sys

from src.load.openalex_dlt import (
    DATASET_NAME, DEFAULT_DATABASE, InvalidWorkFile, load_file, resolve_input,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-file", type=Path)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args(argv)
    try:
        input_file = resolve_input(args.input_file)
        print(f"Loading: {input_file}")
        info = load_file(input_file, args.database)
    except (FileNotFoundError, InvalidWorkFile) as error:
        print(f"Load failed: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        # dlt wraps reader errors; show only our safe diagnostic, not raw rows.
        cause = error
        while cause is not None and not isinstance(cause, InvalidWorkFile):
            cause = cause.__cause__ or cause.__context__
        if cause is not None:
            print(f"Load failed: {cause}", file=sys.stderr)
        else:
            print(
                f"Load failed ({type(error).__name__}). Check the JSONL encoding, "
                "database path/permissions, and whether another process holds the "
                "database open. Inspect local dlt state for failed jobs.",
                file=sys.stderr,
            )
        return 1
    print(info)
    print(f"Load complete: {args.database.resolve()} | dataset={DATASET_NAME}, resource=works")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
