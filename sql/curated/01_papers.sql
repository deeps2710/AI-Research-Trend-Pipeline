-- One row per Work. Duplicate/null Work keys fail quality checks.
CREATE OR REPLACE TABLE curated.papers AS
SELECT w.id AS paper_id{{papers}}
FROM w;
