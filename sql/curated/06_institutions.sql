CREATE OR REPLACE TABLE curated.institutions AS
SELECT i.id AS institution_id{{institutions}}
FROM i
JOIN a ON i._dlt_parent_id = a._dlt_id
JOIN w ON a._dlt_parent_id = w._dlt_id
WHERE i.id IS NOT NULL AND trim(i.id) <> ''
QUALIFY row_number() OVER (PARTITION BY i.id ORDER BY w.id, a._dlt_id, to_json(i)) = 1;
