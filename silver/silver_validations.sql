-- Validation queries. Each one returns the bad rows.
-- A non-empty result is a failed check. The pipeline still loads the
-- other rows; these rows are the ones that belong in quarantine.
-- Dialect: Snowflake. Run after silver is loaded.
--
-- The runnable gate is silver.quality_gate (silver/quality_gate.sql).
-- A FAIL there stops gold.
-- These queries are ad-hoc checks you can run by hand in a worksheet.

-- 1. Mandatory fields. Member id, name, country and enrollment date.
SELECT source_file, row_num, 'MEMBER_ID_MISSING' AS reject_rule
FROM silver.member_stg
WHERE member_id IS NULL OR TRIM(member_id) = ''
UNION ALL
SELECT source_file, row_num, 'MEMBER_NAME_MISSING'
FROM silver.member_stg
WHERE member_name IS NULL OR TRIM(member_name) = ''
UNION ALL
SELECT source_file, row_num, 'COUNTRY_MISSING'
FROM silver.member_stg
WHERE country_code IS NULL OR country_status = 'MISSING'
UNION ALL
SELECT source_file, row_num, 'ENROLLMENT_DATE_MISSING'
FROM silver.member_stg
WHERE enrollment_date IS NULL;

-- 2. The same member_id twice inside one file.
--    The same id in two country files is not a duplicate.
SELECT source_file, member_id, COUNT(*) AS copies
FROM silver.member_stg
GROUP BY source_file, member_id
HAVING COUNT(*) > 1;

-- 3. A flight date after the run date is bad data.
SELECT source_file, row_num, member_id, last_flight_date
FROM silver.member_stg
WHERE last_flight_date > load_date;

-- 4. Country codes the ISO list and the alias file did not know.
--    These rows are loaded. This query is the list to review.
SELECT source_code, country_code, first_seen_date
FROM silver.ref_country
WHERE country_status = 'UNMAPPED';

-- 5. Fail the run only when rejections are a large share of the file.
--    Replace 0.05 with the threshold the business agrees.
SELECT
    source_file,
    rejected,
    loaded,
    rejected / NULLIF(rejected + loaded, 0) AS reject_rate
FROM (
    SELECT source_file, COUNT(*) AS rejected
    FROM silver.member_quarantine
    GROUP BY source_file
) q
JOIN (
    SELECT source_file, COUNT(*) AS loaded
    FROM silver.member_stg
    GROUP BY source_file
) s USING (source_file)
WHERE rejected / NULLIF(rejected + loaded, 0) > 0.05;
