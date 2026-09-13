-- Multiple affiliated authors still produce only one paper/institution pair.
CREATE OR REPLACE TABLE curated.paper_institutions AS
SELECT DISTINCT w.id AS paper_id, i.id AS institution_id
FROM i
JOIN a ON i._dlt_parent_id = a._dlt_id
JOIN w ON a._dlt_parent_id = w._dlt_id
WHERE i.id IS NOT NULL AND trim(i.id) <> '';
