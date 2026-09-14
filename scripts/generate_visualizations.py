"""Save report-ready charts of the current local analytical dataset."""

import argparse
from pathlib import Path
import sys

import duckdb

from src.visualization.generate import DEFAULT_DATABASE, DEFAULT_OUTPUT, generate_visualizations


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top-n", type=int, choices=range(1, 31), default=10, metavar="1-30")
    args = parser.parse_args(argv)
    try:
        generated, skipped = generate_visualizations(args.db_path, args.output_dir, args.top_n)
    except (OSError, ValueError, duckdb.Error) as error:
        print(f"Visualization generation failed ({type(error).__name__}). "
              "Check database/analytics availability, output permissions, and arguments.", file=sys.stderr)
        return 1
    print(f"Finished: {len(generated)} charts saved, {len(skipped)} skipped. "
          f"Output: {args.output_dir.resolve()}")
    print("Coverage: bounded current dataset; these are not global publication totals.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
