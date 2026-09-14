"""Read-only checks. SQL identifiers come only from the project schema contract."""
from datetime import datetime, timezone
import json

import duckdb
from src.load.openalex_dlt import read_jsonl
from src.transform.curated import TABLE_KEYS, columns
from src.quality.models import Result, Status


def outcome(name, layer, value, good, expected, details='', warning=False):
    return Result(name, layer, Status.PASS if good else Status.WARN if warning else Status.FAIL,
                  str(value), expected, details)


def zero_check(con, name, layer, sql, details):
    try:
        value = con.execute(sql).fetchone()[0]
        return outcome(name, layer, value, value == 0, '0 invalid rows', details)
    except duckdb.Error:
        return outcome(name, layer, 'unavailable', False, 'queryable compatible schema', 'Check could not query required fields')


def curated_checks(con):
    results = []
    ready = {}
    for table, keys in TABLE_KEYS.items():
        ready[table] = set(keys) <= columns(con, 'curated', table)
        results.append(outcome(f'{table}.schema', 'curated', ready[table], ready[table], 'business keys present'))
        if not ready[table]:
            continue
        nulls = ' OR '.join(f"{key} IS NULL OR trim({key})=''" for key in keys)
        results.append(zero_check(con, f'{table}.identity', 'curated',
            f'SELECT count(*) FROM curated.{table} WHERE {nulls}', f'Null/blank business key in curated.{table}'))
        keys_sql = ','.join(keys)
        results.append(zero_check(con, f'{table}.unique', 'curated',
            f'SELECT count(*) FROM (SELECT {keys_sql} FROM curated.{table} GROUP BY {keys_sql} HAVING count(*)>1)',
            f'Duplicate grain in curated.{table}'))
    for bridge, dimension, key in [('paper_topics','topics','topic_id'), ('paper_authors','authors','author_id'),
                                    ('paper_institutions','institutions','institution_id')]:
        for target, target_key in [('papers','paper_id'), (dimension,key)]:
            if ready[bridge] and ready[target]:
                results.append(zero_check(con, f'{bridge}.{target}.references', 'curated',
                    f'SELECT count(*) FROM curated.{bridge} b LEFT JOIN curated.{target} d '
                    f'ON b.{target_key}=d.{target_key} WHERE d.{target_key} IS NULL', f'Broken reference from {bridge} to {target}'))
    fields = columns(con, 'curated', 'papers')
    maximum = datetime.now(timezone.utc).year + 1
    for field, condition in [('cited_by_count', 'cited_by_count < 0 OR NOT isfinite(cited_by_count)'),
                              ('publication_year', f'publication_year < 1500 OR publication_year > {maximum}')]:
        if field in fields:
            results.append(zero_check(con, f'papers.{field}.range', 'curated',
                f'SELECT count(*) FROM curated.papers WHERE {condition}', f'Invalid {field} in curated.papers'))
    return results


def coverage_checks(con):
    if 'paper_id' not in columns(con, 'curated', 'papers'):
        return []
    fields = columns(con, 'curated', 'papers')
    total = con.execute('SELECT count(*) FROM curated.papers').fetchone()[0]
    conditions = {name: (f"p.{field} IS NOT NULL AND trim(CAST(p.{field} AS VARCHAR))<>''" if field in fields else 'false')
                  for name, field in [('doi','doi'),('primary_topic','primary_topic_id'),('title','title')]}
    conditions['oa_information'] = ('p.is_open_access IS NOT NULL' if 'is_open_access' in fields else 'false')
    if 'oa_status' in fields:
        conditions['oa_information'] += " OR (p.oa_status IS NOT NULL AND trim(p.oa_status) NOT IN ('','unknown'))"
    for name, bridge in [('authors','paper_authors'),('institutions','paper_institutions')]:
        conditions[name] = (f'EXISTS (SELECT 1 FROM curated.{bridge} b WHERE b.paper_id=p.paper_id)'
                            if 'paper_id' in columns(con, 'curated', bridge) else 'false')
    results = []
    for name, condition in conditions.items():
        count = con.execute(f'SELECT count(*) FROM curated.papers p WHERE {condition}').fetchone()[0]
        percent = round(100 * count / total, 2) if total else None
        results.append(outcome(f'coverage.{name}', 'coverage', percent, bool(total) and count == total,
            'informational percentage; optional field, no failure threshold', f'{count} of {total} papers', warning=True))
    years = con.execute('SELECT count(DISTINCT publication_year) FROM curated.papers').fetchone()[0] if 'publication_year' in fields else 0
    results.append(outcome('coverage.publication_years', 'coverage', years, years >= 2,
        'at least two years for temporal analysis', 'Bounded samples do not establish global coverage', warning=True))
    return results


