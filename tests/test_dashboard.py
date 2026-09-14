"""Dashboard query and actual Streamlit rerun tests using a tiny local warehouse."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb
import pandas as pd
from matplotlib.figure import Figure
from streamlit.testing.v1 import AppTest

from dashboard import data_access as data
from src.visualization.charts import plot_publication_trends


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.duckdb"
        with duckdb.connect(str(self.path)) as con:
            con.execute("CREATE SCHEMA analytics; CREATE SCHEMA curated")
            con.execute("""CREATE TABLE analytics.top_papers AS SELECT * FROM (VALUES
                ('p1','Alpha',2025,20,'Topic A',true,'gold','https://doi.org/10.1/a'),
                ('p2','Beta',2024,5,'Topic B',false,'closed',NULL),
                ('p3','Gamma',2025,NULL,NULL,NULL,NULL,NULL)
                ) t(paper_id,title,publication_year,cited_by_count,primary_topic_name,is_open_access,oa_status,doi)""")
            con.execute("CREATE TABLE curated.paper_topics AS SELECT * FROM (VALUES ('p1','t1'),('p1','t1'),('p2','t2')) t(paper_id,topic_id)")
            con.execute("""CREATE VIEW analytics.overview_kpis AS SELECT count(*) total_papers,
                sum(cited_by_count) total_citations, min(publication_year) earliest_publication_year,
                max(publication_year) latest_publication_year FROM analytics.top_papers""")
            con.execute("""CREATE VIEW analytics.publication_trends AS SELECT publication_year,
                count(*) paper_count, NULL::DOUBLE year_over_year_growth_percentage
                FROM analytics.top_papers GROUP BY 1""")
            con.execute("CREATE TABLE analytics.topic_summary AS SELECT * FROM (VALUES ('t1','Topic A',1),('t2','Topic B',1)) t(topic_id,topic_name,paper_count)")
            con.execute("CREATE VIEW analytics.topic_yearly_trends AS SELECT 2025 publication_year,* FROM analytics.topic_summary")
            con.execute("CREATE VIEW analytics.open_access_summary AS SELECT coalesce(oa_status,'unknown') oa_status,count(*) paper_count FROM analytics.top_papers GROUP BY 1")

    def tearDown(self):
        data._cached_read.clear()
        self.temp.cleanup()

    def test_filters_limits_and_no_fanout(self):
        self.assertEqual(data.get_overview_kpis(self.path)['total_papers'], 3)
        self.assertEqual(len(data.get_papers(self.path, year=2025)), 2)
        self.assertEqual(data.get_papers(self.path, topic_id='t1').paper_id.tolist(), ['p1'])
        self.assertEqual(data.get_papers(self.path, min_citations=10).paper_id.tolist(), ['p1'])
        self.assertEqual(data.get_papers(self.path, oa_status='unknown').paper_id.tolist(), ['p3'])
        self.assertEqual(data.get_papers(self.path, sort='title', limit=1).paper_id.tolist(), ['p1'])
        self.assertTrue(data.get_papers(self.path, year=1990).empty)
        self.assertEqual(len(data.get_view(self.path, 'topic_summary', limit=1)), 1)

    def test_untrusted_filters_and_identifiers(self):
        self.assertTrue(data.get_papers(self.path, topic_id="t1' OR 1=1 --").empty)
        self.assertTrue(data.get_papers(self.path, oa_status="gold' OR 1=1 --").empty)
        for kwargs in ({'sort': 'title; DROP SCHEMA analytics CASCADE'}, {'limit': 201}):
            with self.assertRaises(ValueError):
                data.get_papers(self.path, **kwargs)
        with self.assertRaises(ValueError):
            data.get_view(self.path, 'top_papers; DROP SCHEMA analytics')
        self.assertEqual(len(data.get_papers(self.path)), 3)

    def test_missing_and_empty_database(self):
        missing = self.path.parent / 'missing.duckdb'
        with self.assertRaises(data.DashboardError):
            data.validate_database(missing)
        self.assertFalse(missing.exists())
        with duckdb.connect(str(missing)):
            pass
        with self.assertRaises(data.DashboardError):
            data.validate_database(missing)
        self.assertTrue(data.get_view(self.path, 'author_summary').empty)
        with duckdb.connect(str(self.path)) as con:
            con.execute('DELETE FROM analytics.top_papers')
        data._cached_read.clear()
        self.assertTrue(data.get_papers(self.path).empty)

    def test_in_memory_figure(self):
        frame = pd.DataFrame({'publication_year': [2025], 'paper_count': [3]})
        figure = plot_publication_trends(frame, None)
        self.assertIsInstance(figure, Figure)
        figure.clear()

    def test_all_pages_and_filter_reruns(self):
        with patch.dict(os.environ, {'RESEARCH_WAREHOUSE_PATH': str(self.path)}):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'dashboard/app.py'), default_timeout=30).run()
            self.assertFalse(app.exception)
            self.assertTrue(any(metric.value == '3' for metric in app.metric))
            for page in ('Research Trends', 'Topic Intelligence', 'Authors & Institutions', 'Paper Explorer'):
                app.sidebar.radio[0].set_value(page).run()
                self.assertFalse(app.exception, page)
            app.number_input[0].set_value(100).run()
            self.assertFalse(app.exception)
            self.assertTrue(any('No records' in item.value for item in app.info))
            app.number_input[0].set_value(0).run()
            self.assertEqual(len(app.dataframe[0].value), 3)

    def test_missing_database_ui(self):
        with patch.dict(os.environ, {'RESEARCH_WAREHOUSE_PATH': str(self.path.parent / 'absent.duckdb')}):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'dashboard/app.py'), default_timeout=30).run()
            self.assertFalse(app.exception)
            self.assertIn('Warehouse not found', app.error[0].value)
