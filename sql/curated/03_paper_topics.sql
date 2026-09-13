CREATE OR REPLACE TABLE curated.paper_topics AS
SELECT w.id AS paper_id, t.id AS topic_id{{topic_attributes}}
FROM t
JOIN w ON t._dlt_parent_id = w._dlt_id
WHERE t.id IS NOT NULL AND trim(t.id) <> ''
GROUP BY w.id, t.id;
