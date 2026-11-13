-- Load silver for one day from the views in member_typed.sql.
-- Dialect: Snowflake. Safe to run again for the same day.
--
-- age: full years on load_date. The birthday itself counts.
-- is_stale_member: more than 90 days since the last flight.
-- Exactly 90 is not stale. No flight date is stale.
--
-- CALL silver.load_day(DATE '2024-01-15');

CREATE OR REPLACE PROCEDURE silver.load_day(AS_OF DATE)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
    loaded_count NUMBER;
    rejected_count NUMBER;
BEGIN
    DELETE FROM silver.member_stg WHERE load_date = :AS_OF;
    DELETE FROM silver.member_quarantine WHERE load_date = :AS_OF;

    INSERT INTO silver.member_stg (
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
    FROM silver.member_typed
    WHERE load_date = :AS_OF;

    INSERT INTO silver.member_quarantine (
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
    WHERE reject_rule IS NOT NULL
      AND load_date = :AS_OF;

    -- Register every country code seen on this day.
    MERGE INTO silver.ref_country t
    USING (
        SELECT DISTINCT
            UPPER(TRIM(source_country)) AS source_code,
            country_code,
            country_status,
            load_date AS first_seen_date
        FROM silver.member_stg
        WHERE load_date = :AS_OF
          AND source_country IS NOT NULL
          AND TRIM(source_country) <> ''
    ) s
    ON t.source_code = s.source_code
    WHEN NOT MATCHED THEN
        INSERT (source_code, country_code, country_status, first_seen_date)
        VALUES (s.source_code, s.country_code, s.country_status, s.first_seen_date);

    loaded_count := (SELECT COUNT(*) FROM silver.member_stg WHERE load_date = :AS_OF);
    rejected_count := (SELECT COUNT(*) FROM silver.member_quarantine WHERE load_date = :AS_OF);

    RETURN 'SILVER loaded=' || :loaded_count || ' quarantined=' || :rejected_count;
END;
$$;
