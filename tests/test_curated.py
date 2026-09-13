"""Real DuckDB SQL tests using a tiny model of the observed dlt schema."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

import duckdb

from src.transform.curated import CuratedError, TABLE_KEYS, build_curated, validate_curated


class CuratedTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "test.duckdb"
        with duckdb.connect(str(self.path)) as c:
            c.execute("CREATE SCHEMA openalex_data")
            c.execute("CREATE TABLE openalex_data.works(id VARCHAR, _dlt_id VARCHAR, "
                      "title VARCHAR, publication_year BIGINT, primary_topic__id VARCHAR)")
            c.execute("INSERT INTO openalex_data.works VALUES ('W1','r1','One',2025,'T1'), "
                      "('W2','r2',NULL,NULL,NULL)")

    def build(self):
        with redirect_stdout(io.StringIO()):
            return build_curated(self.path)

    def nested(self):
        with duckdb.connect(str(self.path)) as c:
            c.execute("CREATE TABLE openalex_data.works__topics(id VARCHAR, _dlt_parent_id VARCHAR, "
                      "display_name VARCHAR, score DOUBLE)")
            c.execute("INSERT INTO openalex_data.works__topics VALUES "
                      "('T1','r1','Topic',0.8),('T1','r1','Topic',0.9),('T1','r2','Topic',0.7)")
            c.execute("CREATE TABLE openalex_data.works__authorships(author__id VARCHAR, "
                      "_dlt_id VARCHAR, _dlt_parent_id VARCHAR, author__display_name VARCHAR)")
            c.execute("INSERT INTO openalex_data.works__authorships VALUES "
                      "('A1','a1','r1','Author'),('A1','a2','r1','Author'),('A1','a3','r2','Author')")
            c.execute("CREATE TABLE openalex_data.works__authorships__institutions "
                      "(id VARCHAR, _dlt_parent_id VARCHAR, display_name VARCHAR)")
            c.execute("INSERT INTO openalex_data.works__authorships__institutions VALUES "
                      "('I1','a1','University'),('I1','a2','University')")

    def test_build_rerun_uniqueness_and_references(self):
        self.nested()
        expected = dict(papers=2, topics=1, paper_topics=2, authors=1,
                        paper_authors=2, institutions=1, paper_institutions=1)
        self.assertEqual(self.build(), expected)
        self.assertEqual(self.build(), expected)
        with duckdb.connect(str(self.path)) as c:
            validate_curated(c)
            self.assertEqual(c.execute("SELECT topic_score FROM curated.paper_topics "
                                       "WHERE paper_id='W1'").fetchone()[0], 0.9)
            self.assertEqual(c.execute("SELECT count(*) FROM openalex_data.works").fetchone()[0], 2)

    def test_missing_optional_tables_and_columns(self):
        counts = self.build()
        self.assertEqual(set(counts), set(TABLE_KEYS))
        self.assertEqual(counts['papers'], 2)
        self.assertTrue(all(count == 0 for table, count in counts.items() if table != 'papers'))
        with duckdb.connect(str(self.path)) as c:
            names = {row[0] for row in c.execute('DESCRIBE curated.papers').fetchall()}
            self.assertNotIn('doi', names)
            self.assertNotIn('_dlt_id', names)

    def test_failed_rebuild_rolls_back(self):
        self.build()
        with duckdb.connect(str(self.path)) as c:
            c.execute("INSERT INTO openalex_data.works VALUES ('W1','r3','duplicate',2025,NULL)")
        with self.assertRaisesRegex(CuratedError, 'Duplicate grain'):
            self.build()
        with duckdb.connect(str(self.path)) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM curated.papers').fetchone()[0], 2)

    def test_bad_year_and_null_id_fail(self):
        for change in ("publication_year=9999", "id=NULL"):
            with duckdb.connect(str(self.path)) as c:
                c.execute("UPDATE openalex_data.works SET publication_year=2025, id='W1' WHERE _dlt_id='r1'")
                c.execute(f"UPDATE openalex_data.works SET {change} WHERE _dlt_id='r1'")
            with self.assertRaises(CuratedError):
                self.build()

    def test_unknown_author_keeps_identified_institution(self):
        self.nested()
        with duckdb.connect(str(self.path)) as c:
            c.execute('ALTER TABLE openalex_data.works__authorships DROP COLUMN author__id')
        counts = self.build()
        self.assertEqual(counts['authors'], 0)
        self.assertEqual(counts['paper_authors'], 0)
        self.assertEqual(counts['paper_institutions'], 1)

    def test_orphans_and_broken_curated_references_fail(self):
        self.nested()
        self.build()
        with duckdb.connect(str(self.path)) as c:
            c.execute("UPDATE curated.paper_topics SET topic_id='absent'")
            with self.assertRaisesRegex(CuratedError, 'Broken reference'):
                validate_curated(c)
            c.execute("UPDATE openalex_data.works__topics SET _dlt_parent_id='absent'")
        with self.assertRaisesRegex(CuratedError, 'Orphan'):
            self.build()

    def test_missing_warehouse_and_incompatible_root(self):
        with self.assertRaises(CuratedError):
            build_curated(self.path.with_name('missing.duckdb'))
        with duckdb.connect(str(self.path)) as c:
            c.execute('DROP TABLE openalex_data.works')
        with self.assertRaises(CuratedError):
            self.build()


if __name__ == '__main__':
    unittest.main()
