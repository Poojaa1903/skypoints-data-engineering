# Data quality findings

What is wrong in the sample, and what the pipeline does with it.

| Finding | Where | What the pipeline does |
|---|---|---|
| Spec marks Member Name as the key | brief | Name is not unique. Inside one file the key is `member_id`. Across files a person is name + date of birth. |
| Spec lists Post Code; the file has no Post Code | brief | Column is not created. |
| DOB `03051985` became `3051985` in the sample staging table | brief | Stored as text until parsed, so the leading zero stays. |
| `Agent_Name` blank in the sample staging table | brief | Kept when the file has it (`Sam` on every flat-file row). |
| Staging column named `County` | brief | Named `country_code`. |
| `AU`, `USA`, `PHIL` mixed | flat file | ISO list, then alias file. `AU` → `AUS`, `PHIL` → `PHL`. |
| Different columns and date formats per country file | xlsx | One header map in `ingest.py`. Date format chosen per file. |
| `2021-13-13` | AUS.xlsx | Quarantine, rule `ENROLLMENT_DATE_INVALID`. |
| Text `NULL` in DOB | AUS.xlsx | Treated as missing. Age is blank. Row still loads. |
| `1052022` and `1152022` | USA.xlsx | Each can be two real dates. Quarantine, rule `..._AMBIGUOUS`. |
| Ids 1, 2, 3 in every country file | xlsx | Not merged. Each id is scoped to its file. |
| Mike in AUS and USA, DOB missing on one side | xlsx | Kept in both countries. One row in `review_possible_moves.csv`. |
| Same `txn_id` on a later day | JSON design | Latest `feed_date` wins. |
| Redemption for a member not in the file yet | JSON design | Kept, `match_status = ORPHAN`. |
