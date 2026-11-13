-- Stage and file formats for the Snowflake pipeline.
-- Dialect: Snowflake. Run once after the bronze / silver / gold DDL files.
--
-- Files are uploaded with SnowSQL PUT into dated prefixes that match
-- the local bronze layout:
--   @skypoints_stage/members_flat/2024-01-15/members_20240115.txt
--   @skypoints_stage/redemptions/2024-01-15/redemptions_20240115.json
--   @skypoints_stage/country_xlsx/2024-01-15/country_extract_20240115.csv
--   @skypoints_stage/reference/iso_countries.csv
--   @skypoints_stage/reference/country_aliases.csv
--
-- Snowflake COPY does not read .xlsx. The country seed CSV is the same
-- text shape local bronze/ingest.py produces from AUS.xlsx, IND.xlsx and
-- USA.xlsx. In production an ingest job or Snowpark step would write
-- that CSV (or land rows directly) before this load.

CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;

CREATE OR REPLACE STAGE bronze.skypoints_stage
    COMMENT = 'Internal stage for SkyPoints sample and daily files';

-- Flat member file: pipe-delimited, leading "|", first header row skipped.
CREATE OR REPLACE FILE FORMAT bronze.ff_pipe
    TYPE = CSV
    FIELD_DELIMITER = '|'
    SKIP_HEADER = 1
    EMPTY_FIELD_AS_NULL = TRUE
    NULL_IF = ('')
    TRIM_SPACE = TRUE
    ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE;

-- Redemption feed: one JSON object per file.
CREATE OR REPLACE FILE FORMAT bronze.ff_json
    TYPE = JSON
    STRIP_OUTER_ARRAY = FALSE;

-- Country extract seed and reference CSVs.
CREATE OR REPLACE FILE FORMAT bronze.ff_csv
    TYPE = CSV
    FIELD_DELIMITER = ','
    SKIP_HEADER = 1
    EMPTY_FIELD_AS_NULL = TRUE
    NULL_IF = ('')
    FIELD_OPTIONALLY_ENCLOSED_BY = '"'
    TRIM_SPACE = TRUE;
