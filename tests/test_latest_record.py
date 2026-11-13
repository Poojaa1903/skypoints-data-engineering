"""Tests for "latest record wins" when a member appears in more than one country.

Each member_id must end up with exactly one winning record. Every other
record for that member is reported as superseded, so the gold load can
remove it from the old country table.

Ranking, most important first:

1. Latest last_flight_date. If it is missing, enrollment_date is used.
2. Later file_date (the feed the record came from).
3. Higher row_num (later row in the same file).

Member IDs are compared as text. They are never converted to numbers.
"""

from datetime import date

from gold.latest import MemberRecord, pick_latest


def rec(member_id, country, *, flight=None, enrolled=date(2020, 1, 1),
        file_date=date(2024, 1, 15), row_num=1, source="file.txt"):
    return MemberRecord(
        member_id=member_id,
        country_code=country,
        last_flight_date=flight,
        enrollment_date=enrolled,
        file_date=file_date,
        row_num=row_num,
        source_file=source,
    )


def test_single_record_is_the_winner():
    result = pick_latest([rec("223457", "USA", flight=date(2024, 1, 1))])
    assert result.winners["223457"].country_code == "USA"
    assert result.superseded == []


def test_member_in_two_countries_keeps_the_latest_flight():
    # Mike from the Excel files. AUS last flew 2022-08-01, USA 2021-12-30.
    aus = rec("M1", "AUS", flight=date(2022, 8, 1), source="AUS.xlsx")
    usa = rec("M1", "USA", flight=date(2021, 12, 30), source="USA.xlsx")

    result = pick_latest([usa, aus])

    assert result.winners["M1"].country_code == "AUS"
    assert [r.country_code for r in result.superseded] == ["USA"]


def test_order_of_input_does_not_change_the_winner():
    aus = rec("M1", "AUS", flight=date(2022, 8, 1))
    usa = rec("M1", "USA", flight=date(2021, 12, 30))

    assert pick_latest([aus, usa]).winners["M1"].country_code == "AUS"
    assert pick_latest([usa, aus]).winners["M1"].country_code == "AUS"


def test_same_flight_date_uses_later_file_date():
    older = rec("M2", "IND", flight=date(2022, 3, 1), file_date=date(2024, 1, 14))
    newer = rec("M2", "USA", flight=date(2022, 3, 1), file_date=date(2024, 1, 15))

    assert pick_latest([older, newer]).winners["M2"].country_code == "USA"


def test_same_flight_and_file_date_uses_higher_row_number():
    first = rec("M3", "IND", flight=date(2022, 3, 1), row_num=4)
    second = rec("M3", "PHL", flight=date(2022, 3, 1), row_num=9)

    assert pick_latest([first, second]).winners["M3"].country_code == "PHL"


def test_missing_flight_date_falls_back_to_enrollment_date():
    # No flight date on A, so its enrollment (2022-01-01) is used.
    # B's flight (2021-12-01) is older, so A wins.
    a = rec("M4", "AUS", flight=None, enrolled=date(2022, 1, 1))
    b = rec("M4", "USA", flight=date(2021, 12, 1), enrolled=date(2019, 5, 5))

    assert pick_latest([a, b]).winners["M4"].country_code == "AUS"


def test_each_member_gets_exactly_one_winner():
    records = [
        rec("A", "USA", flight=date(2024, 1, 1)),
        rec("A", "AUS", flight=date(2023, 1, 1)),
        rec("B", "IND", flight=date(2024, 1, 1)),
        rec("C", "PHL", flight=date(2024, 1, 1)),
        rec("C", "CAN", flight=date(2021, 1, 1)),
        rec("C", "AUS", flight=date(2020, 1, 1)),
    ]

    result = pick_latest(records)

    assert set(result.winners) == {"A", "B", "C"}
    assert len(result.superseded) == 3
    assert {r.country_code for r in result.superseded} == {"AUS", "CAN"}
