# SkyPoints Member Data Pipeline

Technical assessment for the Data Craftsperson role at Incubyte.

SkyPoints sends two feeds a day: a flat file of members and a JSON file of mileage redemptions, plus country Excel extracts. This pipeline lands the files unchanged, cleans them, and writes one country view per country. It runs in Snowflake. One call does a day:

```sql
CALL bronze.run_pipeline(DATE '2024-01-15');
```

The sample day has been run. Tests returned `PASS 23 checks`.

## What the brief asked for

| # | Asked for | Where | Result on 15 Jan 2024 |
|---|---|---|---|
| 1 | DDL for raw, staging, and country tables | `bronze/bronze_ddl.sql`, `silver/silver_ddl.sql`, `gold/gold_ddl.sql` | Tables and views created in Snowflake |
| 2 | Staging columns Age and Stale_Member | `silver/silver_load.sql` | Elena is age 38 and stale |
| 3 | Split by country, latest record wins | `gold/latest_and_split.sql` and the country views | AUS 3, IND 4, USA 3, CAN 1, PHL 1 |
| 4 | Flatten the JSON and join it to members | `gold/redemptions.sql` | RX10091 and RX10092 both `MATCHED` to member 223457, USA |
| 5 | Validations: mandatory fields, key uniqueness, sample defects | `silver/member_typed.sql`, `silver/quality_gate.sql` | John and Jonnathan quarantined. Duplicate-id and future-flight checks `PASS` |

Country targets are views (`gold.table_usa`, `gold.table_ind`, `gold.table_aus`, `gold.table_phl`, `gold.table_can`) over one table, `gold.member`. A new country is a new view. One clustered table holds a large day.

## How a day runs

`run_pipeline.sql` is the only entrypoint.

1. `setup/load_config.sql` reads `config/pipeline.env`.
2. `setup/load_reference.sql` loads the ISO country list and the alias file.
3. The day's files are copied onto the stage.
4. `bronze/load_day.sql` lands them as text. Nothing is cleaned yet.
5. `bronze/schema_audit.sql` compares columns with the previous day. Zero rows is `FAILED` and silver does not run.
6. `silver/silver_load.sql` reads `silver/member_typed.sql`. Good rows go to `silver.member_stg` with age and the stale flag. Bad rows go to `silver.member_quarantine`.
7. `silver/quality_gate.sql` scores the day. Any `FAIL` skips gold for that day only.
8. `gold/latest_and_split.sql` keeps one row per person. `gold/redemptions.sql` flattens the JSON and joins it to flat-file members.
9. The day is stored in `gold.pipeline_run` as `SUCCESS`. The next call skips it.

No date means every file from `MONITORING_DATE` (15 Jan 2024) through yesterday. A day with no file is skipped. A failed day does not stop later days.

`silver/silver_validations.sql` is not called. Those are the same checks as queries you can run by hand.

## One-time setup

In a worksheet, database `SKYPOINTS`. Run each file once, in order. The Git stage name below is the one in `config/pipeline.env`.

```sql
ALTER GIT REPOSITORY SKYPOINTS.PUBLIC."skypoints-data-engineering" FETCH;
```

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
15. `tests/run_checks.sql`

Snowflake cannot read `.xlsx`. The country rows are `seed/country_extract_20240115.csv`, copied from `data/AUS.xlsx`, `data/IND.xlsx`, and `data/USA.xlsx`.

## Run

Run the sample day first:

```sql
DELETE FROM gold.pipeline_run WHERE load_date = DATE '2024-01-15';
CALL bronze.run_pipeline(DATE '2024-01-15');
```

Then the checks:

```sql
CALL tests.run_checks();
```

`PASS 23 checks` is the expected return. A failure names the checks. Details are in `tests.check_result`.

A later call with no date fills any new file through yesterday:

```sql
CALL bronze.run_pipeline();
```

## Sample result for 15 Jan 2024

