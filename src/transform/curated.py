"""Transactional SQL rebuild with discovered optional columns and quality checks."""

from datetime import datetime, timezone
from pathlib import Path

import duckdb

DEFAULT_DATABASE = Path("data/warehouse/research_trends.duckdb")
SQL_DIRECTORY = Path(__file__).resolve().parents[2] / "sql" / "curated"
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


class CuratedError(ValueError):
    """A schema or integrity failure with a safe diagnostic."""


def columns(connection, schema, table):
    return {row[0] for row in connection.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema=? AND table_name=?", [schema, table]
    ).fetchall()}


def prepare_sources(connection):
    sources = {
        "w": ("works", {"id", "_dlt_id"}),
        "t": ("works__topics", {"id", "_dlt_parent_id"}),
        "a": ("works__authorships", {"author__id", "_dlt_id", "_dlt_parent_id"}),
        "i": ("works__authorships__institutions", {"id", "_dlt_parent_id"}),
    }
    found = {}
    for alias, (table, required) in sources.items():
        available = columns(connection, "openalex_data", table)
        if alias == "w" and not required <= available:
            raise CuratedError("Stage 3 works table requires id and _dlt_id")
        # A missing nested table/key means no identifiable entity was inferred.
        # Keep empty key-only temp views so the seven output grains stay stable.
        if not available:
            projection = ", ".join(f'CAST(NULL AS VARCHAR) AS "{name}"' for name in sorted(required))
            connection.execute(f"CREATE OR REPLACE TEMP VIEW {alias} AS SELECT {projection} WHERE FALSE")
            found[alias] = required
            continue
        business_key = "author__id" if alias == "a" else "id"
        if not (required - {business_key}) <= available:
            raise CuratedError(f"Incompatible Stage 3 table {table}: missing lineage columns")
        missing_key = f', CAST(NULL AS VARCHAR) AS "{business_key}"' if business_key not in available else ""
        connection.execute(f"CREATE OR REPLACE TEMP VIEW {alias} AS SELECT *{missing_key} FROM openalex_data.{table}")
        found[alias] = available
    # Do not hide broken lineage through inner joins.
    for child, parent in (("t", "w"), ("a", "w"), ("i", "a")):
        if connection.execute(
            f"SELECT count(*) FROM {child} c LEFT JOIN {parent} p "
            "ON c._dlt_parent_id=p._dlt_id WHERE p._dlt_id IS NULL"
        ).fetchone()[0]:
            raise CuratedError(f"Orphan Stage 3 lineage in {child}")
    return found


def projections(found):
    result = {}
    for entity, alias in (("papers", "w"), ("topics", "t"), ("authors", "a"), ("institutions", "i")):
        result[entity] = "".join(
            f',\n    {alias}."{source}" AS {target}'
            for source, target in FIELDS[entity].items() if source in found[alias]
        )
    result["topic_attributes"] = (
        ",\n    max(t.score) AS topic_score" if "score" in found["t"] else ""
    )
    if "primary_topic__id" in found["w"]:
        result["topic_attributes"] += ",\n    bool_or(t.id = w.primary_topic__id) AS is_primary_topic"
    result["author_attributes"] = "".join(
        f",\n    a.{name}" for name in ("author_position", "is_corresponding") if name in found["a"]
    )
    return result


def validate_curated(connection):
    for table, keys in TABLE_KEYS.items():
        nulls = " OR ".join(f"{key} IS NULL OR trim({key})=''" for key in keys)
        if connection.execute(f"SELECT count(*) FROM curated.{table} WHERE {nulls}").fetchone()[0]:
            raise CuratedError(f"Null/blank business key in curated.{table}")
        key_sql = ", ".join(keys)
        if connection.execute(
            f"SELECT count(*) FROM (SELECT {key_sql} FROM curated.{table} "
            f"GROUP BY {key_sql} HAVING count(*)>1)"
        ).fetchone()[0]:
            raise CuratedError(f"Duplicate grain in curated.{table}")
    for bridge, dimension, key in (("paper_topics", "topics", "topic_id"),
                                   ("paper_authors", "authors", "author_id"),
                                   ("paper_institutions", "institutions", "institution_id")):
        for target, target_key in (("papers", "paper_id"), (dimension, key)):
            if connection.execute(
                f"SELECT count(*) FROM curated.{bridge} b LEFT JOIN curated.{target} d "
                f"ON b.{target_key}=d.{target_key} WHERE d.{target_key} IS NULL"
            ).fetchone()[0]:
                raise CuratedError(f"Broken reference from {bridge} to {target}")
    if "publication_year" in columns(connection, "curated", "papers"):
        maximum = datetime.now(timezone.utc).year + 1
        if connection.execute(
            "SELECT count(*) FROM curated.papers WHERE publication_year IS NOT NULL "
            "AND (publication_year < 1500 OR publication_year > ?)", [maximum]
        ).fetchone()[0]:
            raise CuratedError(f"Publication year outside supported range 1500–{maximum}")


def build_curated(database_path=DEFAULT_DATABASE):
    path = Path(database_path).resolve()
    if not path.is_file():
        raise CuratedError(f"Warehouse absent: {path}. Run Stage 3 first.")
    with duckdb.connect(str(path)) as connection:
        connection.execute("BEGIN TRANSACTION")
        try:
            found = prepare_sources(connection)
            substitutions = projections(found)
            connection.execute("CREATE SCHEMA IF NOT EXISTS curated")
            for sql_path in sorted(SQL_DIRECTORY.glob("*.sql")):
                query = sql_path.read_text(encoding="utf-8")
                for name, value in substitutions.items():
                    query = query.replace("{{" + name + "}}", value)
                connection.execute(query)
                print(f"Built {sql_path.stem}")
            validate_curated(connection)
            counts = {table: connection.execute(f"SELECT count(*) FROM curated.{table}").fetchone()[0]
                      for table in TABLE_KEYS}
            connection.execute("COMMIT")
            return counts
        except Exception:
            connection.execute("ROLLBACK")
            raise
