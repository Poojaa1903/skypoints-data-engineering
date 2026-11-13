# SkyPoints Member Data Pipeline

Technical assessment for the Data Craftsperson role at Incubyte.

Loads member profiles and partner redemptions, checks them, and writes one table per country. A person who appears in two countries is kept in the latest one only when we can tell it is the same person.

The demo runs in Snowflake. Setup and the one entrypoint are in `snowflake/README.md`.

```sql
CALL bronze.run_pipeline();
```

No date means every source file from 15 Jan 2024 through yesterday. A day with no file is skipped. Bronze must pass before silver. Quality must pass before gold.

On the sample that is 12 members, 2 quarantined rows, and 2 redemptions joined to Elena.

## Decisions

1. **A person is matched across files only when name and date of birth both match.** Country files reuse ids 1, 2 and 3, so `member_id` is unique inside one file only. Same name without a date of birth (Mike) is kept in both countries.
2. **Dates and ids stay text until a format is chosen per file.** Flat-file dates are `YYYYMMDD`. Flat-file DOB and USA dates are `MMDDYYYY`. AUS and IND dates are Excel serials. `1152022` can be two dates, so it is quarantined, not guessed.
3. **Country** on the flat file is mapped with the ISO list, then the alias file (`PHIL` → `PHL`). A code in neither is kept and marked `UNMAPPED`. On the Excel files the country is the file name.
4. **Stale** means more than 90 days since the last flight. Exactly 90 is not stale. No flight date is stale.
5. **A redemption with no member is kept** and marked `ORPHAN`.

## Scale

Files sit in the Git repo and are copied onto a stage. `CALL bronze.run_pipeline()` loads yesterday. JSON is a `VARIANT` flattened with `LATERAL FLATTEN`. Each table records `created_at`, `created_by` and `modified_at`. At more rows you add files and a larger warehouse. You do not rewrite the SQL.
