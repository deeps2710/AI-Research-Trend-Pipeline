"""Small local benchmark on a private warehouse copy, without API access."""
from pathlib import Path
import shutil
from statistics import median
import tempfile
from time import perf_counter

import duckdb
from src.config import DEFAULT_DATABASE, PathLike, resolve_path
from src.transform.curated import build_curated
from src.transform.analytics import build_analytics
from src.quality.runner import run_quality, enforce
from src.transform.schema import columns

QUERIES = {
    'topics': ('topic_summary', {'topic_id','paper_count'},
        'SELECT topic_id,paper_count FROM analytics.topic_summary ORDER BY paper_count DESC,topic_id LIMIT 10'),
    'papers': ('top_papers', {'paper_id','cited_by_count'},
        'SELECT paper_id,cited_by_count FROM analytics.top_papers ORDER BY cited_by_count DESC NULLS LAST,paper_id LIMIT 50'),
    'filtered_papers': ('top_papers', {'paper_id','cited_by_count','publication_year'},
        'SELECT p.paper_id,p.cited_by_count FROM analytics.top_papers p WHERE p.publication_year='
        '(SELECT max(publication_year) FROM curated.papers) AND p.cited_by_count>=0 '
        'AND EXISTS (SELECT 1 FROM curated.paper_topics b WHERE b.paper_id=p.paper_id AND b.topic_id='
        '(SELECT topic_id FROM curated.paper_topics ORDER BY topic_id LIMIT 1)) '
        'ORDER BY p.cited_by_count DESC NULLS LAST,p.paper_id LIMIT 50'),
    'authors': ('author_summary', {'author_id','paper_count'},
        'SELECT author_id,paper_count FROM analytics.author_summary ORDER BY paper_count DESC,author_id LIMIT 10'),
    'institutions': ('institution_summary', {'institution_id','paper_count'},
        'SELECT institution_id,paper_count FROM analytics.institution_summary ORDER BY paper_count DESC,institution_id LIMIT 10'),
}


def benchmark(database: PathLike = DEFAULT_DATABASE, *, explain: bool = False) -> dict[str, float]:
    """Time one build per stage and median of three warm query executions (seconds)."""
    source = resolve_path(database)
    if not source.is_file():
        raise FileNotFoundError('Benchmark warehouse absent')
    timings = {}
    with tempfile.TemporaryDirectory(prefix='research-benchmark-') as temporary:
        copy = Path(temporary)/'benchmark.duckdb'
        # Hold a read lock while copying database and any uncheckpointed WAL.
        with duckdb.connect(str(source), read_only=True):
            shutil.copyfile(source,copy)
            wal = Path(str(source)+'.wal')
            if wal.is_file():
                shutil.copyfile(wal,Path(str(copy)+'.wal'))
        for name, operation in [('curated',build_curated),('analytics',build_analytics),('quality',run_quality)]:
            start = perf_counter()
            result = operation(copy)
            timings[name] = perf_counter()-start
            if name == 'quality':
                enforce(result[1])
            print(f'{name}: {timings[name]*1000:.2f} ms')
        with duckdb.connect(str(copy),read_only=True) as con:
            for name,(view,required,sql) in QUERIES.items():
                if not required <= columns(con,'analytics',view):
                    print(f'query.{name}: skipped (optional fields absent)')
                    continue
                con.execute(sql).fetchall()
                samples = []
                for _ in range(3):
                    start = perf_counter()
                    con.execute(sql).fetchall()
                    samples.append(perf_counter()-start)
                timings['query.'+name] = median(samples)
                print(f'query.{name}: {median(samples)*1000:.2f} ms (median of 3 warm runs)')
                if explain:
                    print(con.execute('EXPLAIN ANALYZE '+sql).fetchone()[1])
    return timings
