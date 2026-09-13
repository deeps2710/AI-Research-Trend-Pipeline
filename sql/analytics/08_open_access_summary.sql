-- requires papers.oa_status
CREATE OR REPLACE VIEW analytics.open_access_summary AS
SELECT coalesce(nullif(trim(oa_status), ''), 'unknown') AS oa_status,
    count(*) AS paper_count,
    100.0 * count(*) / nullif(sum(count(*)) OVER (), 0) AS percentage_of_papers
FROM curated.papers
GROUP BY coalesce(nullif(trim(oa_status), ''), 'unknown');
