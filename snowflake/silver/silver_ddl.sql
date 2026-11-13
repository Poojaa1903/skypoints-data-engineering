-- =====================================================================
-- silver_ddl.sql
-- Silver = cleaned, typed, standardised members. One row per member
-- record that passed validation. Rejected rows go to the quarantine table.
-- Dialect: Snowflake.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS silver;

-- config/iso_countries.csv
-- and config/country_aliases.csv. Load them before silver_load.sql
-- if you want AU -> AUS and PHIL -> PHL. An empty table does not
-- fail the load; unknown codes stay UNMAPPED.
CREATE TABLE IF NOT EXISTS silver.iso_country (
    alpha2             VARCHAR,
    alpha3             VARCHAR,
    country_name       VARCHAR
);

CREATE TABLE IF NOT EXISTS silver.country_alias (
    source_code        VARCHAR,
    alpha3             VARCHAR
);

-- ---------------------------------------------------------------------
-- Reference: every country code seen in any feed, and its status.
-- Filled by the pipeline. A new code is inserted once, automatically.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.ref_country (
    source_code        VARCHAR       NOT NULL,   -- code as it arrived, e.g. PHIL, AU, UK
    country_code       VARCHAR,                  -- resolved 3-letter code, e.g. PHL, AUS, UK
    country_status     VARCHAR       NOT NULL,   -- MAPPED / ALIAS / UNMAPPED
    first_seen_date    DATE          NOT NULL,
    created_at         TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
    created_by         VARCHAR       DEFAULT CURRENT_USER(),
    modified_at        TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
);

-- ---------------------------------------------------------------------
-- Member staging: typed, cleaned, with derived fields.
-- One row per source record that passed validation.
-- member_id is unique inside one file only. Across files, a person is
-- name + date of birth (see snowflake/gold/latest_and_split.sql).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.member_stg (
    -- lineage
    source_file          VARCHAR       NOT NULL,
    source_system        VARCHAR       NOT NULL,   -- FLAT_FILE / COUNTRY_XLSX
    source_scope         VARCHAR       NOT NULL,   -- FLAT, or the xlsx country. Part of the person key.
    source_country       VARCHAR,                  -- raw country text, before ISO mapping
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
    is_stale_member      BOOLEAN       NOT NULL,   -- more than 90 days since last flight
    created_at           TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
    created_by           VARCHAR       DEFAULT CURRENT_USER(),
    modified_at          TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
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
    raw_record           VARIANT,                  -- the original row, unchanged
    created_at           TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
    created_by           VARCHAR       DEFAULT CURRENT_USER(),
    modified_at          TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Dataset checks for one day. A FAIL stops gold.
CREATE TABLE IF NOT EXISTS silver.quality_report (
    load_date            DATE          NOT NULL,
    check_name           VARCHAR       NOT NULL,
    status               VARCHAR       NOT NULL,   -- PASS / WARN / FAIL
    value                VARCHAR,
    threshold            VARCHAR,
    detail               VARCHAR,
    created_at           TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
    created_by           VARCHAR       DEFAULT CURRENT_USER(),
    modified_at          TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY (load_date);
