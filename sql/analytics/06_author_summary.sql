-- Full counting: every identified author receives the paper's full citations.
CREATE OR REPLACE VIEW analytics.author_summary AS
WITH totals AS (
    SELECT b.author_id, count(DISTINCT p.paper_id) AS paper_count
-- if papers.cited_by_count
        , sum(p.cited_by_count) AS total_citations_of_authored_papers
        , avg(p.cited_by_count) AS average_citations_per_paper
-- endif
-- if papers.is_open_access
        , count(*) FILTER (WHERE p.is_open_access IS TRUE) AS open_access_papers
        , 100.0 * count(*) FILTER (WHERE p.is_open_access IS TRUE)
            / nullif(count(*), 0) AS open_access_percentage
-- endif
    FROM (SELECT DISTINCT paper_id, author_id FROM curated.paper_authors) b
    JOIN curated.papers p ON p.paper_id = b.paper_id
    GROUP BY b.author_id
)
SELECT totals.*
-- if authors.author_name
    , a.author_name
-- endif
FROM totals JOIN curated.authors a ON a.author_id = totals.author_id;
