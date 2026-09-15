"""Execute checks and persist results separately from analytical data."""
import logging
from collections import Counter
import uuid
import duckdb
from src.quality.checks import curated_checks, coverage_checks
from src.quality.analytics import analytics_checks
from src.quality.models import Status, QualityError, Result
from src.config import PathLike, resolve_path

LOGGER = logging.getLogger('research_pipeline')


def persist(database: PathLike, results: list[Result], run_id: str | None = None, execution_id: str | None = None) -> str:
    execution_id = execution_id or str(uuid.uuid4())
    with duckdb.connect(str(database)) as con:
        con.execute("""CREATE SCHEMA IF NOT EXISTS ops;
            CREATE TABLE IF NOT EXISTS ops.data_quality_results (
                execution_id VARCHAR, run_id VARCHAR, check_name VARCHAR, layer VARCHAR,
                status VARCHAR CHECK(status IN ('PASS','WARN','FAIL')), observed_value VARCHAR,
                expected_condition VARCHAR, details VARCHAR, checked_at TIMESTAMPTZ DEFAULT current_timestamp)""")
        if results:
            con.execute('BEGIN TRANSACTION')
            con.executemany('INSERT INTO ops.data_quality_results VALUES (?,?,?,?,?,?,?,?,current_timestamp)',
                [(execution_id,run_id,r.check_name,r.layer,r.status.value,r.observed_value,r.expected_condition,r.details) for r in results])
            con.execute('COMMIT')
    for r in results:
        LOGGER.log(logging.ERROR if r.status == Status.FAIL else logging.WARNING if r.status == Status.WARN else logging.DEBUG,
                   'run_id=%s stage=quality check=%s status=%s observed=%s',run_id or execution_id,r.check_name,r.status.value,r.observed_value)
    counts = Counter(r.status.value for r in results)
    LOGGER.info('run_id=%s stage=quality PASS=%s WARN=%s FAIL=%s',run_id or execution_id,
                counts['PASS'],counts['WARN'],counts['FAIL'])
    return execution_id


def enforce(results: list[Result]) -> None:
    if any(r.status == Status.FAIL for r in results):
        raise QualityError(results)


def run_quality(database: PathLike, layers: tuple[str, ...] = ('curated','analytics'), run_id: str | None = None) -> tuple[str, list[Result]]:
    database = resolve_path(database)
    if not database.is_file():
        raise FileNotFoundError('Warehouse absent; build pipeline first')
    results = []
    with duckdb.connect(str(database), read_only=True) as con:
        if 'curated' in layers:
            results.extend(curated_checks(con))
            results.extend(coverage_checks(con))
        if 'analytics' in layers:
            results.extend(analytics_checks(con))
    execution_id = persist(database, results, run_id)
    return execution_id, results
