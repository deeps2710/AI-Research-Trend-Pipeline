-- requires papers.publication_year
CREATE OR REPLACE VIEW analytics.topic_yearly_trends AS
WITH yearly AS (
    SELECT p.publication_year, b.topic_id, count(DISTINCT p.paper_id) AS paper_count
-- if papers.cited_by_count
        , sum(p.cited_by_count) AS total_citations
        , avg(p.cited_by_count) AS average_citations
-- endif
    FROM (SELECT DISTINCT paper_id, topic_id FROM curated.paper_topics) b
    JOIN curated.papers p ON p.paper_id = b.paper_id
    WHERE p.publication_year IS NOT NULL
    GROUP BY p.publication_year, b.topic_id
), previous AS (
    SELECT *, lag(publication_year) OVER topic_year AS previous_observed_year,
        lag(paper_count) OVER topic_year AS previous_observed_count
    FROM yearly
    WINDOW topic_year AS (PARTITION BY topic_id ORDER BY publication_year)
)
SELECT y.publication_year, y.topic_id, y.paper_count
-- if topics.topic_name
    , t.topic_name
-- endif
-- if papers.cited_by_count
    , y.total_citations, y.average_citations
-- endif
    , CASE WHEN previous_observed_year = publication_year - 1
        THEN previous_observed_count END AS previous_year_paper_count
    , CASE WHEN previous_observed_year = publication_year - 1
        THEN 100.0 * (paper_count - previous_observed_count)
            / nullif(previous_observed_count, 0) END AS year_over_year_growth_percentage
FROM previous y JOIN curated.topics t ON y.topic_id = t.topic_id;
