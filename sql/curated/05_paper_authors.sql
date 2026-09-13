CREATE OR REPLACE TABLE curated.paper_authors AS
SELECT w.id AS paper_id, a.author__id AS author_id{{author_attributes}}
FROM a
JOIN w ON a._dlt_parent_id = w._dlt_id
WHERE a.author__id IS NOT NULL AND trim(a.author__id) <> ''
QUALIFY row_number() OVER (PARTITION BY w.id, a.author__id ORDER BY a._dlt_id) = 1;
