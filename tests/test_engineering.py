"""Configuration, CLI compatibility and bounded projection regression checks."""
from contextlib import redirect_stdout
import hashlib
import importlib
import io
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb
from src.config import PROJECT_ROOT, DEFAULT_DATABASE, RAW_DIRECTORY, DEFAULT_OUTPUT, LOG_DIRECTORY, resolve_path
from src.benchmark import benchmark
from dashboard import data_access


class EngineeringTests(unittest.TestCase):
    def test_logging_setup_does_not_duplicate_handlers(self):
        from src.logging_config import configure_logging
        logger = logging.getLogger('research_pipeline')
        original_handlers = logger.handlers[:]
        extraction = logging.getLogger('src.extract.openalex_client')
        extraction_state = (extraction.handlers[:], extraction.level, extraction.disabled, extraction.propagate)
        logger.handlers = []
        try:
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary)/'pipeline.log'
                try:
                    # dlt/host logging configuration may disable existing loggers.
                    logging.getLogger('src.extract.openalex_client').disabled = True
                    configure_logging(path)
                    configure_logging(path)
                    self.assertEqual(len(logger.handlers),2)
                    logging.getLogger('src.extract.openalex_client').warning('single retry marker')
                    for handler in logger.handlers:
                        handler.flush()
                    self.assertEqual(path.read_text().count('single retry marker'),1)
                finally:
                    for handler in logger.handlers:
                        handler.close()
        finally:
            logger.handlers = original_handlers
            extraction.handlers, extraction.level, extraction.disabled, extraction.propagate = extraction_state

    def test_defaults_from_unicode_working_directory(self):
        original = Path.cwd()
        with tempfile.TemporaryDirectory(prefix='research space 研究 ') as temporary:
            try:
                os.chdir(temporary)
                from src.load.openalex_dlt import DEFAULT_DATABASE as load_default
                from src.transform.curated import DEFAULT_DATABASE as curated_default
                from scripts.extract_openalex import parse_args
                from dashboard.config import database_path
                self.assertEqual(load_default,DEFAULT_DATABASE)
                self.assertEqual(curated_default,DEFAULT_DATABASE)
                self.assertEqual(parse_args([]).output_dir,RAW_DIRECTORY)
                with patch.dict(os.environ,{},clear=True):
                    self.assertEqual(database_path(),DEFAULT_DATABASE)
                with patch.dict(os.environ,{'RESEARCH_WAREHOUSE_PATH':'warehouse 研究.duckdb'}):
                    self.assertEqual(database_path(),Path(temporary)/'warehouse 研究.duckdb')
                self.assertEqual(resolve_path('file with spaces'),Path(temporary)/'file with spaces')
                for path in (DEFAULT_DATABASE,RAW_DIRECTORY,DEFAULT_OUTPUT,LOG_DIRECTORY):
                    self.assertTrue(path.is_relative_to(PROJECT_ROOT))
                    self.assertTrue(path.is_absolute())
            finally:
                os.chdir(original)

    def test_database_aliases_and_exploration_help(self):
        from scripts.explore_openalex import main as explore
        with patch('scripts.explore_openalex.OpenAlexClient') as client, redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                explore(['--help'])
            self.assertEqual(result.exception.code,0)
            client.assert_not_called()
        for name in ('build_curated','build_analytics','check_data_quality','inspect_analytics',
                     'inspect_curated','inspect_warehouse','load_openalex','run_pipeline','pipeline_status',
                     'generate_visualizations','benchmark_pipeline'):
            module = importlib.import_module('scripts.'+name)
            with redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(SystemExit):
                    module.main(['--help'])
            self.assertIn('--db-path',output.getvalue())
            self.assertIn('--database',output.getvalue())
        with patch('scripts.build_curated.build_curated',return_value={}) as build, redirect_stdout(io.StringIO()):
            module = importlib.import_module('scripts.build_curated')
            for flag in ('--db-path','--database'):
                self.assertEqual(module.main([flag,'warehouse space.duckdb']),0)
                self.assertEqual(build.call_args.args[0],Path('warehouse space.duckdb'))

    def test_view_projection_excludes_internal_columns_and_orders_ties(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary)/'test.duckdb'
            with duckdb.connect(str(database)) as con:
                con.execute("CREATE SCHEMA analytics; CREATE TABLE analytics.topic_summary AS SELECT * FROM (VALUES ('T2',1,'hidden'),('T1',1,'hidden')) t(topic_id,paper_count,_dlt_id)")
            frame = data_access.get_view(database,'topic_summary')
            self.assertEqual(frame.topic_id.tolist(),['T1','T2'])
            self.assertNotIn('_dlt_id',frame.columns)
            with self.assertRaises(ValueError):
                data_access.get_view(database,'topic_summary',limit=True)
            data_access._cached_read.clear()

    def test_benchmark_uses_private_copy(self):
        with tempfile.TemporaryDirectory(prefix='benchmark 研究 ') as temporary:
            source = Path(temporary)/'source.duckdb'
            with duckdb.connect(str(source)) as con:
                con.execute("CREATE SCHEMA openalex_data; CREATE TABLE openalex_data.works AS SELECT 'W1' id,'r1' _dlt_id,2025 publication_year,1 cited_by_count")
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            with redirect_stdout(io.StringIO()):
                timings = benchmark(source)
            self.assertTrue({'curated','analytics','quality','query.papers'} <= timings.keys())
            self.assertTrue(all(value>=0 for value in timings.values()))
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)
            with duckdb.connect(str(source),read_only=True) as con:
                self.assertEqual(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='curated'").fetchone()[0],0)
