-- Schema and file audit for one day.
-- Dialect: Snowflake.
--
-- Writes bronze.file_audit and bronze.schema_audit. A feed with zero rows
-- for the day is FAILED and the daily job must not move that day to silver.
--
-- CALL bronze.audit_day(DATE '2024-01-15');

CREATE OR REPLACE PROCEDURE bronze.audit_day(AS_OF DATE)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
    flat_rows NUMBER;
    country_rows NUMBER;
    redemption_rows NUMBER;
    failed_count NUMBER;
BEGIN
    DELETE FROM bronze.file_audit WHERE load_date = :AS_OF;
    DELETE FROM bronze.schema_audit WHERE load_date = :AS_OF;

    flat_rows := (SELECT COUNT(*) FROM bronze.member_flat_raw WHERE load_date = :AS_OF AND record_type = 'D');
    country_rows := (SELECT COUNT(*) FROM bronze.country_extract_raw WHERE load_date = :AS_OF);
    redemption_rows := (SELECT COUNT(*) FROM bronze.redemption_raw WHERE load_date = :AS_OF);

    INSERT INTO bronze.file_audit (
        checked_at, load_date, feed, source_file, sha256, status, row_count, column_count, detail
    )
    SELECT
        CURRENT_TIMESTAMP(),
        :AS_OF,
        'members_flat',
        'members_' || TO_VARCHAR(:AS_OF, 'YYYYMMDD') || '.txt',
        'stage',
        IFF(:flat_rows = 0, 'FAILED', 'NEW_FILE'),
        :flat_rows,
        10,
        IFF(:flat_rows = 0, 'no detail rows for this day', 'landed')
    UNION ALL
    SELECT
        CURRENT_TIMESTAMP(),
        :AS_OF,
        'country_xlsx',
        'country_extract_' || TO_VARCHAR(:AS_OF, 'YYYYMMDD') || '.csv',
        'stage',
        IFF(:country_rows = 0, 'FAILED', 'NEW_FILE'),
        :country_rows,
        8,
        IFF(:country_rows = 0, 'no country rows for this day', 'landed')
    UNION ALL
    SELECT
        CURRENT_TIMESTAMP(),
        :AS_OF,
        'redemptions',
        'redemptions_' || TO_VARCHAR(:AS_OF, 'YYYYMMDD') || '.json',
        'stage',
        IFF(:redemption_rows = 0, 'FAILED', 'NEW_FILE'),
        :redemption_rows,
        3,
        IFF(:redemption_rows = 0, 'no redemption payload for this day', 'landed');

    -- Column snapshot for the flat feed (one row per expected column).
    INSERT INTO bronze.schema_audit (
        checked_at, load_date, feed, source_file, column_position, column_name, data_type, change
    )
    SELECT CURRENT_TIMESTAMP(), :AS_OF, 'members_flat',
           'members_' || TO_VARCHAR(:AS_OF, 'YYYYMMDD') || '.txt',
           column_position, column_name, 'TEXT', 'NEW_FILE'
    FROM (
        SELECT 1 AS column_position, 'Member_Name' AS column_name
        UNION ALL SELECT 2, 'Member_Id'
        UNION ALL SELECT 3, 'Enrollment_Date'
        UNION ALL SELECT 4, 'Last_Flight_Date'
        UNION ALL SELECT 5, 'Tier_Code'
        UNION ALL SELECT 6, 'Agent_Name'
        UNION ALL SELECT 7, 'State'
        UNION ALL SELECT 8, 'Country'
        UNION ALL SELECT 9, 'DOB'
        UNION ALL SELECT 10, 'Is_Active'
    );

    failed_count := (
        SELECT COUNT(*) FROM bronze.file_audit
        WHERE load_date = :AS_OF AND status = 'FAILED'
    );

    IF (failed_count > 0) THEN
        RETURN 'FAILED ' || :failed_count || ' file(s)';
    END IF;
    RETURN 'PASSED flat=' || :flat_rows || ' country=' || :country_rows
        || ' redemptions=' || :redemption_rows;
END;
$$;
