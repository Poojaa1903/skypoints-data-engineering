-- Column change log for one day, compared with the previous day.
-- Dialect: Snowflake.
--
-- One row per column. change is NEW_FILE, NEW_COLUMN, MISSING,
-- TYPE_CHANGED, UNCHANGED, or FAILED.
-- FAILED means that feed landed zero rows. run_pipeline then skips silver.
-- A new or missing column is recorded and the day still continues.
--
-- Flat and country columns come from the file header. JSON columns come
-- from the keys in the payload, including fields inside each redemption.
--
-- CALL bronze.audit_day(DATE '2024-01-15');

DROP TABLE IF EXISTS bronze.file_audit;

CREATE TABLE IF NOT EXISTS bronze.schema_audit (
    checked_at         TIMESTAMP_LTZ NOT NULL,
    load_date          DATE          NOT NULL,
    feed               VARCHAR       NOT NULL,
    source_file        VARCHAR       NOT NULL,
    column_position    NUMBER,
    column_name        VARCHAR       NOT NULL,
    data_type          VARCHAR       NOT NULL,
    change             VARCHAR       NOT NULL,
    created_at         TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
    created_by         VARCHAR       DEFAULT CURRENT_USER(),
    modified_at        TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY (load_date, feed);

CREATE OR REPLACE PROCEDURE bronze.audit_day(AS_OF DATE)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
DECLARE
    day_path VARCHAR;
    flat_rows NUMBER;
    country_rows NUMBER;
    redemption_rows NUMBER;
    failed_count NUMBER;
    flat_file VARCHAR;
    country_file VARCHAR;
    redemption_file VARCHAR;
BEGIN
    day_path := TO_VARCHAR(:AS_OF, 'YYYY-MM-DD');
    flat_file := 'members_' || TO_VARCHAR(:AS_OF, 'YYYYMMDD') || '.txt';
    country_file := 'country_extract_' || TO_VARCHAR(:AS_OF, 'YYYYMMDD') || '.csv';
    redemption_file := 'redemptions_' || TO_VARCHAR(:AS_OF, 'YYYYMMDD') || '.json';

    DELETE FROM bronze.schema_audit WHERE load_date = :AS_OF;

    flat_rows := (SELECT COUNT(*) FROM bronze.member_flat_raw WHERE load_date = :AS_OF AND record_type = 'D');
    country_rows := (SELECT COUNT(*) FROM bronze.country_extract_raw WHERE load_date = :AS_OF);
    redemption_rows := (SELECT COUNT(*) FROM bronze.redemption_raw WHERE load_date = :AS_OF);

    CREATE OR REPLACE TEMPORARY TABLE _schema_cols (
        feed VARCHAR,
        source_file VARCHAR,
        column_position NUMBER,
        column_name VARCHAR,
        data_type VARCHAR
    );
    CREATE OR REPLACE TEMPORARY TABLE _schema_header (line VARCHAR);

    IF (flat_rows = 0) THEN
        INSERT INTO bronze.schema_audit (
            checked_at, load_date, feed, source_file, column_position, column_name, data_type, change
        )
        VALUES (CURRENT_TIMESTAMP(), :AS_OF, 'members_flat', :flat_file, NULL, '(file)', 'TEXT', 'FAILED');
    ELSE
        DELETE FROM _schema_header;
        EXECUTE IMMEDIATE
            'INSERT INTO _schema_header '
            || 'SELECT $1 FROM @bronze.skypoints_stage/members_flat/' || :day_path || '/ '
            || '(FILE_FORMAT => ''bronze.ff_line'') '
            || 'QUALIFY ROW_NUMBER() OVER (ORDER BY METADATA$FILE_ROW_NUMBER) = 1';
        INSERT INTO _schema_cols
        SELECT 'members_flat', :flat_file,
               ROW_NUMBER() OVER (ORDER BY f.index),
               TRIM(f.value::VARCHAR),
               'TEXT'
        FROM _schema_header h,
             LATERAL FLATTEN(input => SPLIT(h.line, '|')) f
        WHERE TRIM(f.value::VARCHAR) <> ''
          AND UPPER(TRIM(f.value::VARCHAR)) <> 'H';
        IF ((SELECT COUNT(*) FROM _schema_cols WHERE feed = 'members_flat') = 0) THEN
            INSERT INTO bronze.schema_audit (
                checked_at, load_date, feed, source_file, column_position, column_name, data_type, change
            )
            VALUES (CURRENT_TIMESTAMP(), :AS_OF, 'members_flat', :flat_file, NULL, '(header)', 'TEXT', 'FAILED');
        END IF;
    END IF;

    IF (country_rows = 0) THEN
        INSERT INTO bronze.schema_audit (
            checked_at, load_date, feed, source_file, column_position, column_name, data_type, change
        )
        VALUES (CURRENT_TIMESTAMP(), :AS_OF, 'country_xlsx', :country_file, NULL, '(file)', 'TEXT', 'FAILED');
    ELSE
        DELETE FROM _schema_header;
        EXECUTE IMMEDIATE
            'INSERT INTO _schema_header '
            || 'SELECT $1 FROM @bronze.skypoints_stage/country_xlsx/' || :day_path || '/ '
            || '(FILE_FORMAT => ''bronze.ff_line'') '
            || 'QUALIFY ROW_NUMBER() OVER (ORDER BY METADATA$FILE_ROW_NUMBER) = 1';
        INSERT INTO _schema_cols
        SELECT 'country_xlsx', :country_file,
               ROW_NUMBER() OVER (ORDER BY f.index),
               TRIM(f.value::VARCHAR),
               'TEXT'
        FROM _schema_header h,
             LATERAL FLATTEN(input => SPLIT(h.line, ',')) f
        WHERE TRIM(f.value::VARCHAR) <> '';
        IF ((SELECT COUNT(*) FROM _schema_cols WHERE feed = 'country_xlsx') = 0) THEN
            INSERT INTO bronze.schema_audit (
                checked_at, load_date, feed, source_file, column_position, column_name, data_type, change
            )
            VALUES (CURRENT_TIMESTAMP(), :AS_OF, 'country_xlsx', :country_file, NULL, '(header)', 'TEXT', 'FAILED');
        END IF;
    END IF;

    IF (redemption_rows = 0) THEN
        INSERT INTO bronze.schema_audit (
            checked_at, load_date, feed, source_file, column_position, column_name, data_type, change
        )
        VALUES (CURRENT_TIMESTAMP(), :AS_OF, 'redemptions', :redemption_file, NULL, '(file)', 'TEXT', 'FAILED');
    ELSE
        INSERT INTO _schema_cols
        SELECT 'redemptions', :redemption_file,
               ROW_NUMBER() OVER (ORDER BY column_name),
               column_name,
               data_type
        FROM (
            SELECT column_name,
                   IFF(COUNT(DISTINCT data_type) > 1, 'MIXED', MIN(data_type)) AS data_type
            FROM (
                SELECT k.value::VARCHAR AS column_name,
                       TYPEOF(GET(br.payload, k.value)) AS data_type
                FROM bronze.redemption_raw br,
                     LATERAL FLATTEN(input => OBJECT_KEYS(br.payload)) k
                WHERE br.load_date = :AS_OF
                UNION ALL
                SELECT 'redemptions.' || k.value::VARCHAR,
                       TYPEOF(GET(r.value, k.value))
                FROM bronze.redemption_raw br,
                     LATERAL FLATTEN(input => br.payload:redemptions) r,
                     LATERAL FLATTEN(input => OBJECT_KEYS(r.value)) k
                WHERE br.load_date = :AS_OF
            )
            GROUP BY column_name
        );
    END IF;

    INSERT INTO bronze.schema_audit (
        checked_at, load_date, feed, source_file, column_position, column_name, data_type, change
    )
    SELECT
        CURRENT_TIMESTAMP(),
        :AS_OF,
        t.feed,
        t.source_file,
        t.column_position,
        t.column_name,
        t.data_type,
        CASE
            WHEN prev.column_name IS NULL AND NOT EXISTS (
                SELECT 1 FROM bronze.schema_audit s
                WHERE s.feed = t.feed
                  AND s.load_date < :AS_OF
                  AND s.change <> 'FAILED'
            ) THEN 'NEW_FILE'
            WHEN prev.column_name IS NULL THEN 'NEW_COLUMN'
            WHEN prev.data_type <> t.data_type THEN 'TYPE_CHANGED'
            ELSE 'UNCHANGED'
        END
    FROM _schema_cols t
    LEFT JOIN bronze.schema_audit prev
      ON prev.feed = t.feed
     AND prev.column_name = t.column_name
     AND prev.change <> 'FAILED'
     AND prev.load_date = (
         SELECT MAX(s.load_date)
         FROM bronze.schema_audit s
         WHERE s.feed = t.feed
           AND s.load_date < :AS_OF
           AND s.change <> 'FAILED'
     );

    INSERT INTO bronze.schema_audit (
        checked_at, load_date, feed, source_file, column_position, column_name, data_type, change
    )
    SELECT
        CURRENT_TIMESTAMP(),
        :AS_OF,
        prev.feed,
        CASE prev.feed
            WHEN 'members_flat' THEN :flat_file
            WHEN 'country_xlsx' THEN :country_file
            ELSE :redemption_file
        END,
        prev.column_position,
        prev.column_name,
        prev.data_type,
        'MISSING'
    FROM bronze.schema_audit prev
    WHERE prev.change <> 'FAILED'
      AND prev.load_date = (
          SELECT MAX(s.load_date)
          FROM bronze.schema_audit s
          WHERE s.feed = prev.feed
            AND s.load_date < :AS_OF
            AND s.change <> 'FAILED'
      )
      AND EXISTS (
          SELECT 1 FROM _schema_cols t WHERE t.feed = prev.feed
      )
      AND NOT EXISTS (
          SELECT 1 FROM _schema_cols t
          WHERE t.feed = prev.feed AND t.column_name = prev.column_name
      );

    failed_count := (
        SELECT COUNT(*) FROM bronze.schema_audit
        WHERE load_date = :AS_OF AND change = 'FAILED'
    );
    IF (failed_count > 0) THEN
        RETURN 'FAILED ' || :failed_count || ' file(s)';
    END IF;
    RETURN 'PASSED';
END;
$$;
