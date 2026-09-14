"""Process new/changed completed raw extractions, then rebuild dependent layers."""
import argparse
from pathlib import Path
import sys

from src.orchestration.pipeline import run_pipeline, DEFAULT_DATABASE, RAW_DIRECTORY, DEFAULT_OUTPUT
from src.logging_config import configure_logging


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=DEFAULT_DATABASE)
    parser.add_argument('--raw-directory', type=Path, default=RAW_DIRECTORY)
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--rebuild-downstream', action='store_true')
    parser.add_argument('--skip-visualizations', action='store_true')
    args = parser.parse_args(argv)
    try:
        configure_logging()
        run_pipeline(**vars(args))
    except KeyboardInterrupt:
        return 130
    except Exception:
        print('Pipeline failed. Check pipeline_status, completed raw inputs, and exclusive warehouse access.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
