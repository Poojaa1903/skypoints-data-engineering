# SkyPoints Member Data Pipeline

Technical assessment for the Data Craftsperson role at Incubyte.

Loads member profiles and partner redemptions, cleans them, checks them, and splits members into one table per country. A member who moved countries is kept only in their latest country.

## Approach

- **Medallion layers**
  - **Bronze:** raw data as received, all text, never changed.
  - **Silver:** cleaned data with proper types, age, and a stale flag.
  - **Gold:** final member tables, one per country.
- **Bad rows go to a quarantine table** with the reason. They do not stop the run.
- **DuckDB runs the pipeline locally.** It needs no account and no network, so tests and the interview demo work offline. The SQL is written for Snowflake. DuckDB is only the engine that runs it on the sample data.

## Key decisions

1. **`member_id` is the key, not `member_name`.** Names are not unique.
2. **IDs and dates are stored as text** so leading zeros are not lost.
3. **Each country file is read with its own date format.** Formats differ by country.
4. **Country comes from the file name**, because the files have no country column.
5. **Stale means more than 90 days since the last flight**, measured from a fixed run date, so results are repeatable.
6. **Redemptions with no matching member are kept and flagged**, not deleted.

## Data problems found

- The spec says `Member Name` is the key. It should be `Member ID`.
- The spec has a `Post Code` column that the sample data does not have.
- DOB `03051985` lost its leading zero and became `3051985`.
- `Agent_Name` is blank in most staging rows.
- The staging column is named `County`, not `Country`.
- Country codes mix formats (`USA`, `IND`, `AU`, `PHIL`, `CAN`).
- Each country file has different column names and date formats.
- AUS has an invalid date (`2021-13-13`) and the text `NULL` in DOB.
- IDs 1, 2, 3 repeat in every country file, so they are not unique across countries.
- `Mike` appears in AUS and USA. The files cannot prove it is the same person.

## Repo layout

```
data/input/     sample files from the assessment
config/         country codes and source column mappings
sql/            Snowflake SQL: tables, loads, country split, checks
src/            Python: read files, run SQL, write logs
tests/          pytest tests
docs/           notes and AI usage
```

## How to run

Coming with the pipeline commit:

```bash
make test
make run
```

## Moving to Snowflake

The business rules stay the same. Only the engine and file location change.

1. Create a Snowflake database with bronze, silver and gold schemas.
2. Move the daily files to cloud storage (S3, GCS or Azure).
3. Load files with `COPY INTO`, or Snowpipe for automatic loads.
4. Store raw JSON in a `VARIANT` column and flatten it with `LATERAL FLATTEN`.
5. Process only new rows with Streams and Tasks.
6. Use `MERGE` so rerunning a file does not create duplicates.
7. Run the same checks after each load.

At billions of rows, the SQL stays the same. You add files and a bigger warehouse.
