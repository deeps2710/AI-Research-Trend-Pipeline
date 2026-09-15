"""Build and validate analytical views without copying curated records."""


import logging

LOGGER = logging.getLogger("research_pipeline")

import duckdb

from src.config import DEFAULT_DATABASE as DEFAULT_DATABASE, PROJECT_ROOT, PathLike, resolve_path
from src.transform.schema import TABLE_KEYS, columns
from src.transform.curated import validate_curated

SQL_DIRECTORY = PROJECT_ROOT / "sql" / "analytics"
VIEW_NAMES = (
    "overview_kpis", "publication_trends", "topic_summary", "topic_yearly_trends",
    "top_papers", "author_summary", "institution_summary", "open_access_summary",
)


class AnalyticsError(ValueError):
    """Missing prerequisites or invalid analytical output."""


def render_sql(text, available):
    """Resolve simple, non-nested optional-field blocks in repository SQL.

    -- requires omits a whole view; -- if / -- endif omit optional metrics.
    No template dependency or user-provided SQL is needed.
    """
    output = []
    include = True
    for line in text.splitlines():
        marker = line.strip()
        if marker.startswith("-- requires "):
            if not set(marker.split()[2:]) <= available:
                return None
        elif marker.startswith("-- if "):
            include = set(marker.split()[2:]) <= available
        elif marker == "-- endif":
            include = True
        elif include:
            output.append(line)
    return "\n".join(output)


def overview(connection):
    result = connection.execute("SELECT * FROM analytics.overview_kpis")
    return dict(zip((column[0] for column in result.description), result.fetchone()))


def validate_analytics(connection, views):
    total = connection.execute("SELECT count(*) FROM curated.papers").fetchone()[0]
    if overview(connection)["total_papers"] != total:
        raise AnalyticsError("Overview paper count differs from curated.papers")
    if "publication_trends" in views:
        count = connection.execute("SELECT coalesce(sum(paper_count),0) FROM analytics.publication_trends").fetchone()[0]
        expected = connection.execute("SELECT count(*) FROM curated.papers WHERE publication_year IS NOT NULL").fetchone()[0]
        if count != expected:
            raise AnalyticsError("Yearly counts do not reconcile with known publication years")
    if "open_access_summary" in views:
        count = connection.execute("SELECT coalesce(sum(paper_count),0) FROM analytics.open_access_summary").fetchone()[0]
        if count != total:
            raise AnalyticsError("OA categories do not reconcile with total papers")
    # Reconcile each independent domain to its distinct bridge grain.
    for view, bridge, key in (
        ("topic_summary", "paper_topics", "topic_id"),
        ("author_summary", "paper_authors", "author_id"),
        ("institution_summary", "paper_institutions", "institution_id"),
    ):
        mismatches = connection.execute(
            f"WITH expected AS (SELECT {key}, count(DISTINCT paper_id) AS n "
            f"FROM curated.{bridge} GROUP BY {key}) "
            f"SELECT count(*) FROM expected e FULL JOIN analytics.{view} a USING ({key}) "
            "WHERE e.n IS DISTINCT FROM a.paper_count"
        ).fetchone()[0]
        if mismatches:
            raise AnalyticsError(f"Incorrect distinct paper grain in {view}")
    for view in views:
        fields = columns(connection, "analytics", view)
        for field in fields:
            condition = None
            if field.endswith("percentage") or field == "percentage_of_papers":
                condition = f"NOT isfinite({field})"
                # Growth can exceed 100% or be negative; shares cannot.
                if field != "year_over_year_growth_percentage":
                    condition += f" OR {field} < 0 OR {field} > 100"
            elif field in ("paper_count", "total_papers", "open_access_papers"):
                condition = f"{field} < 0 OR {field} > {total}"
            elif "citations" in field:
                condition = f"NOT isfinite({field})"
            if condition and connection.execute(
                f"SELECT count(*) FROM analytics.{view} WHERE {condition}"
            ).fetchone()[0]:
                raise AnalyticsError(f"Invalid analytical values in {view}.{field}")
    if "citation_rank" in columns(connection, "analytics", "top_papers"):
        if connection.execute(
            "SELECT count(*) FROM (SELECT citation_rank, row_number() OVER "
            "(ORDER BY cited_by_count DESC NULLS LAST, paper_id) AS expected "
            "FROM analytics.top_papers) WHERE citation_rank <> expected"
        ).fetchone()[0]:
            raise AnalyticsError("Top-paper ranking is not deterministic")


def build_analytics(database_path: PathLike = DEFAULT_DATABASE) -> tuple[list[str], dict]:
    path = resolve_path(database_path)
    if not path.is_file():
        raise AnalyticsError(f"Warehouse absent: {path}. Build Stage 4 first.")
    if path.stem.casefold() in {"analytics", "curated"}:
        raise AnalyticsError("Database filename must differ from the analytics/curated schema names")
    with duckdb.connect(str(path)) as connection:
        connection.execute("BEGIN TRANSACTION")
        try:
            available = set()
            for table, keys in TABLE_KEYS.items():
                fields = columns(connection, "curated", table)
                if not set(keys) <= fields:
                    raise AnalyticsError(f"Missing/incompatible curated.{table}; build Stage 4 first")
                available.update(f"{table}.{field}" for field in fields)
            validate_curated(connection)
            connection.execute("CREATE SCHEMA IF NOT EXISTS analytics")
            created = []
            for index, name in enumerate(VIEW_NAMES, start=1):
                sql = (SQL_DIRECTORY / f"{index:02d}_{name}.sql").read_text(encoding="utf-8")
                query = render_sql(sql, available)
                if query is None:
                    connection.execute(f"DROP VIEW IF EXISTS analytics.{name}")
                    LOGGER.info(f"Omitted {name}: required optional source field is absent")
                    continue
                connection.execute(query)
                created.append(name)
                LOGGER.info(f"Created analytics.{name}")
            validate_analytics(connection, created)
            kpis = overview(connection)
            connection.execute("COMMIT")
            return created, kpis
        except Exception:
            connection.execute("ROLLBACK")
            raise
