"""Run and persist warehouse quality checks; warnings do not fail the command."""
import argparse
from collections import Counter
from pathlib import Path
from src.load.openalex_dlt import DEFAULT_DATABASE
from src.logging_config import configure_logging
from src.quality.runner import run_quality
from src.quality.models import Status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args(argv)
    try:
        configure_logging()
        execution, results = run_quality(args.database)
    except Exception:
        print('Quality unavailable: check warehouse existence, schema and exclusive access.')
        return 1
    print('Quality execution:', execution)
    for layer in sorted({r.layer for r in results}):
        counts = Counter(r.status.value for r in results if r.layer == layer)
        print(layer, ' '.join(f'{status.value}={counts[status.value]}' for status in Status))
        for r in results:
            if r.layer == layer and (r.status != Status.PASS or layer == 'coverage'):
                print(f'  {r.status.value} {r.check_name}: {r.observed_value}; {r.details}')
    return int(any(r.status == Status.FAIL for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
