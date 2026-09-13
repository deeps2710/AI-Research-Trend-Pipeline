-- Only the topic bridge participates: authors/institutions cannot multiply citations.
CREATE OR REPLACE VIEW analytics.topic_summary AS
WITH totals AS (
    SELECT b.topic_id, count(DISTINCT p.paper_id) AS paper_count
-- if papers.cited_by_count
        , sum(p.cited_by_count) AS total_citations
        , avg(p.cited_by_count) AS average_citations
        , median(p.cited_by_count) AS median_citations
-- endif
-- if papers.is_open_access
        , 100.0 * count(*) FILTER (WHERE p.is_open_access IS TRUE)
            / nullif(count(*), 0) AS open_access_percentage
-- endif
    FROM (SELECT DISTINCT paper_id, topic_id FROM curated.paper_topics) b
    JOIN curated.papers p ON p.paper_id = b.paper_id
    GROUP BY b.topic_id
)
SELECT totals.*
-- if topics.topic_name
    , t.topic_name
-- endif
FROM totals JOIN curated.topics t ON t.topic_id = totals.topic_id;
