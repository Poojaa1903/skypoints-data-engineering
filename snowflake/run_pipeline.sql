-- One entrypoint for the Snowflake pipeline.
-- Dialect: Snowflake.
--
-- CALL bronze.run_pipeline();
--   No date: fill every source file from MONITORING_DATE through yesterday.
-- CALL bronze.run_pipeline(DATE '2024-01-15');
--   Same window, but yesterday is replaced by the date you pass.
--
-- A day with no source file is not a gap. A day already marked SUCCESS is
-- skipped. Bronze must pass before silver runs. Quality must pass before
-- gold runs. A failed day does not stop the later days.
--
-- Source files are read from the Git repository stage named in
-- bronze.pipeline_config. Change source_stage if SHOW GIT REPOSITORIES
-- printed a different name.

CREATE TABLE IF NOT EXISTS bronze.pipeline_config (
    monitoring_date    DATE          NOT NULL,
    source_stage       VARCHAR       NOT NULL
);

INSERT INTO bronze.pipeline_config (monitoring_date, source_stage)
SELECT DATE '2024-01-15', '@skypoints_data_engineering/branches/dev'
WHERE NOT EXISTS (SELECT 1 FROM bronze.pipeline_config);

CREATE OR REPLACE PROCEDURE bronze.run_pipeline(AS_OF DATE DEFAULT NULL)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
    start_day DATE;
    end_day DATE;
    source_stage VARCHAR;
    cur DATE;
    ymd VARCHAR;
    day_path VARCHAR;
    has_files NUMBER;
    failed_files NUMBER;
    quality_fails NUMBER;
    member_count NUMBER;
    quarantine_count NUMBER;
    redemption_count NUMBER;
    summary VARCHAR;
BEGIN
    SELECT monitoring_date, source_stage
      INTO :start_day, :source_stage
    FROM bronze.pipeline_config;

    end_day := COALESCE(:AS_OF, DATEADD('day', -1, CURRENT_DATE()));
    IF (end_day < start_day) THEN
        RETURN 'MONITORING_DATE ' || TO_VARCHAR(:start_day)
            || ' is after ' || TO_VARCHAR(:end_day);
    END IF;

    CREATE OR REPLACE TEMPORARY TABLE _source_files (file_name VARCHAR);

    EXECUTE IMMEDIATE 'LIST ' || :source_stage || '/data/';
    INSERT INTO _source_files
    SELECT "name" FROM TABLE(RESULT_SCAN(:SQLID));

    EXECUTE IMMEDIATE 'LIST ' || :source_stage || '/snowflake/seed/';
    INSERT INTO _source_files
    SELECT "name" FROM TABLE(RESULT_SCAN(:SQLID));

    EXECUTE IMMEDIATE
        'COPY FILES INTO @bronze.skypoints_stage/reference/ '
        || 'FROM ' || :source_stage || '/config/ '
        || 'FILES = (''iso_countries.csv'', ''country_aliases.csv'') '
        || 'OVERWRITE = TRUE';
    CALL silver.load_reference();

    summary := 'WINDOW ' || TO_VARCHAR(:start_day) || ' through ' || TO_VARCHAR(:end_day);
    cur := start_day;

    WHILE (cur <= end_day) DO
        ymd := TO_VARCHAR(:cur, 'YYYYMMDD');
        day_path := TO_VARCHAR(:cur, 'YYYY-MM-DD');
        has_files := (
            SELECT COUNT(*) FROM _source_files
            WHERE file_name ILIKE '%members_' || :ymd || '.txt'
               OR file_name ILIKE '%redemptions_' || :ymd || '.json'
               OR file_name ILIKE '%country_extract_' || :ymd || '.csv'
        );

        IF (has_files > 0) THEN
            IF (
                EXISTS (
                    SELECT 1 FROM gold.pipeline_run
                    WHERE load_date = :cur AND status = 'SUCCESS'
                )
            ) THEN
                summary := summary || '\nSKIP ' || :day_path;
            ELSE
                IF (EXISTS (
                    SELECT 1 FROM _source_files
                    WHERE file_name ILIKE '%members_' || :ymd || '.txt'
                )) THEN
                    EXECUTE IMMEDIATE
                        'COPY FILES INTO @bronze.skypoints_stage/members_flat/' || :day_path || '/ '
                        || 'FROM ' || :source_stage || '/data/ '
                        || 'FILES = (''members_' || :ymd || '.txt'') OVERWRITE = TRUE';
                END IF;

                IF (EXISTS (
                    SELECT 1 FROM _source_files
                    WHERE file_name ILIKE '%redemptions_' || :ymd || '.json'
                )) THEN
                    EXECUTE IMMEDIATE
                        'COPY FILES INTO @bronze.skypoints_stage/redemptions/' || :day_path || '/ '
                        || 'FROM ' || :source_stage || '/data/ '
                        || 'FILES = (''redemptions_' || :ymd || '.json'') OVERWRITE = TRUE';
                END IF;

                IF (EXISTS (
                    SELECT 1 FROM _source_files
                    WHERE file_name ILIKE '%country_extract_' || :ymd || '.csv'
                )) THEN
                    EXECUTE IMMEDIATE
                        'COPY FILES INTO @bronze.skypoints_stage/country_xlsx/' || :day_path || '/ '
                        || 'FROM ' || :source_stage || '/snowflake/seed/ '
                        || 'FILES = (''country_extract_' || :ymd || '.csv'') OVERWRITE = TRUE';
                END IF;

                CALL bronze.load_day(:cur);
                CALL bronze.audit_day(:cur);
                failed_files := (
                    SELECT COUNT(*) FROM bronze.file_audit
                    WHERE load_date = :cur AND status = 'FAILED'
                );

                IF (failed_files > 0) THEN
                    summary := summary || '\nBLOCKED ' || :day_path || ' bronze audit failed';
                ELSE
                    CALL silver.load_day(:cur);
                    CALL silver.quality_gate(:cur);
                    quality_fails := (
                        SELECT COUNT(*) FROM silver.quality_report
                        WHERE load_date = :cur AND status = 'FAIL'
                    );

                    IF (quality_fails > 0) THEN
                        summary := summary || '\nQUALITY FAIL ' || :day_path || ' gold skipped';
                    ELSE
                        CALL gold.load_members(:cur);
                        CALL gold.load_redemptions(:cur);

                        member_count := (SELECT COUNT(*) FROM gold.member WHERE load_date = :cur);
                        quarantine_count := (SELECT COUNT(*) FROM silver.member_quarantine WHERE load_date = :cur);
                        redemption_count := (
                            SELECT COUNT(*) FROM gold.redemption r
                            WHERE EXISTS (
                                SELECT 1
                                FROM bronze.redemption_raw br,
                                     LATERAL FLATTEN(input => br.payload:redemptions) f
                                WHERE br.load_date = :cur
                                  AND f.value:txn_id::VARCHAR = r.txn_id
                            )
                        );

                        DELETE FROM gold.pipeline_run WHERE load_date = :cur;
                        INSERT INTO gold.pipeline_run (
                            load_date, finished_at, member_count, quarantine_count, redemption_count, status
                        )
                        VALUES (
                            :cur, CURRENT_TIMESTAMP(), :member_count, :quarantine_count, :redemption_count, 'SUCCESS'
                        );

                        summary := summary || '\nSUCCESS ' || :day_path
                            || ' members=' || :member_count
                            || ' quarantined=' || :quarantine_count
                            || ' redemptions=' || :redemption_count;
                    END IF;
                END IF;
            END IF;
        END IF;

        cur := DATEADD('day', 1, cur);
    END WHILE;

    RETURN summary;
END;
$$;
