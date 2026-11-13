-- Daily orchestrator. Same role as local/utils/backfill.py + pipeline.py.
-- Dialect: Snowflake.
--
-- Runs one day end to end:
--   1. Land files from the stage into bronze
--   2. Audit the day; stop if any feed failed
--   3. Load silver (typed members + quarantine)
--   4. Quality gate; stop if any check FAILs (WARN continues)
--   5. Load gold members and redemptions
--   6. Record gold.pipeline_run (the _SUCCESS marker)
--
-- Setup once (see snowflake/README.md), then:
--   CALL bronze.run_pipeline(DATE '2024-01-15');
--
-- Optional daily task (yesterday):
--   CREATE OR REPLACE TASK bronze.task_run_yesterday
--     WAREHOUSE = COMPUTE_WH
--     SCHEDULE = 'USING CRON 15 1 * * * UTC'
--   AS CALL bronze.run_pipeline(DATEADD('day', -1, CURRENT_DATE()));

CREATE OR REPLACE PROCEDURE bronze.run_pipeline(AS_OF DATE)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
    failed_files NUMBER;
    quality_fails NUMBER;
    member_count NUMBER;
    quarantine_count NUMBER;
    redemption_count NUMBER;
BEGIN
    IF (
        EXISTS (
            SELECT 1 FROM gold.pipeline_run
            WHERE load_date = :AS_OF AND status = 'SUCCESS'
        )
    ) THEN
        RETURN 'SKIP ' || TO_VARCHAR(:AS_OF) || ' already in gold.pipeline_run';
    END IF;

    CALL bronze.load_day(:AS_OF);

    CALL bronze.audit_day(:AS_OF);
    failed_files := (
        SELECT COUNT(*) FROM bronze.file_audit
        WHERE load_date = :AS_OF AND status = 'FAILED'
    );
    IF (failed_files > 0) THEN
        RETURN 'BLOCKED ' || TO_VARCHAR(:AS_OF) || ' bronze audit failed';
    END IF;

    CALL silver.load_day(:AS_OF);

    CALL silver.quality_gate(:AS_OF);
    quality_fails := (
        SELECT COUNT(*) FROM silver.quality_report
        WHERE load_date = :AS_OF AND status = 'FAIL'
    );
    IF (quality_fails > 0) THEN
        RETURN 'QUALITY FAIL ' || TO_VARCHAR(:AS_OF) || ' gold skipped';
    END IF;

    CALL gold.load_members(:AS_OF);
    CALL gold.load_redemptions(:AS_OF);

    member_count := (SELECT COUNT(*) FROM gold.member WHERE load_date = :AS_OF);
    quarantine_count := (SELECT COUNT(*) FROM silver.member_quarantine WHERE load_date = :AS_OF);
    redemption_count := (
        SELECT COUNT(*) FROM gold.redemption r
        WHERE EXISTS (
            SELECT 1
            FROM bronze.redemption_raw br,
                 LATERAL FLATTEN(input => br.payload:redemptions) f
            WHERE br.load_date = :AS_OF
              AND f.value:txn_id::VARCHAR = r.txn_id
        )
    );

    DELETE FROM gold.pipeline_run WHERE load_date = :AS_OF;
    INSERT INTO gold.pipeline_run (
        load_date, finished_at, member_count, quarantine_count, redemption_count, status
    )
    VALUES (
        :AS_OF, CURRENT_TIMESTAMP(), :member_count, :quarantine_count, :redemption_count, 'SUCCESS'
    );

    RETURN 'SUCCESS ' || TO_VARCHAR(:AS_OF)
        || ' members=' || :member_count
        || ' quarantined=' || :quarantine_count
        || ' redemptions=' || :redemption_count;
END;
$$;
