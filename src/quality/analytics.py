"""Analytical checks depend on builders without a curated-check import cycle."""
import duckdb
from src.transform.schema import columns
from src.quality.checks import outcome, zero_check


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
