"""Read small Stage 5 results and batch-save applicable charts."""

from pathlib import Path

import duckdb
import pandas as pd

from src.transform.curated import DEFAULT_DATABASE, columns
from src.visualization import charts

DEFAULT_OUTPUT = Path("outputs/figures")
JOBS = (
    ("publications_over_time", "publication_trends", charts.plot_publication_trends),
    ("year_over_year_growth", "publication_trends", charts.plot_year_over_year_growth),
    ("top_topics", "topic_summary", charts.plot_top_topics),
    ("topic_trends", "topic_yearly_trends", charts.plot_topic_trends),
    ("citation_distribution", "top_papers", charts.plot_citation_distribution),
    ("top_cited_papers", "top_papers", charts.plot_top_cited_papers),
    ("open_access_distribution", "open_access_summary", charts.plot_open_access),
    ("top_authors", "author_summary", charts.plot_top_authors),
    ("top_institutions", "institution_summary", charts.plot_top_institutions),
)


def generate_visualizations(db_path=DEFAULT_DATABASE, output_dir=DEFAULT_OUTPUT, top_n=10):
    if type(top_n) is not int or not 1 <= top_n <= 30:
        raise ValueError("top_n must be an integer between 1 and 30")
    database = Path(db_path).resolve()
    if not database.is_file():
        raise FileNotFoundError("Warehouse absent; run Stages 3–5 first")
    output = Path(output_dir)
    generated, skipped = [], []
    with duckdb.connect(str(database), read_only=True) as connection:
        if not columns(connection, "analytics", "overview_kpis"):
            raise ValueError("Stage 5 analytics schema is absent; run scripts.build_analytics")
        output.mkdir(parents=True, exist_ok=True)
        for name, view, plot in JOBS:
            fields = columns(connection, "analytics", view)
            options = {}
            query = f"SELECT * FROM analytics.{view}"
            if name in {"top_topics", "top_authors", "top_institutions", "top_cited_papers"}:
                key = {"top_topics": "topic_id", "top_authors": "author_id",
                       "top_institutions": "institution_id", "top_cited_papers": "paper_id"}[name]
                metric = "cited_by_count" if name == "top_cited_papers" else "paper_count"
                if {key, metric} <= fields:
                    query += f" ORDER BY {metric} DESC NULLS LAST, {key} LIMIT {top_n}"
                options["top_n"] = top_n
            elif name == "citation_distribution" and "cited_by_count" in fields:
                query = "SELECT cited_by_count FROM analytics.top_papers"
            elif name == "topic_trends" and {"topic_id", "paper_count"} <= fields:
                # Selection only; analytical measures remain defined by Stage 5.
                query += (" WHERE topic_id IN (SELECT topic_id FROM analytics.topic_yearly_trends "
                          "GROUP BY topic_id ORDER BY sum(paper_count) DESC, topic_id LIMIT 5)")
            frame = connection.execute(query).fetchdf() if fields else pd.DataFrame()
            path = output / f"{name}.png"
            result = plot(frame, path, **options)
            if result is None:
                # Never leave a stale multi-year chart from an earlier run.
                path.unlink(missing_ok=True)
                reason = ("multi-year observations and valid growth/trend data required"
                          if name in {"year_over_year_growth", "topic_trends"}
                          else "view/fields absent or no usable records")
                print(f"Skipped {name}: {reason}")
                skipped.append(name)
            else:
                print(f"Saved {result}")
                generated.append(result)
    return generated, skipped
