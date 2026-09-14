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
            tables = set(con.execute("SELECT table_schema,table_name FROM information_schema.tables").fetchall())
            known = {}
            if ('ops','pipeline_runs') in tables:
                for row in con.execute("SELECT run_id,status,started_at,finished_at,raw_files_processed,error_stage,error_message,epoch(finished_at-started_at) AS duration_seconds FROM ops.pipeline_runs ORDER BY started_at DESC LIMIT 10").fetchall():
                    print(' | '.join(str(value) for value in row))
                success = con.execute("SELECT max(finished_at) FROM ops.pipeline_runs WHERE status='success'").fetchone()[0]
                print('Most recent success:', success)
                from datetime import datetime, timezone
                print('Age since success:', datetime.now(timezone.utc)-success if success else 'unavailable')
            else:
                print('No orchestration history yet; freshness unavailable.')
            if ('ops','processed_files') in tables:
                known = dict(con.execute('SELECT file_path,file_hash FROM ops.processed_files').fetchall())
                print('Known processed files:',len(known))
                print('Latest submitted file records:',con.execute('SELECT records_loaded FROM ops.processed_files ORDER BY processed_at DESC LIMIT 5').fetchall())
            if ('ops','pipeline_state') in tables:
                print('Pending downstream / visualizations:', con.execute('SELECT downstream_pending,visualizations_pending FROM ops.pipeline_state WHERE id=1').fetchone())
            if ('ops','data_quality_results') in tables:
                latest = con.execute('SELECT execution_id,run_id,checked_at FROM ops.data_quality_results ORDER BY checked_at DESC LIMIT 1').fetchone()
                if latest:
                    condition, identifier = ('run_id=?',latest[1]) if latest[1] else ('execution_id=?',latest[0])
                    counts = dict(con.execute('SELECT status,count(*) FROM ops.data_quality_results WHERE '+condition+' GROUP BY status',[identifier]).fetchall())
                    overall = 'FAIL' if counts.get('FAIL') else 'WARN' if counts.get('WARN') else 'PASS'
                    print('Latest quality:',overall,'checked_at:',latest[2], 'scope:',identifier)
                    print('Quality counts:', ' '.join(f'{status}={counts.get(status,0)}' for status in ('PASS','WARN','FAIL')))
                    for row in con.execute('SELECT check_name,status,observed_value FROM ops.data_quality_results WHERE '+condition+" AND status<>'PASS'",[identifier]).fetchall():
                        print('Quality finding:', *row)
                else:
                    print('Quality history empty.')
            else:
                print('Quality not checked yet.')
            for schema, table in [('openalex_data','works'),('curated','papers')]:
                if (schema,table) in tables:
                    print(f'{schema}.{table} count:',con.execute(f'SELECT count(*) FROM {schema}.{table}').fetchone()[0])
            fields = {row[0] for row in con.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='curated' AND table_name='papers'").fetchall()}
            if 'publication_year' in fields:
                print('Publication years:',con.execute('SELECT min(publication_year),max(publication_year),count(DISTINCT publication_year) FROM curated.papers').fetchone())
        print('Pending raw files:', sum(known.get(file_key(p)) != fingerprint(p) for p in discover(args.raw_directory)))
    except (duckdb.Error, OSError):
        print('Status unavailable; check warehouse access and operational schema.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