def analytics_checks(con):
    from src.transform.analytics import VIEW_NAMES, validate_analytics, AnalyticsError
    results, views = [], []
    fields = columns(con, 'curated', 'papers')
    optional = {'publication_trends':'publication_year', 'topic_yearly_trends':'publication_year', 'open_access_summary':'oa_status'}
    for view in VIEW_NAMES:
        available = columns(con, 'analytics', view)
        if not available:
            results.append(outcome(f'{view}.queryable','analytics','missing',False,'queryable view',
                'Optional view may be absent when source fields are unavailable', warning=view in optional and optional[view] not in fields))
            continue
        try:
            con.execute(f'SELECT * FROM analytics.{view} LIMIT 1').fetchall()
            check = outcome(f'{view}.queryable','analytics','queryable',True,'queryable view')
        except duckdb.Error:
            check = outcome(f'{view}.queryable','analytics','unavailable',False,'queryable view','View query failed')
        results.append(check)
        views.append(view)
        if view == 'overview_kpis':
            results.append(zero_check(con,'overview_kpis.single_row','analytics',
                'SELECT abs(count(*)-1) FROM analytics.overview_kpis','Exactly one overview row'))
        for field in sorted(available):
            if 'citations' in field or field == 'cited_by_count':
                results.append(zero_check(con, f'{view}.{field}.nonnegative','analytics',
                    f'SELECT count(*) FROM analytics.{view} WHERE {field}<0 OR NOT isfinite({field})', 'Citation metrics must be finite and nonnegative when known'))
        key = {'author_summary':'author_id','institution_summary':'institution_id','topic_summary':'topic_id','top_papers':'paper_id'}.get(view)
        if key:
            results.append(zero_check(con, f'{view}.unique','analytics',
                f'SELECT count(*) FROM (SELECT {key} FROM analytics.{view} GROUP BY {key} HAVING count(*)>1)', 'One row per entity'))
    try:
        validate_analytics(con, views)
        results.append(outcome('analytics.reconciliation', 'analytics', 0, True,
            'KPI totals, percentage ranges, yearly counts, distinct bridge grain and citation ranking reconcile'))
    except (AnalyticsError, duckdb.Error, TypeError, IndexError, KeyError):
        results.append(outcome('analytics.reconciliation', 'analytics', 'invalid', False,
            'KPI totals, percentage ranges, yearly counts, distinct bridge grain and citation ranking reconcile',
            'Existing Stage 5 validator rejected the metrics or schema'))
    return results


def raw_checks(path, metadata_path=None):
    results = []
    try:
        count = sum(1 for _ in read_jsonl(path))
        results.append(outcome('raw.identity_json','raw',count,True,'valid JSON objects with nonblank string Work id'))
    except (ValueError, OSError, UnicodeError):
        return [outcome('raw.identity_json','raw','invalid',False,'valid JSON objects with nonblank string Work id',
                        'Malformed/unreadable input or missing Work id')], 0
    results.append(outcome('raw.nonempty','raw',count,count>0,'at least one record'))
    if metadata_path is None or not metadata_path.is_file():
        results.append(outcome('raw.metadata','raw','absent',False,'optional extraction provenance',warning=True))
        return results, count
    try:
        metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        if not isinstance(metadata, dict):
            raise ValueError()
    except (ValueError, OSError, UnicodeError):
        results.append(outcome('raw.metadata','raw','invalid',False,'valid metadata object'))
        return results, count
    valid = True
    for field in ('actual_record_count','records_extracted','source_match_count','requested_max_records','max_records_requested'):
        value = metadata.get(field)
        if value is None:
            continue
        sensible = type(value) is int and value >= 0
        if field in ('actual_record_count','records_extracted'):
            sensible = sensible and value == count
        else:
            sensible = sensible and value >= count
        valid = valid and sensible
        results.append(outcome(f'raw.{field}','raw', value if type(value) is int else 'invalid type',sensible,
            'count matches records; source/cap counts are nonnegative and >= extracted records'))
    complete = metadata.get('is_complete_extraction')
    if complete is not None:
        source = metadata.get('source_match_count')
        good = type(complete) is bool and (not complete or (valid and type(source) is int and source == count))
        results.append(outcome('raw.completeness','raw',complete if type(complete) is bool else 'invalid type',good,
            'complete=true requires a known matching source count'))
    return results, count
