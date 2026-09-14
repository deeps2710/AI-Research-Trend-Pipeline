"""Inspect local operational state without writing or starting Streamlit."""
import argparse
from pathlib import Path
import sys

import duckdb
from src.orchestration.pipeline import DEFAULT_DATABASE, RAW_DIRECTORY, discover, file_key, fingerprint


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=DEFAULT_DATABASE)
    parser.add_argument('--raw-directory', type=Path, default=RAW_DIRECTORY)
    args = parser.parse_args(argv)
    try:
        if not args.database.is_file():
            print('No warehouse or pipeline history yet.')
            return 0
        with duckdb.connect(str(args.database), read_only=True) as con:
            if not con.execute("SELECT 1 FROM information_schema.tables WHERE table_schema='ops' AND table_name='pipeline_runs'").fetchone():
                print('No orchestration history yet.')
                return 0
            for row in con.execute('SELECT run_id,status,started_at,finished_at,raw_files_processed,error_stage,error_message FROM ops.pipeline_runs ORDER BY started_at DESC LIMIT 10').fetchall():
                print(' | '.join(str(value) for value in row))
            known = dict(con.execute('SELECT file_path,file_hash FROM ops.processed_files').fetchall())
            print('Known processed files:', len(known))
            print('Most recent success:', con.execute("SELECT max(finished_at) FROM ops.pipeline_runs WHERE status='success'").fetchone()[0])
            print('Pending downstream / visualizations:', con.execute('SELECT downstream_pending,visualizations_pending FROM ops.pipeline_state WHERE id=1').fetchone())
        print('Pending raw files:', sum(known.get(file_key(p)) != fingerprint(p) for p in discover(args.raw_directory)))
    except (duckdb.Error, OSError):
        print('Status unavailable; check warehouse access and operational schema.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
