"""Fingerprint completed extractions and coordinate the existing stages."""
from contextlib import contextmanager
import logging
import os
from pathlib import Path
import shutil
import tempfile
import time
import uuid

import duckdb

from src.load.openalex_dlt import DEFAULT_DATABASE, RAW_DIRECTORY, load_file
from src.transform.curated import build_curated
from src.transform.analytics import build_analytics
from src.visualization.generate import DEFAULT_OUTPUT, generate_visualizations
from src.quality.checks import raw_checks
from src.quality.runner import persist, run_quality, enforce
from src.quality.models import QualityError, Result, Status

LOGGER = logging.getLogger('research_pipeline')


def quality_gate(database, layer, run_id):
    _, results = run_quality(database, (layer,), run_id)
    enforce(results)

from src.config import PathLike, resolve_path


from src.load.files import fingerprint as fingerprint, file_key as file_key, discover as discover


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


def run_pipeline(database: PathLike = DEFAULT_DATABASE, raw_directory: PathLike = RAW_DIRECTORY, *, force: bool = False,
                 rebuild_downstream: bool = False, skip_visualizations: bool = False, output_dir: PathLike = DEFAULT_OUTPUT) -> str:
    database = resolve_path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    with run_lock(database):
        initialize(database)
        run_id = str(uuid.uuid4())
        execute(database, "INSERT INTO ops.pipeline_runs(run_id,status) VALUES (?, 'running')", [run_id])
        stage, processed = 'discovery', 0
        run_started = time.monotonic()
        started = run_started
        LOGGER.info('run_id=%s stage=start', run_id)
        try:
            files = discover(raw_directory)
            execute(database, 'UPDATE ops.pipeline_runs SET raw_files_discovered=? WHERE run_id=?', [len(files), run_id])
            known = dict(execute(database, 'SELECT file_path,file_hash FROM ops.processed_files'))
            pending = [p for p in files if force or known.get(file_key(p)) != fingerprint(p)]
            LOGGER.info('run_id=%s stage=discovery discovered=%s skipped=%s pending=%s', run_id,len(files),len(files)-len(pending),len(pending))
            if not pending:
                LOGGER.info('run_id=%s No new raw extractions found.', run_id)
            stage = 'ingestion'
            for path in pending:
                started = time.monotonic()
                # Load an immutable private snapshot, so recorded hash matches loaded bytes.
                with tempfile.TemporaryDirectory() as temporary:
                    snapshot = Path(temporary) / 'works.jsonl'
                    shutil.copyfile(path, snapshot)
                    digest = fingerprint(snapshot)
                    quality_results, records = raw_checks(snapshot, path.with_suffix('.metadata.json'))
                    persist(database, quality_results, run_id)
                    enforce(quality_results)
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
                LOGGER.info('run_id=%s stage=ingestion file_hash=%s file_index=%s records=%s duration=%.2f', run_id,digest,processed,records,time.monotonic()-started)
            dirty, figures_dirty = execute(database, 'SELECT downstream_pending,visualizations_pending FROM ops.pipeline_state WHERE id=1')[0]
            if dirty or rebuild_downstream:
                execute(database, 'UPDATE ops.pipeline_state SET downstream_pending=true, visualizations_pending=true WHERE id=1')
                for stage, build in [('curated', build_curated),
                                     ('quality_curated', lambda db: quality_gate(db, 'curated', run_id)),
                                     ('analytics', build_analytics),
                                     ('quality_analytics', lambda db: quality_gate(db, 'analytics', run_id))]:
                    started = time.monotonic()
                    LOGGER.info('run_id=%s stage=%s started', run_id,stage)
                    build(database)
                    LOGGER.info('run_id=%s stage=%s duration=%.2f', run_id,stage,time.monotonic()-started)
                execute(database, 'UPDATE ops.pipeline_state SET downstream_pending=false WHERE id=1')
                figures_dirty = True
            if figures_dirty and not skip_visualizations:
                stage = 'visualization'
                started = time.monotonic()
                generate_visualizations(database, output_dir)
                execute(database, 'UPDATE ops.pipeline_state SET visualizations_pending=false WHERE id=1')
                LOGGER.info('run_id=%s stage=visualization duration=%.2f', run_id,time.monotonic()-started)
            stage = 'completion'
            execute(database, "UPDATE ops.pipeline_runs SET status='success', finished_at=current_timestamp WHERE run_id=?", [run_id])
            LOGGER.info('run_id=%s status=success files_processed=%s', run_id,processed)
            return run_id
        except BaseException as error:
            if not isinstance(error, QualityError) and stage in ('curated', 'analytics'):
                results = getattr(error, 'quality_results', [Result(f'{stage}.build',stage,Status.FAIL,
                    'failed','successful transactional build','Builder rejected input or model; previous committed layer preserved')])
                persist(database, results, run_id)
            # Never persist arbitrary exception strings: they may contain records/URLs.
            reason = 'Interrupted' if isinstance(error, KeyboardInterrupt) else f'{type(error).__name__}: stage failed; check input and warehouse access'
            execute(database, "UPDATE ops.pipeline_runs SET status='failed',finished_at=current_timestamp,error_stage=?,error_message=? WHERE run_id=?", [stage, reason, run_id])
            LOGGER.error('run_id=%s status=failed stage=%s duration=%.2f reason=%s', run_id,stage,time.monotonic()-started,reason)
            raise
        finally:
            LOGGER.info('run_id=%s stage=total duration=%.2f', run_id,time.monotonic()-run_started)
