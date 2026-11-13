-- Load config/pipeline.env into bronze.pipeline_config.
-- Dialect: Snowflake. Run once after setup/stage_and_formats.sql.
-- Every pipeline call reloads the file, so an edit takes effect on the next run.
--
-- CALL bronze.load_config();

CREATE TABLE IF NOT EXISTS bronze.pipeline_config (
    setting_key        VARCHAR       NOT NULL,
    setting_value      VARCHAR       NOT NULL
);

CREATE OR REPLACE PROCEDURE bronze.load_config()
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
    source_stage VARCHAR;
    internal_stage VARCHAR;
    config_dir VARCHAR;
    loaded NUMBER;
BEGIN
    -- Used only when the table is empty, so the first run can find the file.
    source_stage := (
        SELECT setting_value FROM bronze.pipeline_config WHERE setting_key = 'SOURCE_STAGE'
    );
    IF (source_stage IS NULL) THEN
        source_stage := '@SKYPOINTS.PUBLIC."skypoints-data-engineering"/branches/dev';
    END IF;
    internal_stage := COALESCE(
        (SELECT setting_value FROM bronze.pipeline_config WHERE setting_key = 'INTERNAL_STAGE'),
        '@bronze.skypoints_stage'
    );
    config_dir := COALESCE(
        (SELECT setting_value FROM bronze.pipeline_config WHERE setting_key = 'CONFIG_DIR'),
        'config'
    );

    EXECUTE IMMEDIATE
        'COPY FILES INTO ' || :internal_stage || '/reference/ '
        || 'FROM ' || :source_stage || '/' || :config_dir || '/ '
        || 'FILES = (''pipeline.env'')';

    CREATE OR REPLACE TEMPORARY TABLE _env_raw (
        setting_key VARCHAR,
        setting_value VARCHAR
    );
    EXECUTE IMMEDIATE
        'COPY INTO _env_raw '
        || 'FROM ' || :internal_stage || '/reference/pipeline.env '
        || 'FILE_FORMAT = (FORMAT_NAME = ''bronze.ff_env'') '
        || 'ON_ERROR = ''ABORT_STATEMENT''';

    MERGE INTO bronze.pipeline_config t
    USING (
        SELECT UPPER(TRIM(setting_key)) AS setting_key,
               TRIM(setting_value) AS setting_value
        FROM _env_raw
        WHERE setting_value IS NOT NULL
          AND TRIM(setting_key) <> ''
          AND LEFT(TRIM(setting_key), 1) <> '#'
    ) s
    ON t.setting_key = s.setting_key
    WHEN MATCHED THEN UPDATE SET setting_value = s.setting_value
    WHEN NOT MATCHED THEN INSERT (setting_key, setting_value)
        VALUES (s.setting_key, s.setting_value);

    loaded := (SELECT COUNT(*) FROM bronze.pipeline_config WHERE setting_key = 'REJECT_FAIL');
    IF (loaded = 0) THEN
        RETURN 'CONFIG MISSING. Check config/pipeline.env and SOURCE_STAGE.';
    END IF;
    RETURN 'CONFIG LOADED ' || (SELECT COUNT(*) FROM bronze.pipeline_config);
END;
$$;
