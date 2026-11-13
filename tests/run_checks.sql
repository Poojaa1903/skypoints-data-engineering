-- Checks for the date rules, the reject rules, and the loaded sample.
-- Dialect: Snowflake. Run after CALL bronze.run_pipeline(DATE '2024-01-15').
--
-- CALL tests.run_checks();
-- A failing check is a row in tests.check_result with status FAIL.
-- The throwaway day 2099-01-01 is inserted and removed inside the procedure.

CREATE SCHEMA IF NOT EXISTS tests;

CREATE TABLE IF NOT EXISTS tests.check_result (
    check_name   VARCHAR NOT NULL,
    status       VARCHAR NOT NULL,
    detail       VARCHAR
);

CREATE OR REPLACE PROCEDURE tests.run_checks()
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
    failed NUMBER;
    failed_names VARCHAR;
BEGIN
    DELETE FROM tests.check_result;

    INSERT INTO tests.check_result
    SELECT 'ambiguous_1052022', IFF(silver.us_date_is_ambiguous('1052022'), 'PASS', 'FAIL'),
           '01/05/2022 and 10/05/2022 are both valid'
    UNION ALL
    SELECT 'ambiguous_1152022', IFF(silver.us_date_is_ambiguous('1152022'), 'PASS', 'FAIL'),
           '01/15/2022 and 11/05/2022 are both valid'
    UNION ALL
    SELECT 'unambiguous_6152022',
           IFF(NOT silver.us_date_is_ambiguous('6152022')
               AND silver.us_date_parse('6152022') = DATE '2022-06-15', 'PASS', 'FAIL'),
           'only 06/15/2022 is a real date'
    UNION ALL
    SELECT 'parse_12282021',
           IFF(silver.us_date_parse('12282021') = DATE '2021-12-28', 'PASS', 'FAIL'),
           'MMDDYYYY'
    UNION ALL
    SELECT 'excel_44692',
           IFF(DATEADD('day', 44692, DATE '1899-12-30') = DATE '2022-05-11', 'PASS', 'FAIL'),
           'AUS and IND serials use 1899-12-30'
    UNION ALL
    SELECT 'age_38',
           IFF(
               DATEDIFF('year', DATE '1985-03-05', DATE '2024-01-15')
               - IFF(TO_CHAR(DATE '2024-01-15', 'MMDD') < TO_CHAR(DATE '1985-03-05', 'MMDD'), 1, 0) = 38,
               'PASS', 'FAIL'),
           'birthday has not happened yet on 15 Jan'
    UNION ALL
    SELECT 'stale_old_flight',
           IFF(DATEDIFF('day', DATE '2012-10-13', DATE '2024-01-15') > 90, 'PASS', 'FAIL'),
           'Elena last flew in 2012'
    UNION ALL
    SELECT 'stale_exactly_90_is_not_stale',
           IFF(DATEDIFF('day', DATE '2023-10-17', DATE '2024-01-15') = 90, 'PASS', 'FAIL'),
           'more than 90 days is stale, 90 is not';

    DELETE FROM bronze.country_extract_raw WHERE load_date = DATE '2099-01-01';
    INSERT INTO bronze.country_extract_raw (
        source_file, source_country, load_ts, load_date, row_num,
        source_member_id, member_name, tier_code,
        enrollment_date_raw, flight_date_raw
    )
    SELECT 'USA.xlsx', 'USA', CURRENT_TIMESTAMP()::TIMESTAMP_NTZ, DATE '2099-01-01', 1,
           '9', 'Dup', 'GLD', '06152022', '08202022'
    UNION ALL
    SELECT 'USA.xlsx', 'USA', CURRENT_TIMESTAMP()::TIMESTAMP_NTZ, DATE '2099-01-01', 2,
           '9', 'Dup', 'GLD', '06152022', '08202022'
    UNION ALL
    SELECT 'USA.xlsx', 'USA', CURRENT_TIMESTAMP()::TIMESTAMP_NTZ, DATE '2099-01-01', 3,
           '8', 'Future', 'GLD', '01012099', '01022099';

    INSERT INTO tests.check_result
    SELECT 'duplicate_member_id',
           IFF(COUNT(*) = 2, 'PASS', 'FAIL'),
           COUNT(*) || ' rows marked DUPLICATE_MEMBER_ID'
    FROM silver.member_parsed
    WHERE load_date = DATE '2099-01-01'
      AND member_id = '9'
      AND reject_rule = 'DUPLICATE_MEMBER_ID';

    INSERT INTO tests.check_result
    SELECT 'flight_in_future',
           IFF(COUNT(*) = 1, 'PASS', 'FAIL'),
           COUNT(*) || ' rows marked FLIGHT_DATE_IN_FUTURE'
    FROM silver.member_parsed
    WHERE load_date = DATE '2099-01-01'
      AND member_id = '8'
      AND reject_rule = 'FLIGHT_DATE_IN_FUTURE';

    DELETE FROM bronze.country_extract_raw WHERE load_date = DATE '2099-01-01';

    DELETE FROM silver.member_stg WHERE load_date = DATE '2099-01-02';
    INSERT INTO silver.member_stg (
        source_file, source_system, source_scope, row_num, load_date,
        member_id, member_name, country_code, country_status,
        enrollment_date, last_flight_date, dob, is_stale_member
    )
    SELECT 'AUS.xlsx', 'COUNTRY_XLSX', 'AUS', 1, DATE '2099-01-02',
           '1', 'Moved Person', 'AUS', 'MAPPED',
           DATE '2020-01-01', DATE '2020-06-01', DATE '1990-01-01', TRUE
    UNION ALL
    SELECT 'USA.xlsx', 'COUNTRY_XLSX', 'USA', 1, DATE '2099-01-02',
           '1', 'Moved Person', 'USA', 'MAPPED',
           DATE '2020-01-01', DATE '2024-06-01', DATE '1990-01-01', FALSE;

    CALL gold.load_members(DATE '2099-01-02');

    INSERT INTO tests.check_result
    SELECT 'latest_record_wins',
           IFF(COUNT(*) = 1 AND MAX(country_code) = 'USA', 'PASS', 'FAIL'),
           COUNT(*) || ' rows, country ' || COALESCE(MAX(country_code), 'none')
    FROM gold.member
    WHERE load_date = DATE '2099-01-02'
      AND member_name = 'Moved Person';

    DELETE FROM silver.member_stg WHERE load_date = DATE '2099-01-02';
    DELETE FROM gold.member WHERE load_date = DATE '2099-01-02';

    INSERT INTO tests.check_result
    SELECT 'sample_country_' || country_code,
           IFF(COALESCE(n, 0) = expected, 'PASS', 'FAIL'),
           COALESCE(n, 0) || ' rows, expected ' || expected
    FROM (
        SELECT 'AUS' AS country_code, 3 AS expected
        UNION ALL SELECT 'IND', 4
        UNION ALL SELECT 'USA', 3
        UNION ALL SELECT 'CAN', 1
        UNION ALL SELECT 'PHL', 1
    ) e
    LEFT JOIN (
        SELECT country_code, COUNT(*) AS n
        FROM gold.member
        WHERE load_date = DATE '2024-01-15'
        GROUP BY country_code
    ) g USING (country_code);

    INSERT INTO tests.check_result
    SELECT 'sample_quarantine',
           IFF(COUNT(*) = 2, 'PASS', 'FAIL'),
           COUNT(*) || ' quarantined rows'
    FROM silver.member_quarantine
    WHERE load_date = DATE '2024-01-15';

    INSERT INTO tests.check_result
    SELECT 'sample_john_ambiguous',
           IFF(COUNT(*) = 1, 'PASS', 'FAIL'),
           'USA.xlsx John'
    FROM silver.member_quarantine
    WHERE load_date = DATE '2024-01-15'
      AND source_file = 'USA.xlsx'
      AND reject_rule = 'ENROLLMENT_DATE_AMBIGUOUS';

    INSERT INTO tests.check_result
    SELECT 'sample_jonnathan_invalid',
           IFF(COUNT(*) = 1, 'PASS', 'FAIL'),
           'AUS.xlsx Jonnathan'
    FROM silver.member_quarantine
    WHERE load_date = DATE '2024-01-15'
      AND source_file = 'AUS.xlsx'
      AND reject_rule = 'ENROLLMENT_DATE_INVALID';

    INSERT INTO tests.check_result
    SELECT 'sample_elena_age_stale',
           IFF(COUNT(*) = 1, 'PASS', 'FAIL'),
           'age 38 and stale'
    FROM gold.member
    WHERE load_date = DATE '2024-01-15'
      AND member_id = '223457'
      AND source_scope = 'FLAT'
      AND age = 38
      AND is_stale_member;

    INSERT INTO tests.check_result
    SELECT 'sample_mateo_alias',
           IFF(COUNT(*) = 1, 'PASS', 'FAIL'),
           'PHIL maps to PHL'
    FROM gold.member
    WHERE load_date = DATE '2024-01-15'
      AND member_id = '223459'
      AND country_code = 'PHL'
      AND country_status = 'ALIAS';

    INSERT INTO tests.check_result
    SELECT 'sample_mike_both_countries',
           IFF(COUNT(*) = 2, 'PASS', 'FAIL'),
           COUNT(*) || ' Mike rows'
    FROM gold.member
    WHERE load_date = DATE '2024-01-15'
      AND member_name = 'Mike';

    INSERT INTO tests.check_result
    SELECT 'sample_redemptions',
           IFF(COUNT(*) = 2, 'PASS', 'FAIL'),
           COUNT(*) || ' matched redemptions'
    FROM gold.redemption
    WHERE member_id = '223457'
      AND country_code = 'USA'
      AND match_status = 'MATCHED';

    failed := (SELECT COUNT(*) FROM tests.check_result WHERE status = 'FAIL');
    IF (failed > 0) THEN
        failed_names := (
            SELECT LISTAGG(check_name, ', ') WITHIN GROUP (ORDER BY check_name)
            FROM tests.check_result
            WHERE status = 'FAIL'
        );
        RETURN 'FAIL ' || :failed || ': ' || :failed_names;
    END IF;
    RETURN 'PASS ' || (SELECT COUNT(*) FROM tests.check_result) || ' checks';
END;
$$;
