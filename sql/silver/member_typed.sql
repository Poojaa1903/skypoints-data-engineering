-- Typed member rows, built from bronze. Both engines read this shape.
-- Snowflake runs this file as written.
-- Locally, make run does the same rules in Python; it does not execute
-- this file. tests/gold/test_sql_rules.py checks the shared expressions.
--
-- member_parsed is every detail row, with a reject_rule when it fails.
-- member_typed is only the rows that passed. silver_load.sql reads both.

CREATE OR REPLACE VIEW silver.member_parsed AS
WITH flat AS (
    SELECT
        source_file,
        'FLAT_FILE' AS source_system,
        'FLAT' AS source_scope,
        country AS source_country,
        row_num,
        load_date,
        member_id,
        member_name,
        tier_code,
        agent_name,
        state AS state_code,
        TRY_TO_DATE(NULLIF(NULLIF(TRIM(enrollment_date), ''), 'NULL'), 'YYYYMMDD') AS enrollment_date,
        TRY_TO_DATE(NULLIF(NULLIF(TRIM(last_flight_date), ''), 'NULL'), 'YYYYMMDD') AS last_flight_date,
        TRY_TO_DATE(NULLIF(NULLIF(TRIM(dob), ''), 'NULL'), 'MMDDYYYY') AS dob,
        IFF(UPPER(TRIM(is_active)) = 'A', TRUE, FALSE) AS is_active,
        OBJECT_CONSTRUCT(*) AS raw_record
    FROM bronze.member_flat_raw
    WHERE record_type = 'D'
),
xlsx AS (
    SELECT
        source_file,
        'COUNTRY_XLSX' AS source_system,
        source_country AS source_scope,
        source_country,
        row_num,
        load_date,
        source_member_id AS member_id,
        member_name,
        tier_code,
        NULL AS agent_name,
        NULL AS state_code,
        CASE
            WHEN source_country = 'USA'
                THEN TRY_TO_DATE(NULLIF(NULLIF(TRIM(enrollment_date_raw), ''), 'NULL'), 'MMDDYYYY')
            ELSE DATEADD('day', TRY_TO_NUMBER(NULLIF(NULLIF(TRIM(enrollment_date_raw), ''), 'NULL')), DATE '1899-12-30')
        END AS enrollment_date,
        CASE
            WHEN source_country = 'USA'
                THEN TRY_TO_DATE(NULLIF(NULLIF(TRIM(flight_date_raw), ''), 'NULL'), 'MMDDYYYY')
            ELSE DATEADD('day', TRY_TO_NUMBER(NULLIF(NULLIF(TRIM(flight_date_raw), ''), 'NULL')), DATE '1899-12-30')
        END AS last_flight_date,
        CASE
            WHEN source_country = 'USA'
                THEN TRY_TO_DATE(NULLIF(NULLIF(TRIM(dob_raw), ''), 'NULL'), 'MMDDYYYY')
            WHEN NULLIF(NULLIF(TRIM(dob_raw), ''), 'NULL') IS NULL THEN NULL
            ELSE DATEADD('day', TRY_TO_NUMBER(dob_raw), DATE '1899-12-30')
        END AS dob,
        TRUE AS is_active,
        OBJECT_CONSTRUCT(*) AS raw_record
    FROM bronze.country_extract_raw
),
combined AS (
    SELECT * FROM flat
    UNION ALL
    SELECT * FROM xlsx
),
resolved AS (
    SELECT
        c.*,
        COALESCE(iso3.alpha3, iso2.alpha3, alias.alpha3, NULLIF(UPPER(TRIM(c.source_country)), '')) AS country_code,
        CASE
            WHEN NULLIF(TRIM(c.source_country), '') IS NULL THEN 'MISSING'
            WHEN iso3.alpha3 IS NOT NULL OR iso2.alpha3 IS NOT NULL THEN 'MAPPED'
            WHEN alias.alpha3 IS NOT NULL THEN 'ALIAS'
            ELSE 'UNMAPPED'
        END AS country_status
    FROM combined c
    LEFT JOIN silver.iso_country iso3
        ON iso3.alpha3 = UPPER(TRIM(c.source_country))
    LEFT JOIN silver.iso_country iso2
        ON iso2.alpha2 = UPPER(TRIM(c.source_country))
    LEFT JOIN silver.country_alias alias
        ON alias.source_code = UPPER(TRIM(c.source_country))
)
SELECT
    source_file, source_system, source_scope, source_country, row_num, load_date,
    member_id, member_name, tier_code, agent_name, state_code,
    enrollment_date, last_flight_date, dob, is_active,
    country_code, country_status, raw_record,
    CASE
        WHEN member_id IS NULL OR TRIM(member_id) = '' THEN 'MEMBER_ID_MISSING'
        WHEN member_name IS NULL OR TRIM(member_name) = '' THEN 'MEMBER_NAME_MISSING'
        WHEN country_status = 'MISSING' THEN 'COUNTRY_MISSING'
        WHEN enrollment_date IS NULL THEN 'ENROLLMENT_DATE_INVALID'
        ELSE NULL
    END AS reject_rule
FROM resolved;

CREATE OR REPLACE VIEW silver.member_typed AS
SELECT
    source_file, source_system, source_scope, source_country, row_num, load_date,
    member_id, member_name, tier_code, agent_name, state_code,
    enrollment_date, last_flight_date, dob, is_active,
    country_code, country_status
FROM silver.member_parsed
WHERE reject_rule IS NULL;
