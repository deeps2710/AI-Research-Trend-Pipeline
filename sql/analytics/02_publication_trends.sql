-- requires papers.publication_year
CREATE OR REPLACE VIEW analytics.publication_trends AS
WITH yearly AS (
    SELECT publication_year, count(*) AS paper_count
-- if papers.cited_by_count
        , sum(cited_by_count) AS total_citations
        , avg(cited_by_count) AS average_citations
-- endif
    FROM curated.papers
    WHERE publication_year IS NOT NULL
    GROUP BY publication_year
), previous AS (
    SELECT *, lag(publication_year) OVER (ORDER BY publication_year) AS previous_observed_year,
        lag(paper_count) OVER (ORDER BY publication_year) AS previous_observed_count
    FROM yearly
)
SELECT publication_year, paper_count
-- if papers.cited_by_count
    , total_citations, average_citations
-- endif
    , CASE WHEN previous_observed_year = publication_year - 1
        THEN previous_observed_count END AS previous_year_paper_count
    , CASE WHEN previous_observed_year = publication_year - 1
        THEN 100.0 * (paper_count - previous_observed_count)
            / nullif(previous_observed_count, 0) END AS year_over_year_growth_percentage
FROM previous;
