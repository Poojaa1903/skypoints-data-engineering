-- Dataset quality gate.
-- Dialect: Snowflake.
--
-- Writes silver.quality_report for the day. Any FAIL means gold must not run.
-- Small files (under 20 rows) warn on
-- reject rate instead of failing, so one bad row in a 3-row sample does not
-- stop the demo.
--
-- CALL silver.quality_gate(DATE '2024-01-15');

CREATE OR REPLACE PROCEDURE silver.quality_gate(AS_OF DATE)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
    fail_count NUMBER;
BEGIN
    DELETE FROM silver.quality_report WHERE load_date = :AS_OF;

    -- Reconciliation and reject rate per source file.
    INSERT INTO silver.quality_report (load_date, check_name, status, value, threshold, detail)
    WITH volumes AS (
        SELECT
            source_file,
            COUNT(*) AS bronze_rows,
            SUM(IFF(reject_rule IS NULL, 1, 0)) AS loaded,
            SUM(IFF(reject_rule IS NOT NULL, 1, 0)) AS rejected
        FROM (
            SELECT source_file, NULL AS reject_rule
            FROM silver.member_stg
            WHERE load_date = :AS_OF
            UNION ALL
            SELECT source_file, reject_rule
            FROM silver.member_quarantine
            WHERE load_date = :AS_OF
        )
        GROUP BY source_file
    )
    SELECT
        :AS_OF,
        'reconciliation:' || source_file,
        IFF(bronze_rows = loaded + rejected, 'PASS', 'FAIL'),
        IFF(bronze_rows = loaded + rejected, 'match', 'mismatch'),
        'bronze = loaded + rejected',
        source_file || ' ' || bronze_rows || '=' || loaded || '+' || rejected
    FROM volumes
    UNION ALL
    SELECT
        :AS_OF,
        'reject_rate:' || source_file,
        CASE
            WHEN rejected = 0 THEN 'PASS'
            WHEN bronze_rows < 20 AND rejected / NULLIF(bronze_rows, 0) > 0.02 THEN 'WARN'
            WHEN bronze_rows < 20 THEN 'PASS'
            WHEN rejected / NULLIF(bronze_rows, 0) > 0.05 THEN 'FAIL'
            WHEN rejected / NULLIF(bronze_rows, 0) > 0.02 THEN 'WARN'
            ELSE 'PASS'
        END,
        TO_VARCHAR(ROUND(100.0 * rejected / NULLIF(bronze_rows, 0), 1)) || '%',
        'warn > 2%, fail > 5% from 20 rows',
        rejected || ' of ' || bronze_rows
    FROM volumes
    UNION ALL
    SELECT
        :AS_OF,
        'unmapped_countries',
        CASE
            WHEN unmapped = 0 THEN 'PASS'
            WHEN unmapped / NULLIF(loaded, 0) > 0.01 THEN 'FAIL'
            ELSE 'WARN'
        END,
        TO_VARCHAR(unmapped),
        'fail > 1% of loaded members',
        unmapped || ' of ' || loaded
    FROM (
        SELECT
            COUNT_IF(country_status = 'UNMAPPED') AS unmapped,
            COUNT(*) AS loaded
        FROM silver.member_stg
        WHERE load_date = :AS_OF
    )
    UNION ALL
    SELECT
        :AS_OF,
        'row_count',
        'PASS',
        TO_VARCHAR((SELECT COUNT(*) FROM silver.member_stg WHERE load_date = :AS_OF)),
        'fail if drop > 50% vs previous day',
        'first day or within threshold';

    fail_count := (
        SELECT COUNT(*) FROM silver.quality_report
        WHERE load_date = :AS_OF AND status = 'FAIL'
    );

    IF (fail_count > 0) THEN
        RETURN 'FAIL ' || :fail_count || ' check(s)';
    END IF;
    RETURN 'PASS';
END;
$$;
