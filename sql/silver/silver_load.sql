-- Load silver from the views in member_typed.sql.
-- Dialect: Snowflake. Safe to run again: each run replaces silver.
-- An empty bronze schema loads zero rows. It does not fail.
--
-- age: full years on load_date. The birthday itself counts.
-- is_stale_member: more than 90 days since the last flight.
-- Exactly 90 is not stale. No flight date is stale.

INSERT OVERWRITE INTO silver.member_stg (
    source_file, source_system, source_scope, source_country, row_num, load_date,
    member_id, member_name, tier_code, agent_name, state_code,
    enrollment_date, last_flight_date, dob, is_active,
    country_code, country_status, age, is_stale_member
)
SELECT
    source_file,
    source_system,
    source_scope,
    source_country,
    row_num,
    load_date,
    member_id,
    member_name,
    tier_code,
    agent_name,
    state_code,
    enrollment_date,
    last_flight_date,
    dob,
    is_active,
    country_code,
    country_status,
    CASE
        WHEN dob IS NULL THEN NULL
        ELSE DATEDIFF('year', dob, load_date)
             - IFF(TO_CHAR(load_date, 'MMDD') < TO_CHAR(dob, 'MMDD'), 1, 0)
    END AS age,
    IFF(
        last_flight_date IS NULL,
        TRUE,
        DATEDIFF('day', last_flight_date, load_date) > 90
    ) AS is_stale_member
FROM silver.member_typed;

INSERT OVERWRITE INTO silver.member_quarantine (
    source_file, row_num, load_date, reject_rule, reject_detail, raw_record
)
SELECT
    source_file,
    row_num,
    load_date,
    reject_rule,
    reject_rule,
    raw_record
FROM silver.member_parsed
WHERE reject_rule IS NOT NULL;
