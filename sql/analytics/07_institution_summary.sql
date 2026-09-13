-- Full counting per distinct paper/institution, independent of authorship count.
CREATE OR REPLACE VIEW analytics.institution_summary AS
WITH totals AS (
    SELECT b.institution_id, count(DISTINCT p.paper_id) AS paper_count
-- if papers.cited_by_count
        , sum(p.cited_by_count) AS total_citations
        , avg(p.cited_by_count) AS average_citations
-- endif
    FROM (SELECT DISTINCT paper_id, institution_id FROM curated.paper_institutions) b
    JOIN curated.papers p ON p.paper_id = b.paper_id
    GROUP BY b.institution_id
)
SELECT totals.*
-- if institutions.institution_name
    , i.institution_name
-- endif
-- if institutions.country_code
    , i.country_code
-- endif
-- if institutions.institution_type
    , i.institution_type
-- endif
FROM totals JOIN curated.institutions i ON i.institution_id = totals.institution_id;
