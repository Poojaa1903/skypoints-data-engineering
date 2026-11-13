# SkyPoints Member Data Pipeline

Technical assessment for the Data Craftsperson role at Incubyte.

Loads member profiles and partner redemptions, checks them, and writes one table per country. A person who appears in two countries is kept in the latest one only when we can tell it is the same person.

## One-time setup

In a SQL worksheet, database `SKYPOINTS`:

1. `bronze/bronze_ddl.sql`
2. `bronze/schema_audit.sql`
3. `silver/silver_ddl.sql`
4. `silver/member_typed.sql`
5. `gold/gold_ddl.sql`
6. `setup/stage_and_formats.sql`
7. `setup/load_config.sql`
8. `setup/load_reference.sql`
9. `bronze/load_day.sql`
10. `silver/silver_load.sql`
11. `silver/quality_gate.sql`
12. `gold/latest_and_split.sql`
13. `gold/redemptions.sql`
14. `run_pipeline.sql`

Paths and quality limits are in `config/pipeline.env`. Change them there. The next `CALL bronze.run_pipeline()` reloads the file.

Snowflake cannot read `.xlsx`. The country rows are `seed/country_extract_20240115.csv`.

## Run

```sql
CALL bronze.run_pipeline();
```

No date means every source file from 15 Jan 2024 through yesterday. A day with no file is skipped. Bronze must pass before silver. Quality must pass before gold.

On the sample that is 12 members, 2 quarantined rows, and 2 redemptions joined to Elena.

## Decisions

1. **A person is matched across files only when name and date of birth both match.** Country files reuse ids 1, 2 and 3, so `member_id` is unique inside one file only. Same name without a date of birth (Mike) is kept in both countries.
2. **Dates and ids stay text until silver parses them.** Flat-file dates are `YYYYMMDD`. Flat-file DOB and USA dates are `MMDDYYYY`. AUS and IND dates are Excel serials. `1152022` can be two dates, so it is quarantined, not guessed.
3. **Country** on the flat file is mapped with the ISO list, then the alias file (`PHIL` → `PHL`). A code in neither is kept and marked `UNMAPPED`. On the Excel files the country is the file name.
4. **Stale** means more than 90 days since the last flight. Exactly 90 is not stale. No flight date is stale.
5. **A redemption with no member is kept** and marked `ORPHAN`.
