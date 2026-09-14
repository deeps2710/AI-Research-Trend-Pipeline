"""Parameterized read-only queries; no pipeline imports or cached connections."""
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

ORDERS = {
    "overview_kpis": "1", "publication_trends": "publication_year",
    "topic_summary": "paper_count DESC, topic_id",
    "topic_yearly_trends": "publication_year, topic_id",
    "author_summary": "paper_count DESC, author_id",
    "institution_summary": "paper_count DESC, institution_id",
    "open_access_summary": "paper_count DESC, oa_status",
}


class DashboardError(ValueError):
    """Safe user-facing failure text."""


@st.cache_data(ttl=30, max_entries=128, show_spinner=False)
def _cached_read(path, signature, sql, parameters):
    # signature participates in the cache key, even though SQL does not use it.
    with duckdb.connect(path, read_only=True) as connection:
        return connection.execute(sql, parameters).fetchdf()


def _read(path, sql, parameters=()):
    path = Path(path).resolve()
    if not path.is_file():
        raise DashboardError("Warehouse not found. Build the local pipeline through Stage 5 first.")
    try:
        info = path.stat()
        return _cached_read(str(path), (info.st_mtime_ns, info.st_size), sql, tuple(parameters))
    except (duckdb.Error, OSError):
        raise DashboardError("Cannot read analytics. Close warehouse writers and check that Stage 5 is built.") from None


def fields(path, table, schema="analytics"):
    return set(_read(path, "SELECT column_name FROM information_schema.columns "
                     "WHERE table_schema=? AND table_name=?", (schema, table)).column_name)


def validate_database(path):
    if "total_papers" not in fields(path, "overview_kpis"):
        raise DashboardError("Analytics is not available. Run scripts.build_analytics after Stage 4.")


def get_view(path, name, limit=500, topic_id=None):
    if name not in ORDERS:
        raise ValueError("Unsupported analytical view")
    if not 1 <= limit <= 10000:
        raise ValueError("Result limit must be 1–10000")
    available = fields(path, name)
    if not available:
        return pd.DataFrame()
    condition, parameters = "", []
    if topic_id is not None:
        if "topic_id" not in available:
            raise ValueError("This view cannot filter by topic")
        condition = " WHERE topic_id=?"
        parameters.append(topic_id)
    parameters.append(limit)
    return _read(path, f"SELECT * FROM analytics.{name}{condition} ORDER BY {ORDERS[name]} LIMIT ?", parameters)


def get_overview_kpis(path):
    data = get_view(path, "overview_kpis", limit=1)
    return data.iloc[0].to_dict() if not data.empty else {}


def topic_filter_available(path):
    return {"paper_id", "topic_id"} <= fields(path, "paper_topics", "curated")


def get_papers(path, year=None, topic_id=None, min_citations=None, oa_status=None,
               sort="citations", limit=50):
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("Paper limit must be 1–200")
    available = fields(path, "top_papers")
    if "paper_id" not in available:
        return pd.DataFrame()
    filters, parameters = [], []
    for column, value, comparison in (("publication_year", year, "="),
                                       ("cited_by_count", min_citations, ">=")):
        if value is not None:
            if column not in available:
                raise DashboardError(f"Filter unavailable: {column}")
            filters.append(f"p.{column} {comparison} ?")
            parameters.append(value)
    if oa_status is not None:
        if "oa_status" not in available:
            raise DashboardError("OA status filter is unavailable")
        filters.append("coalesce(nullif(trim(p.oa_status),''),'unknown')=?")
        parameters.append(oa_status)
    if topic_id is not None:
        if not topic_filter_available(path):
            raise DashboardError("Topic relationships are unavailable")
        # EXISTS preserves one paper row even if a bridge contains repeated links.
        filters.append("EXISTS (SELECT 1 FROM curated.paper_topics b "
                       "WHERE b.paper_id=p.paper_id AND b.topic_id=?)")
        parameters.append(topic_id)
    order_columns = {"citations": "cited_by_count", "year": "publication_year", "title": "title"}
    if sort not in order_columns:
        raise ValueError("Unsupported sort")
    order = order_columns[sort]
    ordering = (f"p.{order} {'ASC' if sort == 'title' else 'DESC'} NULLS LAST, "
                if order in available else "") + "p.paper_id"
    allowed = ("paper_id", "title", "publication_year", "cited_by_count",
               "primary_topic_name", "is_open_access", "oa_status", "doi")
    projection = ", ".join(f"p.{column}" for column in allowed if column in available)
    where = " WHERE " + " AND ".join(filters) if filters else ""
    parameters.append(limit)
    return _read(path, f"SELECT {projection} FROM analytics.top_papers p{where} ORDER BY {ordering} LIMIT ?", parameters)
