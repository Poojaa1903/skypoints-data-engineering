-- Latest record wins, then load gold.member for one day.
-- Dialect: Snowflake.
--
-- A person is the same across files only when name and date of birth match.
-- Otherwise the id is scoped to its file, so AUS id 1 is not USA id 1.
-- Ranking: latest flight date (enrollment date if the flight is missing),
-- then later file date, then higher row number.
--
-- CALL gold.load_members(DATE '2024-01-15');

CREATE OR REPLACE PROCEDURE gold.load_members(AS_OF DATE)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
    member_count NUMBER;
BEGIN
    DELETE FROM gold.member WHERE load_date = :AS_OF;

    INSERT INTO gold.member (
        member_key, member_id, source_file, source_scope, member_name, tier_code,
        country_code, country_status, enrollment_date, last_flight_date, dob,
        age, is_stale_member, load_date
    )
    SELECT
        member_key, member_id, source_file, source_scope, member_name, tier_code,
        country_code, country_status, enrollment_date, last_flight_date, dob,
        age, is_stale_member, load_date
    FROM (
        SELECT
            CASE
                WHEN dob IS NOT NULL
                    THEN UPPER(TRIM(member_name)) || '|' || TO_CHAR(dob, 'YYYY-MM-DD')
                ELSE source_scope || ':' || member_id
            END AS member_key,
            member_id, source_file, source_scope, member_name, tier_code,
            country_code, country_status, enrollment_date, last_flight_date, dob,
            age, is_stale_member, load_date,
            ROW_NUMBER() OVER (
                PARTITION BY
                    CASE
                        WHEN dob IS NOT NULL
                            THEN UPPER(TRIM(member_name)) || '|' || TO_CHAR(dob, 'YYYY-MM-DD')
                        ELSE source_scope || ':' || member_id
                    END
                ORDER BY
                    COALESCE(last_flight_date, enrollment_date) DESC NULLS LAST,
                    load_date DESC,
                    row_num DESC
            ) AS rn
        FROM silver.member_stg
        WHERE load_date = :AS_OF
    )
    WHERE rn = 1;

    member_count := (SELECT COUNT(*) FROM gold.member WHERE load_date = :AS_OF);
    RETURN 'GOLD members=' || :member_count;
END;
$$;
