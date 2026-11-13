-- =====================================================================
-- bronze_ddl.sql
-- Bronze = landing zone. Data is stored exactly as it arrived.
-- Rules:
--   * Every business column is VARCHAR. Nothing is cast here, so
--     leading zeros (DOB 03051985, IDs like 2256) are never lost.
--   * Every table carries audit columns so any row can be traced
--     back to its file and load run.
--   * Nothing is updated or deleted in bronze. Fixes happen in silver.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS bronze;

-- ---------------------------------------------------------------------
-- 1. Flat member file (pipe-delimited, H and D records)
--    Columns follow the layout in the brief. Post Code is not in the
--    sample, so it is not here.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze.member_flat_raw (
    -- audit
    source_file        VARCHAR       NOT NULL,   -- e.g. members_20240115.txt
    load_ts            TIMESTAMP_NTZ NOT NULL,   -- when this row was loaded
    load_date          DATE          NOT NULL,   -- partition / cluster key
    row_num            NUMBER        NOT NULL,   -- line number in the file
    -- record
    record_type        VARCHAR,                  -- 'H' header or 'D' detail
    member_name        VARCHAR,                  -- 255
    member_id          VARCHAR,                  -- 18, text, never INT
    enrollment_date    VARCHAR,                  -- 8, YYYYMMDD expected
    last_flight_date   VARCHAR,                  -- 8, optional
    tier_code          VARCHAR,                  -- 5
    agent_name         VARCHAR,                  -- 255, optional
    state              VARCHAR,                  -- 5
    country            VARCHAR,                  -- 5, raw code, not mapped yet
    dob                VARCHAR,                  -- 8, format checked in silver
    is_active          VARCHAR,                  -- 1
    created_at         TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
    created_by         VARCHAR       DEFAULT CURRENT_USER(),
    modified_at        TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY (load_date);

-- ---------------------------------------------------------------------
-- 2. Country extracts (AUS.xlsx, IND.xlsx, USA.xlsx)
--    Each country names and orders its columns differently. The loader
--    maps source columns to these names using config/source_mappings.yaml,
--    so one table holds all countries. A column a country does not send
--    is left NULL (for example USA has no DOB).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze.country_extract_raw (
    -- audit
    source_file            VARCHAR       NOT NULL,  -- e.g. AUS.xlsx
    source_country         VARCHAR       NOT NULL,  -- AUS / IND / USA, from the file name
    load_ts                TIMESTAMP_NTZ NOT NULL,
    load_date              DATE          NOT NULL,
    row_num                NUMBER        NOT NULL,  -- row number in the sheet
    -- record (mapped to canonical names)
    source_member_id       VARCHAR,                 -- AUS "Unique ID", IND "ID", USA "ID"
    member_name           VARCHAR,
    tier_code              VARCHAR,                 -- AUS "Tier Type", IND "TierCode", USA "TierCode"
    dob_raw                VARCHAR,                 -- Excel serial, text, or NULL (AUS has "NULL")
    enrollment_date_raw    VARCHAR,                 -- Excel serial, MMDDYYYY, or text
    flight_date_raw        VARCHAR,                 -- Excel serial, MMDDYYYY, or text
    individual_or_corp     VARCHAR,                 -- IND only: 'I' or 'C'
    created_at             TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
    created_by             VARCHAR       DEFAULT CURRENT_USER(),
    modified_at            TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY (load_date);

-- ---------------------------------------------------------------------
-- 3. Redemption feed (JSON, one object per member per day)
--    The whole JSON object is kept in one VARIANT column. Flattening
--    happens in silver, so a change in the JSON shape never breaks load.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze.redemption_raw (
    -- audit
    source_file        VARCHAR       NOT NULL,   -- e.g. redemptions_20240115.json
    load_ts            TIMESTAMP_NTZ NOT NULL,
    load_date          DATE          NOT NULL,
    row_num            NUMBER        NOT NULL,   -- object number in the file
    -- record
    member_id          VARCHAR,                  -- read from the JSON as text
    feed_date          VARCHAR,                  -- YYYYMMDD, text
    payload            VARIANT       NOT NULL,   -- the full JSON object, unchanged
    created_at         TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
    created_by         VARCHAR       DEFAULT CURRENT_USER(),
    modified_at        TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY (load_date);

-- ---------------------------------------------------------------------
-- 4. Load audit: one row per load attempt of a file.
--    Used to skip files already loaded successfully (idempotent reruns).
--    No primary key on purpose: a failed file is retried and gets a new
--    row. Snowflake does not enforce keys anyway, so the pipeline checks
--    for status = 'LOADED' before loading.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze.load_audit (
    source_file        VARCHAR       NOT NULL,
    feed_type          VARCHAR       NOT NULL,   -- MEMBER_FLAT / COUNTRY_XLSX / REDEMPTION_JSON
    load_ts            TIMESTAMP_NTZ NOT NULL,
    row_count          NUMBER,
    rejected_count     NUMBER,
    status             VARCHAR       NOT NULL,   -- STARTED / LOADED / FAILED
    created_at         TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
    created_by         VARCHAR       DEFAULT CURRENT_USER(),
    modified_at        TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Staging tables used by bronze.load_day while COPY INTO runs.
-- Truncated at the start of each load. Not part of the lasting bronze store.
CREATE TABLE IF NOT EXISTS bronze.flat_landing (
    empty_col          VARCHAR,
    record_type        VARCHAR,
    member_name        VARCHAR,
    member_id          VARCHAR,
    enrollment_date    VARCHAR,
    last_flight_date   VARCHAR,
    tier_code          VARCHAR,
    agent_name         VARCHAR,
    state              VARCHAR,
    country            VARCHAR,
    dob                VARCHAR,
    is_active          VARCHAR
);

CREATE TABLE IF NOT EXISTS bronze.country_landing (
    source_file            VARCHAR,
    source_country         VARCHAR,
    row_num                NUMBER,
    source_member_id       VARCHAR,
    member_name            VARCHAR,
    tier_code              VARCHAR,
    dob_raw                VARCHAR,
    enrollment_date_raw    VARCHAR,
    flight_date_raw        VARCHAR,
    individual_or_corp     VARCHAR
);

CREATE TABLE IF NOT EXISTS bronze.redemption_landing (
    payload VARIANT
);
