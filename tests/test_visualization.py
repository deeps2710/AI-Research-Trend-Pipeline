"""Headless chart execution and selection tests; no pixel comparisons."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

import duckdb
import pandas as pd
from PIL import Image
from matplotlib._pylab_helpers import Gcf

from src.visualization import charts
from src.visualization.generate import JOBS, generate_visualizations


class VisualizationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_empty_inputs_skip_without_files(self):
        for name, _, plot in JOBS:
            with self.subTest(name=name):
                path = self.root / f"{name}.png"
                self.assertIsNone(plot(pd.DataFrame(), path))
                self.assertFalse(path.exists())

    def test_one_year_and_null_growth(self):
        frame = pd.DataFrame({"publication_year": [2025], "paper_count": [250],
                              "year_over_year_growth_percentage": [None]})
        self.assertTrue(charts.plot_publication_trends(frame, self.root / "year.png").exists())
        self.assertIsNone(charts.plot_year_over_year_growth(frame, self.root / "growth.png"))
        frame["topic_id"] = "T1"
        self.assertIsNone(charts.plot_topic_trends(frame, self.root / "topics.png"))

    def test_multi_year_charts_and_gaps(self):
        frame = pd.DataFrame({"publication_year": [2022, 2023, 2025], "paper_count": [2, 4, 3],
                              "year_over_year_growth_percentage": [None, 100.0, None]})
        self.assertTrue(charts.plot_year_over_year_growth(frame, self.root / "growth.png").exists())
        frame["topic_id"] = "T1"
        frame["topic_name"] = "Long topic label " * 8
        self.assertTrue(charts.plot_topic_trends(frame, self.root / "topics.png", topic_ids=["T1"]).exists())
        frame["year_over_year_growth_percentage"] = None
        self.assertIsNone(charts.plot_year_over_year_growth(frame, self.root / "unknown.png"))

    def test_ranked_charts_long_labels_and_tie_selection(self):
        frame = pd.DataFrame({"paper_count": [5, 10, 10], "cited_by_count": [0, 10, 10000],
                              "topic_id": ["C", "B", "A"], "paper_id": ["C", "B", "A"]})
        self.assertEqual(charts.select_top(frame, "paper_count", "topic_id", 1).topic_id.tolist(), ["A"])
        with self.assertRaises(ValueError):
            charts.select_top(frame, "paper_count", "topic_id", 0)
        frame["topic_name"] = "A long but identifiable research topic " * 15
        frame["title"] = frame.topic_name
        frame["author_id"] = frame.topic_id
        frame["author_name"] = frame.topic_name
        frame["institution_id"] = frame.topic_id
        frame["institution_name"] = frame.topic_name
        for name, plot in (("topics", charts.plot_top_topics), ("papers", charts.plot_top_cited_papers),
                            ("authors", charts.plot_top_authors), ("institutions", charts.plot_top_institutions)):
            path = plot(frame, self.root / f"{name}.png", top_n=2)
            with Image.open(path) as image:
                self.assertGreaterEqual(image.width, 2000)
                self.assertGreaterEqual(image.height, 1000)
        self.assertEqual(Gcf.get_all_fig_managers(), [])

    def test_citation_skew_zero_and_oa_unknown(self):
        for values in ([0, 0], [0, 1, 5, 1000000], [None]):
            frame = pd.DataFrame({"cited_by_count": values})
            for log_spacing in (True, False):
                result = charts.plot_citation_distribution(frame, self.root / "hist.png", log_spacing)
                self.assertEqual(result is None, values == [None])
        oa = pd.DataFrame({"oa_status": ["gold", None], "paper_count": [1, 2]})
        original = oa.copy(deep=True)
        self.assertTrue(charts.plot_open_access(oa, self.root / "oa.png").exists())
        pd.testing.assert_frame_equal(oa, original)

    def test_batch_repeatability_and_stale_skip_cleanup(self):
        database = self.root / "fixture.duckdb"
        output = self.root / "figures"
        with duckdb.connect(str(database)) as c:
            c.execute('CREATE SCHEMA analytics')
            c.execute('CREATE VIEW analytics.overview_kpis AS SELECT 2 AS total_papers')
            c.execute('CREATE VIEW analytics.publication_trends AS SELECT 2025 AS publication_year, '
                      '2 AS paper_count, NULL::DOUBLE AS year_over_year_growth_percentage')
            c.execute("CREATE VIEW analytics.top_papers AS SELECT 'W1' AS paper_id, 'Sample' AS title, 2 AS cited_by_count")
        with redirect_stdout(io.StringIO()):
            first, skipped = generate_visualizations(database, output)
            stale = output / 'year_over_year_growth.png'
            stale.write_bytes(b'old result')
            second, skipped_again = generate_visualizations(database, output)
        self.assertEqual(first, second)
        self.assertEqual(skipped, skipped_again)
        self.assertEqual(len(first), 3)
        self.assertFalse(stale.exists())
        for path in first:
            self.assertGreater(path.stat().st_size, 1000)
        self.assertEqual(Gcf.get_all_fig_managers(), [])

    def test_missing_database_and_analytics(self):
        database = self.root / 'missing.duckdb'
        with self.assertRaises(FileNotFoundError):
            generate_visualizations(database, self.root / 'output')
        self.assertFalse(database.exists())
        with duckdb.connect(str(database)):
            pass
        with self.assertRaisesRegex(ValueError, 'Stage 5'):
            generate_visualizations(database, self.root / 'output')


if __name__ == '__main__':
    unittest.main()
