-- Deterministic representative for conflicting labels: earliest Work ID.
CREATE OR REPLACE TABLE curated.topics AS
SELECT t.id AS topic_id{{topics}}
FROM t
JOIN w ON t._dlt_parent_id = w._dlt_id
WHERE t.id IS NOT NULL AND trim(t.id) <> ''
QUALIFY row_number() OVER (PARTITION BY t.id ORDER BY w.id, to_json(t)) = 1;
