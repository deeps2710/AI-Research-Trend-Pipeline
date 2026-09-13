"""Analytical SQL checks on a small, known curated fixture."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

import duckdb

from src.transform.analytics import AnalyticsError, VIEW_NAMES, build_analytics, validate_analytics


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "fixture.duckdb"
        with duckdb.connect(str(self.path)) as c:
            c.execute("CREATE SCHEMA curated")
            c.execute("CREATE TABLE curated.papers(paper_id VARCHAR, title VARCHAR, "
                      "publication_year BIGINT, cited_by_count BIGINT, is_open_access BOOLEAN, oa_status VARCHAR)")
            c.execute("INSERT INTO curated.papers VALUES "
                      "('P1','First',2022,10,true,'gold'),('P2','Second',2023,20,false,'closed'),"
                      "('P3','Third',2023,20,NULL,NULL),('P4','Fourth',2025,0,true,'green'),"
                      "('P5','Unknown',NULL,NULL,NULL,NULL)")
            for table, key, label in (("topics", "topic_id", "topic_name"),
                                      ("authors", "author_id", "author_name"),
                                      ("institutions", "institution_id", "institution_name")):
                c.execute(f"CREATE TABLE curated.{table}({key} VARCHAR, {label} VARCHAR)")
                prefix = table[0].upper()
                c.execute(f"INSERT INTO curated.{table} VALUES ('{prefix}1','One'),('{prefix}2','Two')")
            for table, key, values in (
                ("paper_topics", "topic_id", "('P1','T1'),('P2','T1'),('P4','T1'),('P1','T2'),('P3','T2')"),
                ("paper_authors", "author_id", "('P1','A1'),('P1','A2'),('P2','A1')"),
                ("paper_institutions", "institution_id", "('P1','I1'),('P1','I2'),('P2','I1')"),
            ):
                c.execute(f"CREATE TABLE curated.{table}(paper_id VARCHAR, {key} VARCHAR)")
                c.execute(f"INSERT INTO curated.{table} VALUES {values}")

    def build(self):
        with redirect_stdout(io.StringIO()):
            return build_analytics(self.path)

    def query(self, sql):
        with duckdb.connect(str(self.path), read_only=True) as c:
            return c.execute(sql).fetchall()

    def test_views_kpis_and_rerun(self):
        views, kpis = self.build()
        self.assertEqual(tuple(views), VIEW_NAMES)
        self.assertEqual(kpis['total_papers'], 5)
        self.assertEqual(kpis['total_citations'], 50)
        self.assertEqual(kpis['average_citations_per_paper'], 12.5)
        self.assertEqual(kpis['median_citations_per_paper'], 15)
        self.assertEqual(kpis['open_access_percentage'], 40)
        self.assertEqual(kpis['unique_authors'], 2)
        before = {view: self.query(f'SELECT * FROM analytics.{view} ORDER BY ALL') for view in views}
        self.assertEqual(self.build(), (views, kpis))
        self.assertEqual(before, {view: self.query(f'SELECT * FROM analytics.{view} ORDER BY ALL') for view in views})

    def test_growth_and_calendar_gaps(self):
        self.build()
        self.assertEqual(self.query(
            'SELECT publication_year,previous_year_paper_count,year_over_year_growth_percentage '
            'FROM analytics.publication_trends ORDER BY publication_year'
        ), [(2022,None,None),(2023,1,100.0),(2025,None,None)])
        self.assertEqual(self.query(
            "SELECT year_over_year_growth_percentage FROM analytics.topic_yearly_trends "
            "WHERE topic_id='T1' AND publication_year=2023"
        ), [(0.0,)])

    def test_domains_do_not_multiply_citations(self):
        self.build()
        self.assertEqual(self.query("SELECT paper_count,total_citations FROM analytics.topic_summary WHERE topic_id='T1'"), [(3,30)])
        self.assertEqual(self.query("SELECT paper_count,total_citations_of_authored_papers FROM analytics.author_summary WHERE author_id='A1'"), [(2,30)])
        self.assertEqual(self.query("SELECT paper_count,total_citations FROM analytics.institution_summary WHERE institution_id='I1'"), [(2,30)])
        self.assertEqual(self.query("SELECT paper_count,percentage_of_papers FROM analytics.open_access_summary WHERE oa_status='unknown'"), [(2,40.0)])

    def test_rank_ties_and_age_metric(self):
        self.build()
        self.assertEqual(self.query('SELECT paper_id FROM analytics.top_papers ORDER BY citation_rank'),
                         [('P2',),('P3',),('P1',),('P4',),('P5',)])
        self.assertEqual(self.query("SELECT citations_per_year_since_publication FROM analytics.top_papers WHERE paper_id='P5'"), [(None,)])
        self.assertEqual(self.query("SELECT citations_per_year_since_publication = 10.0 / greatest(1, year(current_date)-2022+1) FROM analytics.top_papers WHERE paper_id='P1'"), [(True,)])

    def test_empty_data_safe_division(self):
        with duckdb.connect(str(self.path)) as c:
            for table in ('paper_topics','paper_authors','paper_institutions','papers'):
                c.execute(f'DELETE FROM curated.{table}')
        _, kpis = self.build()
        self.assertEqual(kpis['total_papers'], 0)
        self.assertIsNone(kpis['open_access_percentage'])
        self.assertIsNone(kpis['average_citations_per_paper'])
        self.assertEqual(self.query('SELECT * FROM analytics.publication_trends'), [])

    def test_missing_optional_fields_omit_metrics(self):
        with duckdb.connect(str(self.path)) as c:
            for field in ('publication_year','cited_by_count','oa_status','is_open_access'):
                c.execute(f'ALTER TABLE curated.papers DROP COLUMN {field}')
        views, kpis = self.build()
        self.assertNotIn('publication_trends', views)
        self.assertNotIn('topic_yearly_trends', views)
        self.assertNotIn('open_access_summary', views)
        self.assertNotIn('total_citations', kpis)
        self.assertNotIn('open_access_percentage', kpis)

    def test_quality_rejects_bad_percentage(self):
        views, _ = self.build()
        with duckdb.connect(str(self.path)) as c:
            c.execute('CREATE OR REPLACE VIEW analytics.open_access_summary AS '
                      "SELECT 'bad' AS oa_status, 5 AS paper_count, 101.0 AS percentage_of_papers")
            with self.assertRaisesRegex(AnalyticsError, 'Invalid analytical'):
                validate_analytics(c, views)

    def test_missing_stage4_fails_without_new_file(self):
        missing = self.path.with_name('missing.duckdb')
        with self.assertRaises(AnalyticsError):
            build_analytics(missing)
        self.assertFalse(missing.exists())
        with duckdb.connect(str(self.path)) as c:
            c.execute('DROP TABLE curated.topics')
        with self.assertRaisesRegex(AnalyticsError, 'build Stage 4'):
            self.build()


if __name__ == '__main__':
    unittest.main()
