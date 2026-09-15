"""Transactional SQL rebuild with discovered optional columns and quality checks."""


import logging

LOGGER = logging.getLogger("research_pipeline")

import duckdb

from src.config import DEFAULT_DATABASE as DEFAULT_DATABASE, PROJECT_ROOT, PathLike, resolve_path
from src.transform.schema import TABLE_KEYS as TABLE_KEYS, FIELDS, columns as columns
SQL_DIRECTORY = PROJECT_ROOT / "sql" / "curated"



class CuratedError(ValueError):
    """A schema or integrity failure with a safe diagnostic."""


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
    # The transactional builder and standalone quality runner share one contract.
    from src.quality.checks import curated_checks
    from src.quality.models import Status
    results = curated_checks(connection)
    failures = [result for result in results if result.status == Status.FAIL]
    if failures:
        error = CuratedError(failures[0].details or failures[0].check_name)
        error.quality_results = results
        raise error


def build_curated(database_path: PathLike = DEFAULT_DATABASE) -> dict[str, int]:
    path = resolve_path(database_path)
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
                LOGGER.info(f"Built {sql_path.stem}")
            validate_curated(connection)
            counts = {table: connection.execute(f"SELECT count(*) FROM curated.{table}").fetchone()[0]
                      for table in TABLE_KEYS}
            connection.execute("COMMIT")
            return counts
        except Exception:
            connection.execute("ROLLBACK")
            raise
