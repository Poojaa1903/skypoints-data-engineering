-- Latest record wins, then load gold.member.
-- Dialect: Snowflake. Same rule as src/gold/latest.py and src/gold/gold.py.
--
-- A person is the same across files only when name and date of birth match.
-- Otherwise the id is scoped to its file, so AUS id 1 is not USA id 1.
-- Ranking: latest flight date (enrollment date if the flight is missing),
-- then later file date, then higher row number.

INSERT OVERWRITE INTO gold.member (
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
)
WHERE rn = 1;

-- Rows that lost (rn > 1) and sit in a different country are removed from
-- that country's view automatically, because the view reads gold.member
-- and the old row is no longer in it.
