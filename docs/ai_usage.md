# How AI was used

Cursor was used to draft the SQL, the tests, and these docs. Every result was checked against the sample files before it was kept. Three corrections matter.

1. **Country identity.** Merging on `member_id` looked right from the brief and dropped 6 of the 9 Excel rows, because ids 1, 2, and 3 repeat in every country. The rule is now: match across files only when name and date of birth both match. Mike stays in both countries. Gold has two rows for him. There is no separate review file.

2. **A date that looked invalid and was not.** The month-13 test used `20131013`, which is 13 October 2013, a real date. The invalid case in the sample is `2021-13-13` on Jonnathan's enrollment date.

3. **Ambiguous USA dates.** `1152022` is 15 January or 5 November. `1052022` is 5 January or 5 October. The first draft would have picked one. Those rows are quarantined. John in USA.xlsx is the sample row.

The checks in `tests/run_checks.sql` cover these rules and the sample counts. On the loaded day they returned `PASS 23 checks`.
