# Snowflake pipeline

Same rules as the local Python run. This folder is what you execute in Snowflake.

## One-time setup

In a Snowflake worksheet (database `SKYPOINTS`, role that can create schemas):

1. `bronze/bronze_ddl.sql`
2. `bronze/schema_audit.sql`
3. `silver/silver_ddl.sql`
4. `silver/member_typed.sql`
5. `gold/gold_ddl.sql`
6. `setup/stage_and_formats.sql`
7. `setup/load_reference.sql`
8. `bronze/load_day.sql`
9. `bronze/audit_day.sql`
10. `silver/silver_load.sql`
11. `silver/quality_gate.sql`
12. `gold/latest_and_split.sql`
13. `gold/redemptions.sql`
14. `run_pipeline.sql`

Snowflake `COPY` does not read `.xlsx`. The country rows are `snowflake/seed/country_extract_20240115.csv`, the same text the local ingest writes from the three Excel files. The entrypoint copies that file, the flat file, the JSON, and the country lists out of the Git repo.

## Run the pipeline

After the setup files above, run `run_pipeline.sql` once. That creates the entrypoint. Then:

```sql
CALL bronze.run_pipeline();
```

No date means: every source file from `MONITORING_DATE` (2024-01-15) through yesterday. The procedure copies those files out of the Git repo, loads bronze, and moves to silver only when the bronze audit passes. Gold runs only when the quality checks pass. A day with no file is skipped. A day already finished returns `SKIP`.

To stop at a chosen day instead of yesterday:

```sql
CALL bronze.run_pipeline(DATE '2024-01-15');
```

## What you should see

```sql
SELECT country_code, COUNT(*) FROM gold.member WHERE load_date = DATE '2024-01-15' GROUP BY 1 ORDER BY 1;
-- AUS 3, CAN 1, IND 4, PHL 1, USA 3  (12 members)

SELECT reject_rule, COUNT(*) FROM silver.member_quarantine WHERE load_date = DATE '2024-01-15' GROUP BY 1;
-- Jonnathan and John

SELECT * FROM gold.redemption ORDER BY txn_date;
-- RX10091 and RX10092, both MATCHED

SELECT * FROM silver.quality_report WHERE load_date = DATE '2024-01-15' ORDER BY check_name;
SELECT * FROM gold.pipeline_run WHERE load_date = DATE '2024-01-15';
```

A second `CALL bronze.run_pipeline(DATE '2024-01-15')` returns `SKIP` because `gold.pipeline_run` already has SUCCESS.

## File map

| File | Role |
|---|---|
| `setup/stage_and_formats.sql` | Internal stage and file formats |
| `setup/load_reference.sql` | Load ISO + alias CSVs |
| `bronze/load_day.sql` | COPY files for one day into bronze |
| `bronze/audit_day.sql` | File / schema audit; FAIL blocks silver |
| `silver/member_typed.sql` | Views that parse dates and set reject rules |
| `silver/silver_load.sql` | Fill staging + quarantine |
| `silver/quality_gate.sql` | PASS / WARN / FAIL; FAIL blocks gold |
| `gold/latest_and_split.sql` | Latest row wins into `gold.member` |
| `gold/redemptions.sql` | Flatten JSON and join |
| `run_pipeline.sql` | The daily job: `bronze.run_pipeline` |

`silver/silver_validations.sql` is still the ad-hoc check queries. The gate that stops gold is `quality_gate.sql`.
