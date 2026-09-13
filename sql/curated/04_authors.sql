CREATE OR REPLACE TABLE curated.authors AS
SELECT a.author__id AS author_id{{authors}}
FROM a
JOIN w ON a._dlt_parent_id = w._dlt_id
WHERE a.author__id IS NOT NULL AND trim(a.author__id) <> ''
QUALIFY row_number() OVER (PARTITION BY a.author__id ORDER BY w.id, a._dlt_id) = 1;
