-- Gold: one member row per person, then one view per country.
-- Dialect: Snowflake.
--
-- Why one table plus views, not one physical table per country:
-- a new country is a new view, not a code change, and a billion-row day
-- is one clustered table instead of a rewrite of every country table.
-- The views are what a developer queries (Table_USA, Table_IND, ...).

CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE IF NOT EXISTS gold.member (
    member_key         VARCHAR       NOT NULL,  -- name|dob when both exist, else scope:member_id
    member_id          VARCHAR       NOT NULL,  -- text, unique inside one source file only
    source_file        VARCHAR       NOT NULL,
    source_scope       VARCHAR       NOT NULL,  -- FLAT, or the xlsx country (AUS, IND, USA)
    member_name        VARCHAR,
    tier_code          VARCHAR,
    country_code       VARCHAR       NOT NULL,  -- ISO-3, or the raw code when UNMAPPED
    country_status     VARCHAR       NOT NULL,  -- MAPPED / ALIAS / UNMAPPED
    enrollment_date    DATE,
    last_flight_date   DATE,
    dob                DATE,
    age                NUMBER,
    is_stale_member    BOOLEAN       NOT NULL,
    load_date          DATE          NOT NULL,  -- the file date; also the folder name
    created_at         TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
    created_by         VARCHAR       DEFAULT CURRENT_USER(),
    modified_at        TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY (load_date, country_code);

-- Country tables the brief asks for. Each is a view over gold.member.
-- A country that shows up later gets the same view, created from its code.
CREATE OR REPLACE VIEW gold.table_usa AS SELECT * FROM gold.member WHERE country_code = 'USA';
CREATE OR REPLACE VIEW gold.table_ind AS SELECT * FROM gold.member WHERE country_code = 'IND';
CREATE OR REPLACE VIEW gold.table_aus AS SELECT * FROM gold.member WHERE country_code = 'AUS';
CREATE OR REPLACE VIEW gold.table_phl AS SELECT * FROM gold.member WHERE country_code = 'PHL';
CREATE OR REPLACE VIEW gold.table_can AS SELECT * FROM gold.member WHERE country_code = 'CAN';

-- One row per redemption, after flatten and dedupe. Orphans have no country.
CREATE TABLE IF NOT EXISTS gold.redemption (
    member_id          VARCHAR,
    feed_date          DATE,
    txn_id             VARCHAR       NOT NULL,
    txn_date           DATE,
    partner            VARCHAR,
    miles_redeemed     NUMBER,
    status             VARCHAR,
    country_code       VARCHAR,                 -- NULL when the member is not in gold yet
    match_status       VARCHAR       NOT NULL,  -- MATCHED / ORPHAN
    created_at         TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
    created_by         VARCHAR       DEFAULT CURRENT_USER(),
    modified_at        TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY (txn_date);
