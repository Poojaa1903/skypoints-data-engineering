# Data quality findings

What is wrong in the sample, and what the pipeline does with it. The sample day is 15 Jan 2024.

| Finding | Where | What the pipeline does |
|---|---|---|
| Spec marks Member Name as the key | brief | Name is not unique. Inside one file the key is `member_id`. Across files a person is name plus date of birth. |
| Spec lists Post Code; the file has no Post Code | brief | Column is not created. |
| DOB `03051985` became `3051985` in the sample staging table | brief | Stored as text until parsed, so the leading zero stays. |
| `Agent_Name` blank in the sample staging table | brief | Kept when the file has it (`Sam` on every flat-file row). |
| Staging column named `County` | brief | Named `country_code`. |
| `AU`, `USA`, `PHIL` mixed | flat file | ISO list, then alias file. `AU` becomes `AUS`, `PHIL` becomes `PHL`. |
| Different columns and date formats per country file | xlsx | `seed/country_extract_20240115.csv` uses one column set. `silver/member_typed.sql` parses each country. |
| `2021-13-13` | AUS.xlsx, Jonnathan | Quarantine, rule `ENROLLMENT_DATE_INVALID`. |
| Text `NULL` in DOB | AUS.xlsx, Mike | Treated as missing. Age is blank. The row still loads. |
| `1052022` and `1152022` | USA.xlsx, John | Each can be two real dates. Quarantine, rule `ENROLLMENT_DATE_AMBIGUOUS`. His flight dates are the same kind of value. The enrollment rule is reported because it is checked first. |
| Ids 1, 2, 3 in every country file | xlsx | Not merged. Each id is scoped to its file. |
| Mike in AUS and USA, date of birth missing on one side | xlsx | Kept in both countries. Gold has two rows for Mike. |
| Same `txn_id` on a later day | JSON design | Latest `feed_date` wins. |
| Redemption for a member not in the flat file | JSON design | Kept, `match_status` = `ORPHAN`. |
| Same `member_id` twice in one file on one day | rule, not in the sample | Quarantine, rule `DUPLICATE_MEMBER_ID`. The quality gate FAILs and gold is skipped. The same id in two country files is not a duplicate. |
| Last flight after the file date | rule, not in the sample | Quarantine, rule `FLIGHT_DATE_IN_FUTURE`. The quality gate FAILs. |

## What the sample run produced

| Output | Count |
|---|---|
| `gold.member` | 12. AUS 3, IND 4, USA 3, CAN 1, PHL 1 |
| `silver.member_quarantine` | 2. Jonnathan `ENROLLMENT_DATE_INVALID`, John `ENROLLMENT_DATE_AMBIGUOUS` |
| `gold.redemption` | 2. RX10091 and RX10092, both `MATCHED` to member 223457, USA |
| Elena, flat file 223457 | Age 38, stale. Last flight 13 Oct 2012, file date 15 Jan 2024 |
| Mateo, 223459 | `PHL`, status `ALIAS` |

`tests.run_checks` returned `PASS 23 checks` on this result. That includes a throwaway day that proves the duplicate-id rule, the future-flight rule, and latest-record-wins. Those rows are deleted before the procedure returns.

## Gate versus hand queries

The daily gate is `silver.quality_gate`. It writes `silver.quality_report`. A `FAIL` skips gold for that day. Limits are in `config/pipeline.env`.

`silver/silver_validations.sql` repeats the checks as queries for a worksheet. The pipeline does not call it. Each query should return no rows after a good load.
