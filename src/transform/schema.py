"""Shared curated schema contract and metadata inspection; no stage dependencies."""
import duckdb

TABLE_KEYS = {
    "papers": ("paper_id",), "topics": ("topic_id",),
    "paper_topics": ("paper_id", "topic_id"), "authors": ("author_id",),
    "paper_authors": ("paper_id", "author_id"),
    "institutions": ("institution_id",),
    "paper_institutions": ("paper_id", "institution_id"),
}
# Mappings are based on DESCRIBE of the real Stage 3 database. Optional
# columns are projected only when dlt actually materialized them.
FIELDS = {
    "papers": {
        "doi": "doi", "title": "title", "publication_year": "publication_year",
        "publication_date": "publication_date", "type": "work_type",
        "cited_by_count": "cited_by_count", "open_access__is_oa": "is_open_access",
        "open_access__oa_status": "oa_status", "primary_topic__id": "primary_topic_id",
        "primary_topic__display_name": "primary_topic_name",
        "primary_location__source__id": "source_id",
        "primary_location__source__display_name": "source_name",
    },
    "topics": {
        "display_name": "topic_name", "subfield__id": "subfield_id",
        "subfield__display_name": "subfield_name", "field__id": "field_id",
        "field__display_name": "field_name", "domain__id": "domain_id",
        "domain__display_name": "domain_name",
    },
    "authors": {"author__display_name": "author_name"},
    "institutions": {"display_name": "institution_name", "country_code": "country_code",
                     "type": "institution_type"},
}


def columns(connection: duckdb.DuckDBPyConnection, schema: str, table: str) -> set[str]:
    return {row[0] for row in connection.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema=? AND table_name=?", [schema, table]
    ).fetchall()}
