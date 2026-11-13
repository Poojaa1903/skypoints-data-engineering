USE DATABASE SKYPOINTS;

--1. Refresh the repo

SHOW GIT REPOSITORIES;

ALTER GIT REPOSITORY SKYPOINTS.PUBLIC."skypoints-data-engineering" FETCH;

DROP TABLE IF EXISTS bronze.pipeline_config;

--2. Create the tables and the job (one time job)

EXECUTE IMMEDIATE FROM @SKYPOINTS.PUBLIC."skypoints-data-engineering"/branches/dev/bronze/bronze_ddl.sql;
EXECUTE IMMEDIATE FROM @SKYPOINTS.PUBLIC."skypoints-data-engineering"/branches/dev/bronze/schema_audit.sql;
EXECUTE IMMEDIATE FROM @SKYPOINTS.PUBLIC."skypoints-data-engineering"/branches/dev/silver/silver_ddl.sql;
EXECUTE IMMEDIATE FROM @SKYPOINTS.PUBLIC."skypoints-data-engineering"/branches/dev/silver/member_typed.sql;
EXECUTE IMMEDIATE FROM @SKYPOINTS.PUBLIC."skypoints-data-engineering"/branches/dev/gold/gold_ddl.sql;
EXECUTE IMMEDIATE FROM @SKYPOINTS.PUBLIC."skypoints-data-engineering"/branches/dev/setup/stage_and_formats.sql;
EXECUTE IMMEDIATE FROM @SKYPOINTS.PUBLIC."skypoints-data-engineering"/branches/dev/setup/load_config.sql;

CALL bronze.load_config();

EXECUTE IMMEDIATE FROM @SKYPOINTS.PUBLIC."skypoints-data-engineering"/branches/dev/setup/load_reference.sql;
EXECUTE IMMEDIATE FROM @SKYPOINTS.PUBLIC."skypoints-data-engineering"/branches/dev/bronze/load_day.sql;
EXECUTE IMMEDIATE FROM @SKYPOINTS.PUBLIC."skypoints-data-engineering"/branches/dev/silver/silver_load.sql;
EXECUTE IMMEDIATE FROM @SKYPOINTS.PUBLIC."skypoints-data-engineering"/branches/dev/silver/quality_gate.sql;
EXECUTE IMMEDIATE FROM @SKYPOINTS.PUBLIC."skypoints-data-engineering"/branches/dev/gold/latest_and_split.sql;
EXECUTE IMMEDIATE FROM @SKYPOINTS.PUBLIC."skypoints-data-engineering"/branches/dev/gold/redemptions.sql;
EXECUTE IMMEDIATE FROM @SKYPOINTS.PUBLIC."skypoints-data-engineering"/branches/dev/run_pipeline.sql;

--3. Copy the sample files out of Git into the stage

COPY FILES INTO @SKYPOINTS.BRONZE.skypoints_stage/reference/
  FROM @SKYPOINTS.PUBLIC."skypoints-data-engineering"/branches/dev/config/
  FILES = ('iso_countries.csv', 'country_aliases.csv');

COPY FILES INTO @SKYPOINTS.BRONZE.skypoints_stage/members_flat/2024-01-15/
  FROM @SKYPOINTS.PUBLIC."skypoints-data-engineering"/branches/dev/data/
  FILES = ('members_20240115.txt');

COPY FILES INTO @SKYPOINTS.BRONZE.skypoints_stage/redemptions/2024-01-15/
  FROM @SKYPOINTS.PUBLIC."skypoints-data-engineering"/branches/dev/data/
  FILES = ('redemptions_20240115.json');

COPY FILES INTO @SKYPOINTS.BRONZE.skypoints_stage/country_xlsx/2024-01-15/
  FROM @SKYPOINTS.PUBLIC."skypoints-data-engineering"/branches/dev/seed/
  FILES = ('country_extract_20240115.csv');


CALL bronze.run_pipeline(DATE '2024-01-15');

SELECT country_code, COUNT(*)
FROM gold.member
WHERE load_date = DATE '2024-01-15'
GROUP BY 1 ORDER BY 1;

