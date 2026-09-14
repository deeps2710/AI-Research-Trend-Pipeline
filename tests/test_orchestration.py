"""Incremental state and failure recovery on disposable local warehouses."""
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb
from src.orchestration import pipeline as p
from scripts.run_pipeline import main
from scripts.pipeline_status import main as status_main


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / 'warehouse.duckdb'
        self.raw = self.root / 'raw'
        self.raw.mkdir()
        self.path = self.raw / 'a.jsonl'
        self.write(2)

    def write(self, citations):
        self.path.write_text(json.dumps({'id': 'https://openalex.org/W1', 'title': 'Example',
            'publication_year': 2025, 'cited_by_count': citations,
            'open_access': {'is_oa': True, 'oa_status': 'gold'}}) + '\n', encoding='utf-8')
        self.path.with_suffix('.metadata.json').write_text('{}', encoding='utf-8')

    def run_pipe(self, **kwargs):
        with redirect_stdout(io.StringIO()):
            return p.run_pipeline(self.database, self.raw, skip_visualizations=True, **kwargs)

    def query(self, sql):
        with duckdb.connect(str(self.database), read_only=True) as con:
            return con.execute(sql).fetchall()

    def test_fingerprint_discovery(self):
        self.assertEqual(p.fingerprint(self.path), hashlib.sha256(self.path.read_bytes()).hexdigest())
        for name in ('bad.json', 'b.jsonl.inprogress', 'unfinished.jsonl'):
            (self.raw / name).write_text('{}')
        self.assertEqual(p.discover(self.raw), [self.path.resolve()])
        old = p.fingerprint(self.path)
        self.write(5)
        self.assertNotEqual(old, p.fingerprint(self.path))

    def test_real_first_skip_force_changed_and_rebuild(self):
        first = self.run_pipe()
        self.assertEqual(self.query('SELECT records_loaded FROM ops.processed_files'), [(1,)])
        with patch.object(p, 'load_file') as loader, patch.object(p, 'build_curated') as curated:
            second = self.run_pipe()
            loader.assert_not_called()
            curated.assert_not_called()
        self.assertNotEqual(first, second)
        self.run_pipe(force=True)
        self.assertEqual(self.query('SELECT count(*) FROM openalex_data.works'), [(1,)])
        self.write(9)
        self.run_pipe()
        self.assertEqual(self.query('SELECT count(*),max(cited_by_count) FROM openalex_data.works'), [(1, 9)])
        self.assertEqual(self.query('SELECT total_papers,total_citations FROM analytics.overview_kpis'), [(1, 9)])
        with patch.object(p, 'load_file') as loader:
            self.run_pipe(rebuild_downstream=True)
            loader.assert_not_called()
        self.assertEqual(self.query("SELECT status,raw_files_processed FROM ops.pipeline_runs ORDER BY started_at"),
                         [('success',1),('success',0),('success',1),('success',1),('success',0)])
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(status_main(['--database', str(self.database), '--raw-directory', str(self.raw)]), 0)
        self.assertIn('Pending raw files: 0', output.getvalue())

    def test_malformed_fails_and_corrected_run_succeeds(self):
        self.path.write_text('{bad secret-placeholder')
        with patch.object(p, 'build_curated') as curated, self.assertRaises(ValueError):
            self.run_pipe()
        curated.assert_not_called()
        self.assertEqual(self.query('SELECT count(*) FROM ops.processed_files'), [(0,)])
        self.assertEqual(self.query('SELECT status,error_stage FROM ops.pipeline_runs'), [('failed','ingestion')])
        self.assertNotIn('secret-placeholder', str(self.query('SELECT error_message FROM ops.pipeline_runs')))
        self.write(4)
        self.run_pipe()
        self.assertEqual(self.query('SELECT total_papers FROM analytics.overview_kpis'), [(1,)])

    def test_loader_failure_not_marked_and_cli_nonzero(self):
        with patch.object(p, 'load_file', side_effect=RuntimeError('private-data')), \
                patch.object(p, 'build_curated') as curated, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--database',str(self.database),'--raw-directory',str(self.raw)]), 1)
        curated.assert_not_called()
        self.assertEqual(self.query('SELECT count(*) FROM ops.processed_files'), [(0,)])
        self.assertEqual(self.query('SELECT status,error_stage FROM ops.pipeline_runs'), [('failed','ingestion')])

    def test_downstream_failure_recovery_without_reloading(self):
        with patch.object(p, 'build_curated', side_effect=RuntimeError('failed')), patch.object(p, 'build_analytics') as analytics:
            with self.assertRaises(RuntimeError):
                self.run_pipe()
            analytics.assert_not_called()
        self.assertEqual(self.query('SELECT status,error_stage FROM ops.pipeline_runs'), [('failed','curated')])
        self.assertEqual(self.query('SELECT count(*) FROM ops.processed_files'), [(1,)])
        with patch.object(p, 'load_file') as loader:
            self.run_pipe()
            loader.assert_not_called()
        self.assertEqual(self.query('SELECT downstream_pending FROM ops.pipeline_state'), [(False,)])

    def test_analytics_and_visualization_fail_fast_and_retry(self):
        with patch.object(p, 'build_analytics', side_effect=RuntimeError()), patch.object(p, 'generate_visualizations') as figures:
            with self.assertRaises(RuntimeError):
                self.run_pipe()
            figures.assert_not_called()
        self.assertEqual(self.query('SELECT error_stage FROM ops.pipeline_runs'), [('analytics',)])
        self.run_pipe()
        with patch.object(p, 'generate_visualizations', side_effect=RuntimeError()), redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                p.run_pipeline(self.database,self.raw)
        self.assertEqual(self.query('SELECT visualizations_pending FROM ops.pipeline_state'), [(True,)])
        with patch.object(p, 'generate_visualizations') as figures, patch.object(p, 'load_file') as loader, redirect_stdout(io.StringIO()):
            p.run_pipeline(self.database,self.raw)
            figures.assert_called_once()
            loader.assert_not_called()
        self.assertEqual(self.query('SELECT visualizations_pending FROM ops.pipeline_state'), [(False,)])

    def test_empty_file_and_interrupted_run(self):
        self.path.write_text('')
        self.run_pipe()
        self.assertEqual(self.query('SELECT records_loaded FROM ops.processed_files'), [(0,)])
        p.execute(self.database,"INSERT INTO ops.pipeline_runs(run_id,status) VALUES ('interrupted','running')")
        self.run_pipe()
        self.assertEqual(self.query("SELECT status,error_stage FROM ops.pipeline_runs WHERE run_id='interrupted'"), [('failed','interrupted')])

    def test_partial_batch_preserves_success_and_retries_rest(self):
        bad = self.raw / 'b.jsonl'
        bad.write_text('invalid')
        bad.with_suffix('.metadata.json').write_text('{}')
        with self.assertRaises(ValueError):
            self.run_pipe()
        self.assertEqual(self.query('SELECT raw_files_processed,status FROM ops.pipeline_runs'), [(1,'failed')])
        self.assertEqual(self.query('SELECT count(*) FROM ops.processed_files'), [(1,)])
        bad.write_text('{"id":"https://openalex.org/W2","publication_year":2025}')
        with patch.object(p, 'load_file', wraps=p.load_file) as loader:
            self.run_pipe()
            self.assertEqual(loader.call_count, 1)
        self.assertEqual(self.query('SELECT total_papers FROM analytics.overview_kpis'), [(2,)])

    def test_lock_rejects_overlap_and_releases(self):
        with p.run_lock(self.database):
            with self.assertRaises(RuntimeError):
                with p.run_lock(self.database):
                    pass
        with p.run_lock(self.database):
            pass
