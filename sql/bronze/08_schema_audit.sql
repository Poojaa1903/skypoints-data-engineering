-- Schema and file audit. This is the CDC log for files and columns.
-- Dialect: Snowflake.
--
-- file_audit: one row per file. NEW_FILE, UNCHANGED, SCHEMA_CHANGED, FAILED.
-- schema_audit: one row per column. NEW_FILE, NEW_COLUMN, TYPE_CHANGED,
-- UNCHANGED, MISSING.
--
-- A file with status FAILED is not loaded into silver. The raw copy
-- stays in bronze so the failure can be inspected.

CREATE TABLE IF NOT EXISTS bronze.file_audit (
    checked_at         TIMESTAMP_LTZ NOT NULL,
    load_date          DATE          NOT NULL,
    feed               VARCHAR       NOT NULL,
    source_file        VARCHAR       NOT NULL,
    sha256             VARCHAR       NOT NULL,
    status             VARCHAR       NOT NULL,
    row_count          NUMBER,
    column_count       NUMBER,
    detail             VARCHAR,
    created_at         TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
    created_by         VARCHAR       DEFAULT CURRENT_USER(),
    modified_at        TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY (load_date);

CREATE TABLE IF NOT EXISTS bronze.schema_audit (
    checked_at         TIMESTAMP_LTZ NOT NULL,
    load_date          DATE          NOT NULL,
    feed               VARCHAR       NOT NULL,
    source_file        VARCHAR       NOT NULL,
    column_position    NUMBER,
    column_name        VARCHAR       NOT NULL,
    data_type          VARCHAR       NOT NULL,   -- TEXT / NUMBER / EMPTY / ARRAY / OBJECT / MIXED
    change             VARCHAR       NOT NULL,   -- NEW_FILE / NEW_COLUMN / TYPE_CHANGED / UNCHANGED / MISSING
    created_at         TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
    created_by         VARCHAR       DEFAULT CURRENT_USER(),
    modified_at        TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY (load_date, feed);
