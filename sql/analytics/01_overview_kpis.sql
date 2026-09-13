CREATE OR REPLACE VIEW analytics.overview_kpis AS
SELECT count(*) AS total_papers
-- if papers.cited_by_count
    , sum(cited_by_count) AS total_citations
    , avg(cited_by_count) AS average_citations_per_paper
    , median(cited_by_count) AS median_citations_per_paper
-- endif
-- if papers.is_open_access
    , count(*) FILTER (WHERE is_open_access IS TRUE) AS open_access_papers
    , 100.0 * count(*) FILTER (WHERE is_open_access IS TRUE)
        / nullif(count(*), 0) AS open_access_percentage
-- endif
    , (SELECT count(*) FROM curated.authors) AS unique_authors
    , (SELECT count(*) FROM curated.topics) AS unique_topics
    , (SELECT count(*) FROM curated.institutions) AS unique_institutions
-- if papers.publication_year
    , min(publication_year) AS earliest_publication_year
    , max(publication_year) AS latest_publication_year
-- endif
FROM curated.papers;
