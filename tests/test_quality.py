"""Unit, integration and end-to-end quality checks; no live API calls."""
from contextlib import redirect_stdout
from collections import Counter
import io
import json
import logging
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import duckdb
from src.load.openalex_dlt import load_file
from src.transform.curated import build_curated
from src.transform.analytics import build_analytics
from src.quality.checks import raw_checks
from src.quality.models import Result, Status, QualityError
from src.quality.runner import enforce, run_quality
from src.orchestration import pipeline
from src.logging_config import configure_logging
from scripts.check_data_quality import main as quality_main
from scripts.pipeline_status import main as status_main

WORKS = [
    {'id':'W1','title':'One','doi':'https://doi.org/10.1/one','publication_year':2024,'cited_by_count':10,
     'primary_topic':{'id':'T1'},'topics':[{'id':'T1'},{'id':'T2'}],
     'authorships':[{'author':{'id':'A1'},'institutions':[{'id':'I1'}]},
                    {'author':{'id':'A2'},'institutions':[{'id':'I1'}]}],
     'open_access':{'is_oa':True,'oa_status':'gold'}},
    {'id':'W2','title':'Two','publication_year':2025,'cited_by_count':0,
     'primary_topic':{'id':'T1'},'topics':[{'id':'T1'}],
     'authorships':[{'author':{'id':'A1'},'institutions':[]}],
     'open_access':{'is_oa':False,'oa_status':'closed'}},
    {'id':'W3','publication_year':2025},
]


class QualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.base_temp.name)/'base.duckdb'
        raw = Path(cls.base_temp.name)/'works.jsonl'
        raw.write_text('\n'.join(json.dumps(w) for w in WORKS))
        load_file(raw,cls.base)
        build_curated(cls.base)
        build_analytics(cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.base_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root/'test.duckdb'
        shutil.copyfile(self.base,self.db)

    def sql(self, query):
        with duckdb.connect(str(self.db)) as con:
            return con.execute(query).fetchall()

    def test_status_and_optional_coverage_and_persistence(self):
        execution, results = run_quality(self.db)
        enforce(results)
        coverage = {r.check_name:r.observed_value for r in results if r.layer=='coverage'}
        self.assertEqual(coverage['coverage.doi'],'33.33')
        self.assertEqual(coverage['coverage.authors'],'66.67')
        self.assertEqual(coverage['coverage.institutions'],'33.33')
        self.assertEqual(coverage['coverage.oa_information'],'66.67')
        self.assertEqual(coverage['coverage.primary_topic'],'66.67')
        self.assertEqual(self.sql('SELECT count(*) FROM ops.data_quality_results')[0][0],len(results))
        self.assertEqual(self.sql('SELECT DISTINCT execution_id FROM ops.data_quality_results'),[(execution,)])
        self.assertNotIn(Status.FAIL,Counter(r.status for r in results))
        with self.assertRaises(QualityError):
            enforce([Result('bad','raw',Status.FAIL,'1','0')])
        enforce([Result('sparse','coverage',Status.WARN,'0','informational')])

    def test_duplicate_orphan_negative_and_null_key_fail(self):
        self.sql('INSERT INTO curated.papers SELECT * FROM curated.papers WHERE paper_id=\'W1\'')
        self.sql("INSERT INTO curated.paper_topics(paper_id,topic_id) VALUES ('missing','T1')")
        self.sql("UPDATE curated.papers SET cited_by_count=-1 WHERE paper_id='W2'")
        self.sql("UPDATE curated.papers SET paper_id=NULL WHERE paper_id='W3'")
        _, results = run_quality(self.db,('curated',))
        failed = {r.check_name for r in results if r.status == Status.FAIL}
        self.assertTrue({'papers.unique','paper_topics.papers.references','papers.cited_by_count.range','papers.identity'} <= failed)
        self.assertGreater(self.sql("SELECT count(*) FROM ops.data_quality_results WHERE status='FAIL'")[0][0],0)

    def test_analytics_metrics_and_grain_fail(self):
        self.sql('CREATE OR REPLACE VIEW analytics.overview_kpis AS SELECT 999 total_papers,-1 total_citations,150 open_access_percentage')
        self.sql("CREATE OR REPLACE VIEW analytics.author_summary AS SELECT 'A1' author_id,999 paper_count")
        _, results = run_quality(self.db,('analytics',))
        failed = {r.check_name for r in results if r.status==Status.FAIL}
        self.assertIn('analytics.reconciliation',failed)
        self.assertIn('overview_kpis.total_citations.nonnegative',failed)

    def test_one_year_warn_and_cli_status(self):
        self.sql('UPDATE curated.papers SET publication_year=2025')
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(quality_main(['--database',str(self.db)]),0)
            self.assertEqual(status_main(['--database',str(self.db),'--raw-directory',str(self.root)]),0)
        self.assertIn('WARN coverage.publication_years',out.getvalue())
        self.assertIn('Latest quality: WARN',out.getvalue())
        self.assertIn('freshness unavailable',out.getvalue())

    def test_raw_contract_metadata_and_malformed(self):
        raw = self.root/'works.jsonl'; meta = self.root/'works.metadata.json'
        for content, metadata, check in [('',{},'raw.nonempty'), ('{invalid',{},'raw.identity_json'),
                ('{}',{},'raw.identity_json'), ('{"id":"W1"}',{'actual_record_count':2},'raw.actual_record_count'),
                ('{"id":"W1"}',{'is_complete_extraction':True},'raw.completeness')]:
            raw.write_text(content); meta.write_text(json.dumps(metadata))
            results,_ = raw_checks(raw,meta)
            self.assertIn(check,{r.check_name for r in results if r.status==Status.FAIL})
        meta.write_text('{}')
        enforce(raw_checks(raw,meta)[0])

    def test_gate_blocks_and_persists_before_downstream(self):
        raw = self.root/'raw'; raw.mkdir()
        def corrupt(db):
            self.sql("UPDATE curated.papers SET cited_by_count=-1 WHERE paper_id='W1'")
        with patch.object(pipeline,'build_curated',side_effect=corrupt), \
                patch.object(pipeline,'build_analytics') as analytics, patch.object(pipeline,'generate_visualizations') as figures:
            with self.assertRaises(QualityError):
                pipeline.run_pipeline(self.db,raw,rebuild_downstream=True)
            analytics.assert_not_called(); figures.assert_not_called()
        self.assertEqual(self.sql('SELECT status,error_stage FROM ops.pipeline_runs'),[('failed','quality_curated')])
        self.assertGreater(self.sql("SELECT count(*) FROM ops.data_quality_results WHERE status='FAIL' AND run_id IS NOT NULL")[0][0],0)
        with redirect_stdout(io.StringIO()) as out:
            status_main(['--database',str(self.db),'--raw-directory',str(raw)])
        self.assertIn('Latest quality: FAIL',out.getvalue())

    def test_raw_gate_failure_persisted(self):
        raw = self.root/'raw'; raw.mkdir()
        (raw/'works.jsonl').write_text('{"id":"W1"}')
        (raw/'works.metadata.json').write_text('{"records_extracted":9}')
        with patch.object(pipeline,'load_file') as load, patch.object(pipeline,'build_curated') as curated:
            with self.assertRaises(QualityError):
                pipeline.run_pipeline(self.db,raw)
            load.assert_not_called(); curated.assert_not_called()
        self.assertEqual(self.sql('SELECT count(*) FROM ops.processed_files'),[(0,)])
        self.assertEqual(self.sql("SELECT status FROM ops.data_quality_results WHERE check_name='raw.records_extracted'"),[('FAIL',)])

    def test_end_to_end_smoke(self):
        db = self.root/'smoke.duckdb'; raw = self.root/'raw'; raw.mkdir()
        (raw/'works.jsonl').write_text('\n'.join(json.dumps(w) for w in WORKS))
        (raw/'works.metadata.json').write_text('{"records_extracted":3,"source_match_count":100,"is_complete_extraction":false}')
        pipeline.run_pipeline(db,raw,skip_visualizations=True)
        with duckdb.connect(str(db),read_only=True) as con:
            self.assertEqual(con.execute('SELECT total_papers,total_citations FROM analytics.overview_kpis').fetchone(),(3,10))
            self.assertEqual(con.execute('SELECT count(*) FROM curated.paper_authors').fetchone(),(3,))
            self.assertEqual(con.execute('SELECT count(*) FROM curated.paper_topics').fetchone(),(3,))
            self.assertEqual(con.execute('SELECT count(*) FROM curated.paper_institutions').fetchone(),(1,))
            self.assertEqual(con.execute("SELECT count(*) FROM ops.data_quality_results WHERE status='FAIL'").fetchone(),(0,))
            self.assertEqual(con.execute('SELECT status FROM ops.pipeline_runs').fetchone(),('success',))

    def test_logging_redaction_and_file(self):
        logger = logging.getLogger('research_pipeline')
        old_handlers = logger.handlers[:]
        logger.handlers = []
        try:
            log_path = self.root/'logs'/'test.log'
            configure_logging(log_path)
            with patch.dict('os.environ',{'OPENALEX_API_KEY':'fake-sensitive-key'}):
                logger.warning('run_id=test stage=quality api_key=another-secret fake-sensitive-key')
            for handler in logger.handlers:
                handler.flush()
            text = log_path.read_text()
            self.assertIn('WARNING run_id=test stage=quality',text)
            self.assertNotIn('another-secret',text)
            self.assertNotIn('fake-sensitive-key',text)
        finally:
            for handler in logger.handlers:
                handler.close()
            logger.handlers = old_handlers

    def test_missing_database_not_created(self):
        missing = self.root/'absent.duckdb'
        with self.assertRaises(FileNotFoundError):
            run_quality(missing)
        self.assertFalse(missing.exists())

    def test_missing_schema_persists_failures(self):
        db = self.root/'empty.duckdb'
        with duckdb.connect(str(db)):
            pass
        _, results = run_quality(db)
        self.assertTrue(any(r.status==Status.FAIL for r in results))
        with duckdb.connect(str(db),read_only=True) as con:
            self.assertGreater(con.execute('SELECT count(*) FROM ops.data_quality_results').fetchone()[0],0)

    def test_builder_rollback_still_persists_negative_citations(self):
        raw = self.root/'raw'; raw.mkdir()
        (raw/'bad.jsonl').write_text('{"id":"W1","cited_by_count":-7}')
        (raw/'bad.metadata.json').write_text('{}')
        with patch.object(pipeline,'build_analytics') as analytics:
            with self.assertRaises(ValueError):
                pipeline.run_pipeline(self.db,raw,skip_visualizations=True)
            analytics.assert_not_called()
        self.assertEqual(self.sql("SELECT status FROM ops.data_quality_results WHERE check_name='papers.cited_by_count.range'"),[('FAIL',)])
        self.assertEqual(self.sql("SELECT cited_by_count FROM curated.papers WHERE paper_id='W1'"),[(10,)])
