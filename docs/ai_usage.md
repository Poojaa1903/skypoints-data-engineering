# How AI was used

Cursor was used to draft code, tests and SQL. I checked every result against the sample files before keeping it. Three corrections matter:

1. **Country identity.** Merging on `member_id` looked right from the brief and dropped 6 of the 9 Excel rows, because ids 1, 2 and 3 repeat in every country. The rule is now: match across files only when name and date of birth both match. Mike stays in both countries and goes to a review file.

2. **A test that was wrong.** The month-13 test used `20131013`, which is 13 October 2013, a real date. The case is `20121313`.

3. **Ambiguous USA dates.** `1152022` is 15 January or 5 November. The first draft would have picked one. Those rows are quarantined instead.

AI output was not kept until it matched the sample files.
