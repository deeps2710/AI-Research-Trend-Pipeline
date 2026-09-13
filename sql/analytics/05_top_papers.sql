CREATE OR REPLACE VIEW analytics.top_papers AS
SELECT paper_id
-- if papers.title
    , title
-- endif
-- if papers.doi
    , doi
-- endif
-- if papers.publication_year
    , publication_year
-- endif
-- if papers.cited_by_count
    , cited_by_count
    , row_number() OVER (ORDER BY cited_by_count DESC NULLS LAST, paper_id) AS citation_rank
-- endif
-- if papers.primary_topic_name
    , primary_topic_name
-- endif
-- if papers.is_open_access
    , is_open_access
-- endif
-- if papers.oa_status
    , oa_status
-- endif
-- if papers.cited_by_count papers.publication_year
    , year(current_date) AS citation_reference_year
    , CASE WHEN publication_year <= year(current_date)
        THEN cited_by_count * 1.0 / greatest(1, year(current_date) - publication_year + 1)
        END AS citations_per_year_since_publication
-- endif
FROM curated.papers;
