"""Fingerprint completed extractions and coordinate the existing stages."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import time
import uuid

import duckdb

from src.load.openalex_dlt import DEFAULT_DATABASE, RAW_DIRECTORY, load_file, read_jsonl
from src.transform.curated import build_curated
from src.transform.analytics import build_analytics
from src.visualization.generate import DEFAULT_OUTPUT, generate_visualizations

ROOT = Path(__file__).resolve().parents[2]


def fingerprint(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def file_key(path):
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def discover(raw_directory):
    # Stage 2 publishes the final sidecar last, as its completion marker.
    return sorted((p.resolve() for p in Path(raw_directory).glob('*.jsonl')
                   if p.is_file() and p.with_suffix('.metadata.json').is_file()),
                  key=lambda p: p.as_posix())


@contextmanager
def run_lock(database):
    """OS-released advisory lock; a crash never leaves a stale held lock."""
    lock = Path(str(database) + '.pipeline.lock')
    with lock.open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('Another orchestrator is using this warehouse') from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def execute(database, sql, parameters=()):
    # No open connection spans a dlt/build call.
    with duckdb.connect(str(database)) as con:
        return con.execute(sql, parameters).fetchall()


def initialize(database):
    execute(database, """CREATE SCHEMA IF NOT EXISTS ops;
        CREATE TABLE IF NOT EXISTS ops.pipeline_runs (
            run_id VARCHAR PRIMARY KEY, started_at TIMESTAMPTZ DEFAULT current_timestamp,
            finished_at TIMESTAMPTZ, status VARCHAR, raw_files_discovered INTEGER DEFAULT 0,
            raw_files_processed INTEGER DEFAULT 0, error_stage VARCHAR, error_message VARCHAR);
        CREATE TABLE IF NOT EXISTS ops.processed_files (
            file_path VARCHAR PRIMARY KEY, file_hash VARCHAR, file_size BIGINT,
            processed_at TIMESTAMPTZ, records_loaded BIGINT, run_id VARCHAR);
        CREATE TABLE IF NOT EXISTS ops.pipeline_state (
            id INTEGER PRIMARY KEY, downstream_pending BOOLEAN, visualizations_pending BOOLEAN);
        INSERT INTO ops.pipeline_state VALUES (1,false,false) ON CONFLICT DO NOTHING;
        UPDATE ops.pipeline_runs SET status='failed', finished_at=current_timestamp,
            error_stage='interrupted', error_message='Previous process ended before completion'
            WHERE status='running';""")


def run_pipeline(database=DEFAULT_DATABASE, raw_directory=RAW_DIRECTORY, *, force=False,
                 rebuild_downstream=False, skip_visualizations=False, output_dir=DEFAULT_OUTPUT):
    database = Path(database).resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    with run_lock(database):
        initialize(database)
        run_id = str(uuid.uuid4())
        execute(database, "INSERT INTO ops.pipeline_runs(run_id,status) VALUES (?, 'running')", [run_id])
        stage, processed = 'discovery', 0
        print(f'Pipeline run {run_id}')
        try:
            files = discover(raw_directory)
            execute(database, 'UPDATE ops.pipeline_runs SET raw_files_discovered=? WHERE run_id=?', [len(files), run_id])
            known = dict(execute(database, 'SELECT file_path,file_hash FROM ops.processed_files'))
            pending = [p for p in files if force or known.get(file_key(p)) != fingerprint(p)]
            print(f'Files discovered={len(files)} skipped={len(files)-len(pending)} pending={len(pending)}')
            if not pending:
                print('No new raw extractions found.')
            stage = 'ingestion'
            for path in pending:
                started = time.monotonic()
                # Load an immutable private snapshot, so recorded hash matches loaded bytes.
                with tempfile.TemporaryDirectory() as temporary:
                    snapshot = Path(temporary) / 'works.jsonl'
                    shutil.copyfile(path, snapshot)
                    digest = fingerprint(snapshot)
                    records = sum(1 for _ in read_jsonl(snapshot))
                    if records:
                        execute(database, 'UPDATE ops.pipeline_state SET downstream_pending=true, visualizations_pending=true WHERE id=1')
                        load_file(snapshot, database)
                    execute(database, """INSERT INTO ops.processed_files VALUES (?, ?, ?, current_timestamp, ?, ?)
                        ON CONFLICT(file_path) DO UPDATE SET file_hash=excluded.file_hash,
                        file_size=excluded.file_size, processed_at=excluded.processed_at,
                        records_loaded=excluded.records_loaded, run_id=excluded.run_id""",
                        [file_key(path), digest, snapshot.stat().st_size, records, run_id])
                processed += 1
                execute(database, 'UPDATE ops.pipeline_runs SET raw_files_processed=? WHERE run_id=?', [processed, run_id])
                print(f'ingestion: file {processed}/{len(pending)}, records={records}, seconds={time.monotonic()-started:.2f}')
            dirty, figures_dirty = execute(database, 'SELECT downstream_pending,visualizations_pending FROM ops.pipeline_state WHERE id=1')[0]
            if dirty or rebuild_downstream:
                execute(database, 'UPDATE ops.pipeline_state SET downstream_pending=true, visualizations_pending=true WHERE id=1')
                for stage, build in [('curated', build_curated), ('analytics', build_analytics)]:
                    started = time.monotonic()
                    print(f'Stage: {stage}')
                    build(database)
                    print(f'{stage}: seconds={time.monotonic()-started:.2f}')
                execute(database, 'UPDATE ops.pipeline_state SET downstream_pending=false WHERE id=1')
                figures_dirty = True
            if figures_dirty and not skip_visualizations:
                stage = 'visualization'
                started = time.monotonic()
                generate_visualizations(database, output_dir)
                execute(database, 'UPDATE ops.pipeline_state SET visualizations_pending=false WHERE id=1')
                print(f'visualization: seconds={time.monotonic()-started:.2f}')
            stage = 'completion'
            execute(database, "UPDATE ops.pipeline_runs SET status='success', finished_at=current_timestamp WHERE run_id=?", [run_id])
            print(f'Final status: success; files processed={processed}')
            return run_id
        except BaseException as error:
            # Never persist arbitrary exception strings: they may contain records/URLs.
            reason = 'Interrupted' if isinstance(error, KeyboardInterrupt) else f'{type(error).__name__}: stage failed; check input and warehouse access'
            execute(database, "UPDATE ops.pipeline_runs SET status='failed',finished_at=current_timestamp,error_stage=?,error_message=? WHERE run_id=?", [stage, reason, run_id])
            print(f'Final status: failed; stage={stage}; {reason}')
            raise
