-- Land one day's files from the stage into bronze tables.
-- Dialect: Snowflake.
--
-- Before the first sample run, upload the files (from the project root,
-- with SnowSQL connected to your account):
--
--   PUT file://data/members_20240115.txt @bronze.skypoints_stage/members_flat/2024-01-15/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE;
--   PUT file://data/redemptions_20240115.json @bronze.skypoints_stage/redemptions/2024-01-15/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE;
--   PUT file://seed/country_extract_20240115.csv @bronze.skypoints_stage/country_xlsx/2024-01-15/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE;
--
-- CALL bronze.load_day(DATE '2024-01-15');

CREATE OR REPLACE PROCEDURE bronze.load_day(AS_OF DATE)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
    day_path VARCHAR;
    internal_stage VARCHAR;
    flat_count NUMBER;
    country_count NUMBER;
    redemption_count NUMBER;
BEGIN
    day_path := TO_VARCHAR(:AS_OF, 'YYYY-MM-DD');
    internal_stage := (SELECT setting_value FROM bronze.pipeline_config WHERE setting_key = 'INTERNAL_STAGE');

    DELETE FROM bronze.member_flat_raw WHERE load_date = :AS_OF;
    DELETE FROM bronze.country_extract_raw WHERE load_date = :AS_OF;
    DELETE FROM bronze.redemption_raw WHERE load_date = :AS_OF;

    TRUNCATE TABLE bronze.flat_landing;
    TRUNCATE TABLE bronze.country_landing;
    TRUNCATE TABLE bronze.redemption_landing;

    -- Flat member file. Leading "|" makes the first CSV field empty.
    EXECUTE IMMEDIATE
        'COPY INTO bronze.flat_landing '
        || 'FROM ' || :internal_stage || '/members_flat/' || :day_path || '/ '
        || 'FILE_FORMAT = (FORMAT_NAME = bronze.ff_pipe) '
        || 'ON_ERROR = ''ABORT_STATEMENT''';

    INSERT INTO bronze.member_flat_raw (
        source_file, load_ts, load_date, row_num,
        record_type, member_name, member_id, enrollment_date, last_flight_date,
        tier_code, agent_name, state, country, dob, is_active
    )
    SELECT
        'members_' || TO_VARCHAR(:AS_OF, 'YYYYMMDD') || '.txt',
        CURRENT_TIMESTAMP()::TIMESTAMP_NTZ,
        :AS_OF,
        ROW_NUMBER() OVER (ORDER BY member_id),
        record_type, member_name, member_id, enrollment_date, last_flight_date,
        tier_code, agent_name, state, country, dob, is_active
    FROM bronze.flat_landing
    WHERE record_type IS NOT NULL;

    flat_count := (SELECT COUNT(*) FROM bronze.member_flat_raw WHERE load_date = :AS_OF);

    -- Country extracts. The seed CSV keeps the Excel values as text.
    EXECUTE IMMEDIATE
        'COPY INTO bronze.country_landing '
        || 'FROM ' || :internal_stage || '/country_xlsx/' || :day_path || '/ '
        || 'FILE_FORMAT = (FORMAT_NAME = bronze.ff_csv) '
        || 'ON_ERROR = ''ABORT_STATEMENT''';

    INSERT INTO bronze.country_extract_raw (
        source_file, source_country, load_ts, load_date, row_num,
        source_member_id, member_name, tier_code, dob_raw,
        enrollment_date_raw, flight_date_raw, individual_or_corp
    )
    SELECT
        source_file, source_country,
        CURRENT_TIMESTAMP()::TIMESTAMP_NTZ,
        :AS_OF, row_num,
        source_member_id, member_name, tier_code, dob_raw,
        enrollment_date_raw, flight_date_raw, individual_or_corp
    FROM bronze.country_landing;

    country_count := (SELECT COUNT(*) FROM bronze.country_extract_raw WHERE load_date = :AS_OF);

    -- Redemption JSON. One object per file; payload kept as VARIANT.
    EXECUTE IMMEDIATE
        'COPY INTO bronze.redemption_landing '
        || 'FROM ' || :internal_stage || '/redemptions/' || :day_path || '/ '
        || 'FILE_FORMAT = (FORMAT_NAME = bronze.ff_json) '
        || 'ON_ERROR = ''ABORT_STATEMENT''';

    INSERT INTO bronze.redemption_raw (
        source_file, load_ts, load_date, row_num, member_id, feed_date, payload
    )
    SELECT
        'redemptions_' || TO_VARCHAR(:AS_OF, 'YYYYMMDD') || '.json',
        CURRENT_TIMESTAMP()::TIMESTAMP_NTZ,
        :AS_OF,
        1,
        payload:member_id::VARCHAR,
        payload:feed_date::VARCHAR,
        payload
    FROM bronze.redemption_landing;

    redemption_count := (SELECT COUNT(*) FROM bronze.redemption_raw WHERE load_date = :AS_OF);

    INSERT INTO bronze.load_audit (source_file, feed_type, load_ts, row_count, rejected_count, status)
    SELECT 'members_' || TO_VARCHAR(:AS_OF, 'YYYYMMDD') || '.txt', 'MEMBER_FLAT',
           CURRENT_TIMESTAMP()::TIMESTAMP_NTZ, :flat_count, 0, 'LOADED'
    UNION ALL
    SELECT 'country_extract_' || TO_VARCHAR(:AS_OF, 'YYYYMMDD') || '.csv', 'COUNTRY_XLSX',
           CURRENT_TIMESTAMP()::TIMESTAMP_NTZ, :country_count, 0, 'LOADED'
    UNION ALL
    SELECT 'redemptions_' || TO_VARCHAR(:AS_OF, 'YYYYMMDD') || '.json', 'REDEMPTION_JSON',
           CURRENT_TIMESTAMP()::TIMESTAMP_NTZ, :redemption_count, 0, 'LOADED';

    RETURN 'LANDED flat=' || :flat_count || ' country=' || :country_count
        || ' redemptions=' || :redemption_count;
END;
$$;