| Check | Expected |
|---|---|
| Gold members | 12. AUS 3, IND 4, USA 3, CAN 1, PHL 1 |
| Quarantine | 2. Jonnathan in AUS.xlsx, `ENROLLMENT_DATE_INVALID`. John in USA.xlsx, `ENROLLMENT_DATE_AMBIGUOUS` |
| Redemptions | RX10091 and RX10092, both `MATCHED` to 223457, USA |
| Elena (flat file 223457) | Age 38, stale, because her last flight was 13 Oct 2012 |
| Mateo (223459) | Country `PHL`, status `ALIAS` (`PHIL` in the file) |
| Mike | One row in AUS and one in USA. The USA row has no date of birth, so they are not the same person |

## Settings

Edit `config/pipeline.env` only. The next pipeline call reloads it.

| Setting | Meaning | Current value |
|---|---|---|
| `SOURCE_STAGE` | Git repository stage | `@SKYPOINTS.PUBLIC."skypoints-data-engineering"/branches/dev` |
| `INTERNAL_STAGE` | Stage the COPY commands read | `@bronze.skypoints_stage` |
| `DATA_DIR` | Folder of the flat file and the JSON | `data` |
| `SEED_DIR` | Folder of the country CSV | `seed` |
| `CONFIG_DIR` | Folder of the lookups and this env file | `config` |
| `MONITORING_DATE` | First day a call with no date will load | `2024-01-15` |
| `REJECT_WARN` | Reject rate that warns | `0.02` |
| `REJECT_FAIL` | Reject rate that fails, once the file has at least `REJECT_MIN_ROWS` | `0.05` |
| `REJECT_MIN_ROWS` | Smaller files warn instead of fail | `20` |
| `UNMAPPED_FAIL` | Share of loaded rows with an unknown country | `0.01` |
| `ROW_DROP_FAIL` | Drop versus the previous day | `0.50` |
| `NULL_FAIL` | Share of staged rows missing a mandatory field | `0.01` |

The sample files are under 20 rows, so the AUS and USA reject rates warn and gold still runs.

## Files

**Inputs**

| File | Role |
|---|---|
| `data/members_20240115.txt` | Pipe-delimited member file. Header plus five detail rows |
| `data/redemptions_20240115.json` | One member, two redemption transactions |
| `data/AUS.xlsx`, `data/IND.xlsx`, `data/USA.xlsx` | Country extracts. Snowflake does not read these |
| `seed/country_extract_20240115.csv` | The three Excel files as CSV, which Snowflake does read |
| `config/iso_countries.csv` | ISO country codes. `AU` becomes `AUS` |
| `config/country_aliases.csv` | Extra names. `PHIL` becomes `PHL` |
| `config/pipeline.env` | Paths and quality limits |

**Setup, run once**

| File | Role |
|---|---|
| `bronze/bronze_ddl.sql` | Raw tables. Every business column is text, so leading zeros stay |
| `bronze/schema_audit.sql` | Column-change log, and the procedure that compares today with yesterday |
| `silver/silver_ddl.sql` | Cleaned members, quarantine, quality report, country lookups |
| `silver/member_typed.sql` | Date parsing, country mapping, and the reject rules |
| `gold/gold_ddl.sql` | `gold.member`, one view per country, redemptions, pipeline run log |
| `setup/stage_and_formats.sql` | Internal stage and the pipe, JSON, CSV, and env file formats |
| `setup/load_config.sql` | Loads `pipeline.env` into `bronze.pipeline_config` |
| `setup/load_reference.sql` | Loads the ISO list and the alias file |

**Called for each day**

| File | Role |
|---|---|
| `run_pipeline.sql` | Entrypoint. Calls the steps below |
| `bronze/load_day.sql` | Copies one day into the raw tables |
| `silver/silver_load.sql` | Writes age, the stale flag, and quarantine |
| `silver/quality_gate.sql` | PASS, WARN, or FAIL. A FAIL skips gold |
| `gold/latest_and_split.sql` | One row per person, then the country views show their slice |
| `gold/redemptions.sql` | One row per transaction, joined to the flat-file member |
| `tests/run_checks.sql` | The 23 checks. Not part of the daily call |

