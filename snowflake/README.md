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

## Upload the sample files

From your laptop, in the project root, with [SnowSQL](https://docs.snowflake.com/en/user-guide/snowsql):

```bash
snowsql -a <account> -u <user> -d SKYPOINTS -s PUBLIC

PUT file://config/iso_countries.csv @bronze.skypoints_stage/reference/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE;
PUT file://config/country_aliases.csv @bronze.skypoints_stage/reference/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE;
PUT file://data/members_20240115.txt @bronze.skypoints_stage/members_flat/2024-01-15/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE;
PUT file://data/redemptions_20240115.json @bronze.skypoints_stage/redemptions/2024-01-15/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE;
PUT file://snowflake/seed/country_extract_20240115.csv @bronze.skypoints_stage/country_xlsx/2024-01-15/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE;
```

Snowflake `COPY` does not read `.xlsx`. The seed CSV is the same text the local ingest writes from `AUS.xlsx`, `IND.xlsx` and `USA.xlsx`. In production an ingest job or Snowpark step would produce that shape.

## Load the country lists, then run the day

```sql
CALL silver.load_reference();
CALL bronze.run_pipeline(DATE '2024-01-15');
```

That one call is the whole pipeline: bronze → audit → silver → quality → gold.

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
