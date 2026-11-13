-- Dataset quality gate.
-- Dialect: Snowflake.
--
-- Limits come from config/pipeline.env (loaded into bronze.pipeline_config).
-- Writes silver.quality_report for the day. Any FAIL means gold must not run.
-- Small files (under REJECT_MIN_ROWS) warn on reject rate instead of failing,
-- so one bad row in a 3-row sample does not stop the demo.
--
-- CALL silver.quality_gate(DATE '2024-01-15');

CREATE OR REPLACE PROCEDURE silver.quality_gate(AS_OF DATE)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
    reject_warn FLOAT;
    reject_fail FLOAT;
    reject_min_rows NUMBER;
    unmapped_fail FLOAT;
    row_drop_fail FLOAT;
    null_fail FLOAT;
    today_rows NUMBER;
    prev_rows NUMBER;
    prev_day DATE;
    fail_count NUMBER;
BEGIN
    reject_warn := (SELECT TO_NUMBER(setting_value) FROM bronze.pipeline_config WHERE setting_key = 'REJECT_WARN');
    reject_fail := (SELECT TO_NUMBER(setting_value) FROM bronze.pipeline_config WHERE setting_key = 'REJECT_FAIL');
    reject_min_rows := (SELECT TO_NUMBER(setting_value) FROM bronze.pipeline_config WHERE setting_key = 'REJECT_MIN_ROWS');
    unmapped_fail := (SELECT TO_NUMBER(setting_value) FROM bronze.pipeline_config WHERE setting_key = 'UNMAPPED_FAIL');
    row_drop_fail := (SELECT TO_NUMBER(setting_value) FROM bronze.pipeline_config WHERE setting_key = 'ROW_DROP_FAIL');
    null_fail := (SELECT TO_NUMBER(setting_value) FROM bronze.pipeline_config WHERE setting_key = 'NULL_FAIL');

    today_rows := (
        SELECT COUNT(*) FROM silver.member_stg WHERE load_date = :AS_OF
    ) + (
        SELECT COUNT(*) FROM silver.member_quarantine WHERE load_date = :AS_OF
    );
    prev_day := (
        SELECT MAX(load_date) FROM (
            SELECT load_date FROM silver.member_stg WHERE load_date < :AS_OF
            UNION
            SELECT load_date FROM silver.member_quarantine WHERE load_date < :AS_OF
        )
    );
    prev_rows := NULL;
    IF (prev_day IS NOT NULL) THEN
        prev_rows := (
            SELECT COUNT(*) FROM silver.member_stg WHERE load_date = :prev_day
        ) + (
            SELECT COUNT(*) FROM silver.member_quarantine WHERE load_date = :prev_day
        );
    END IF;

    DELETE FROM silver.quality_report WHERE load_date = :AS_OF;

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
            WHEN bronze_rows < :reject_min_rows AND rejected / NULLIF(bronze_rows, 0) > :reject_warn THEN 'WARN'
            WHEN bronze_rows < :reject_min_rows THEN 'PASS'
            WHEN rejected / NULLIF(bronze_rows, 0) > :reject_fail THEN 'FAIL'
            WHEN rejected / NULLIF(bronze_rows, 0) > :reject_warn THEN 'WARN'
            ELSE 'PASS'
        END,
        TO_VARCHAR(ROUND(100.0 * rejected / NULLIF(bronze_rows, 0), 1)) || '%',
        'warn > ' || TO_VARCHAR(:reject_warn * 100) || '%, fail > ' || TO_VARCHAR(:reject_fail * 100)
            || '% from ' || TO_VARCHAR(:reject_min_rows) || ' rows',
        rejected || ' of ' || bronze_rows
    FROM volumes
    UNION ALL
    SELECT
        :AS_OF,
        'unmapped_countries',
        CASE
            WHEN unmapped = 0 THEN 'PASS'
            WHEN unmapped / NULLIF(loaded, 0) > :unmapped_fail THEN 'FAIL'
            ELSE 'WARN'
        END,
        TO_VARCHAR(unmapped),
        'fail > ' || TO_VARCHAR(:unmapped_fail * 100) || '% of loaded members',
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
        'null_mandatory',
        CASE
            WHEN missing = 0 THEN 'PASS'
            WHEN missing / NULLIF(loaded, 0) > :null_fail THEN 'FAIL'
            ELSE 'WARN'
        END,
        TO_VARCHAR(missing),
        'fail > ' || TO_VARCHAR(:null_fail * 100) || '% missing member id, name, country, or enrollment',
        missing || ' of ' || loaded
    FROM (
        SELECT
            COUNT_IF(
                member_id IS NULL OR member_name IS NULL
                OR country_code IS NULL OR enrollment_date IS NULL
            ) AS missing,
            COUNT(*) AS loaded
        FROM silver.member_stg
        WHERE load_date = :AS_OF
    )
    UNION ALL
    SELECT
        :AS_OF,
        'key_uniqueness',
        IFF(dupes = 0, 'PASS', 'FAIL'),
        TO_VARCHAR(dupes),
        'member_id unique inside one file and one day',
        dupes || ' duplicate member ids'
    FROM (
        SELECT
            (
                SELECT COUNT(*)
                FROM (
                    SELECT source_file, member_id
                    FROM silver.member_stg
                    WHERE load_date = :AS_OF
                    GROUP BY source_file, member_id
                    HAVING COUNT(*) > 1
                )
            ) + (
                SELECT COUNT(*)
                FROM silver.member_quarantine
                WHERE load_date = :AS_OF
                  AND reject_rule = 'DUPLICATE_MEMBER_ID'
            ) AS dupes
    )
    UNION ALL
    SELECT
        :AS_OF,
        'flight_after_load_date',
        IFF(future_flights = 0, 'PASS', 'FAIL'),
        TO_VARCHAR(future_flights),
        'last flight cannot be after the file date',
        future_flights || ' rows'
    FROM (
        SELECT
            (
                SELECT COUNT(*)
                FROM silver.member_stg
                WHERE load_date = :AS_OF
                  AND last_flight_date > load_date
            ) + (
                SELECT COUNT(*)
                FROM silver.member_quarantine
                WHERE load_date = :AS_OF
                  AND reject_rule = 'FLIGHT_DATE_IN_FUTURE'
            ) AS future_flights
    )
    UNION ALL
    SELECT
        :AS_OF,
        'row_count',
        CASE
            WHEN :prev_rows IS NULL OR :prev_rows = 0 THEN 'PASS'
            WHEN (:prev_rows - :today_rows) / :prev_rows::FLOAT > :row_drop_fail THEN 'FAIL'
            ELSE 'PASS'
        END,
        TO_VARCHAR(:today_rows),
        'fail if drop > ' || TO_VARCHAR(:row_drop_fail * 100) || '% vs previous day',
        IFF(:prev_rows IS NULL, 'first day', :today_rows || ' vs ' || :prev_rows);

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
