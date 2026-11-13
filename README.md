# SkyPoints Member Data Pipeline

Technical assessment for the Data Craftsperson role at Incubyte.

Loads member profiles and partner redemptions, checks them, and writes one table per country. A person who appears in two countries is kept in the latest one only when we can tell it is the same person.

## How to run

```bash
make setup
make test
make run
```

`make run` restores every file from `MONITORING_DATE` in `config/paths.env` through yesterday. It copies what is missing into `outputs/bronze/<date>/`, then writes `outputs/silver/<date>/` and `outputs/gold/<date>/`. A day that is already complete is skipped. A day with no file is not a gap. The sample monitoring date is `2024-01-15`.

On the sample files the run writes 5 country tables (12 members), 2 quarantined rows, 1 review row (Mike), and 2 redemptions joined to Elena.

## What runs where

- **Python** (`src/bronze/`, `src/silver/`, `src/gold/`, `make run`) is the pipeline you can run and demo. `make test` covers it.
- **Snowflake SQL** (`sql/`) is the same design for production: landing tables, staging load with age and the stale flag, latest-record split, redemption flatten, and validation queries. These need a Snowflake account, so they are not what `make test` runs.
- **DuckDB** (`tests/test_sql_rules.py`) runs the shared expressions (age, stale, latest row, JSON flatten) so those rules are tested without a warehouse.

## Approach

- **Bronze** (`outputs/bronze/<date>/`): raw text, never changed. JSON kept whole. `file_audit.csv` logs every file. `schema_audit.csv` logs each column name and type, and a change when a column is new, missing, or a different type. A file that fails these checks does not go to silver.
- **Silver** (`outputs/silver/<date>/`): typed rows, age, stale flag. A bad row (invalid date, missing name) goes to quarantine. The rest of that file still loads.
- **Gold** (`outputs/gold/<date>/`): one table per country and the review list, for the file date. A redemption is filed under its transaction date, so a file from 24 Nov that contains a 25 Nov transaction creates the 25 Nov folder.

## Decisions

1. **A person is matched across files only when name and date of birth both match.** Country files reuse ids 1, 2 and 3, so `member_id` is unique inside one file only. Same name without a date of birth (Mike) is listed in `review_possible_moves.csv` and kept in both countries.
2. **Dates and ids stay text until a format is chosen per file.** Flat-file dates are `YYYYMMDD`. Flat-file DOB and USA dates are `MMDDYYYY`. AUS and IND dates are Excel serials. `1152022` can be two dates, so it is quarantined, not guessed.
3. **Country** on the flat file is mapped with the ISO list, then the alias file (`PHIL` → `PHL`). A code in neither is kept and marked `UNMAPPED`. On the Excel files the country is the file name.
4. **Stale** means more than 90 days since the last flight, from the run date passed in. Exactly 90 is not stale. No flight date is stale.
5. **A redemption with no member is kept** and marked `ORPHAN`.

## Data problems the pipeline catches

- Invalid date `2021-13-13` (Jonnathan) and ambiguous USA dates (John) go to quarantine.
- `NULL` text in a date is a missing value, not a crash.
- `03051985` keeps its leading zero.
- `AU` becomes `AUS`. `PHIL` becomes `PHL`.
- Duplicate ids are checked per file, not across countries.

## Moving to Snowflake

The rules stay the same. Files move to cloud storage under the same date prefix (`.../2024-01-15/`), `COPY INTO` or Snowpipe loads them, and a daily task runs for yesterday. JSON is a `VARIANT` flattened with `LATERAL FLATTEN` (`sql/gold/06_redemptions.sql`). Each table records `created_at`, `created_by` and `modified_at`. At billions of rows you add files and a larger warehouse. You do not rewrite the SQL.