`silver/silver_validations.sql` is a worksheet of the same checks. The pipeline does not call it.

## Rules

1. **A person is the same across files only when name and date of birth both match.** Country files reuse ids 1, 2, and 3, so `member_id` is unique inside one file only. Mike has no date of birth on one side, so he stays in both countries.
2. **Latest record wins** when that match is true. Rank is the latest flight date, then the enrollment date if the flight is missing, then the later file date, then the higher row number. The tests insert a person in AUS and USA on a throwaway day and keep the USA row, which has the later flight.
3. **Dates stay text until silver.** Flat-file dates are `YYYYMMDD`. Flat-file date of birth and USA dates are `MMDDYYYY`. AUS and IND dates are Excel serials counted from 1899-12-30. A 7-digit USA date that can be two real dates (`1052022`, `1152022`) is quarantined, not guessed.
4. **Country** on the flat file is mapped with the ISO list, then the alias file. A code in neither is kept and marked `UNMAPPED`. On the Excel files the country is the file name.
5. **Stale** means more than 90 days since the last flight, measured on the file date. Exactly 90 is not stale. A missing flight date is stale.
6. **A redemption with no matching flat-file member is kept** and marked `ORPHAN`. The join key is `member_id` as text, and only against flat-file members, because country-file ids are not global.
7. **Reject rules**, in the order they are applied: `MEMBER_ID_MISSING`, `MEMBER_NAME_MISSING`, `COUNTRY_MISSING`, `ENROLLMENT_DATE_AMBIGUOUS`, `ENROLLMENT_DATE_INVALID`, `FLIGHT_DATE_AMBIGUOUS`, `DUPLICATE_MEMBER_ID`, `FLIGHT_DATE_IN_FUTURE`. A duplicate is the same `member_id` twice in one file on one day. The same id in two country files is not a duplicate.

## Quality gate

`silver.quality_report` gets one row per check. Any `FAIL` skips gold for that day.

| Check | Fail when |
|---|---|
| `reconciliation` | Loaded rows plus quarantined rows do not equal the rows read |
| `reject_rate` | Rejected share is above `REJECT_FAIL` and the file has at least `REJECT_MIN_ROWS`. Smaller files warn |
| `unmapped_countries` | Unknown-country share is above `UNMAPPED_FAIL` |
| `null_mandatory` | Staged rows missing member id, name, country, or enrollment date are above `NULL_FAIL` |
| `key_uniqueness` | Any duplicate `member_id` inside one file |
| `flight_after_load_date` | Any last flight after the file date |
| `row_count` | Member rows dropped more than `ROW_DROP_FAIL` versus the previous day |

## Schema change log

`bronze.schema_audit` stores one row per column per day. `change` is `NEW_FILE`, `NEW_COLUMN`, `MISSING`, `TYPE_CHANGED`, `UNCHANGED`, or `FAILED`.

`FAILED` means that feed landed zero rows, and silver does not run. A new or missing column is recorded and the day continues. Flat and country columns come from the file header. JSON columns come from the keys in the payload, including each field inside a redemption.

## Scale

Files stay in the Git stage or object storage and are copied in. Bronze keeps the raw text. Silver and gold are tables clustered by `load_date`, and `gold.member` is also clustered by `country_code`. The daily procedure loads yesterday. A larger day is a larger warehouse, not a new script per country. A Snowflake stream on the bronze tables would be the next step if only changed rows should move forward. This sample reloads the day.

## Docs

- [Data quality findings](docs/data_quality.md) lists what is wrong in the sample and what the pipeline does with each one.
- [How AI was used](docs/ai_usage.md) lists the corrections made after checking the draft against the files.
