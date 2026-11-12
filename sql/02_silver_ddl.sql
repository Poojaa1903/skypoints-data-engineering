-- =====================================================================
-- 02_silver_ddl.sql
-- Silver = cleaned, typed, standardised members. One row per member
-- record that passed validation. Rejected rows go to the quarantine table.
-- Dialect: Snowflake.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS silver;

-- ---------------------------------------------------------------------
-- Reference: every country code seen in any feed, and its status.
-- Filled by the pipeline. A new code is inserted once, automatically.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.ref_country (
    source_code        VARCHAR       NOT NULL,   -- code as it arrived, e.g. PHIL, AU, UK
    country_code       VARCHAR,                  -- resolved 3-letter code, e.g. PHL, AUS, UK
    country_status     VARCHAR       NOT NULL,   -- MAPPED / ALIAS / UNMAPPED
    first_seen_date    DATE          NOT NULL
);

-- ---------------------------------------------------------------------
-- Member staging: typed, cleaned, with derived fields.
-- One row per member per source record. Business key is member_id.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.member_stg (
    -- lineage
    source_file          VARCHAR       NOT NULL,
    source_system        VARCHAR       NOT NULL,   -- FLAT_FILE / COUNTRY_XLSX
    source_country       VARCHAR,                  -- from the file name (xlsx) or raw Country (flat)
    row_num              NUMBER        NOT NULL,
    load_date            DATE          NOT NULL,   -- as_of date of the run
    -- business key and attributes
    member_id            VARCHAR       NOT NULL,   -- text, never INT
    member_name          VARCHAR,
    tier_code            VARCHAR,
    agent_name           VARCHAR,
    state_code           VARCHAR,
    enrollment_date      DATE,
    last_flight_date     DATE,
    dob                  DATE,
    is_active            BOOLEAN,
    -- standardised country
    country_code         VARCHAR,                  -- 3-letter, e.g. USA, AUS, PHL
    country_status       VARCHAR       NOT NULL,   -- MAPPED / ALIAS / UNMAPPED / MISSING
    -- derived
    age                  NUMBER,                   -- full years on load_date
    is_stale_member      BOOLEAN       NOT NULL    -- more than 90 days since last flight
)
CLUSTER BY (load_date);

-- ---------------------------------------------------------------------
-- Quarantine: rows that failed a mandatory or format check.
-- The rest of the file still loads. Nothing here is silently dropped.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.member_quarantine (
    source_file          VARCHAR       NOT NULL,
    row_num              NUMBER        NOT NULL,
    load_date            DATE          NOT NULL,
    reject_rule          VARCHAR       NOT NULL,   -- e.g. MEMBER_ID_MISSING, DOB_AMBIGUOUS
    reject_detail        VARCHAR,                  -- human-readable explanation
    raw_record           VARIANT                   -- the original row, unchanged
);
