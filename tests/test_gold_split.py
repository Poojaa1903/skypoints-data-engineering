"""Tests for splitting the latest member records into per-country gold tables.

Input: the LatestResult from pick_latest(). It has one winner per member.

Output:
* One table per country, named Table_<CODE> (for example Table_AUS).
  A country that is registered later (UK) gets its own table too.
* Each member appears in exactly one country table.
* removals: for every superseded record in a different country, the
  (member_id, old country) pair that must be deleted from that table.
  That is how a member who moved is removed from the old country.
"""

from datetime import date

import pytest

from skypoints.gold import split_by_country, table_name_for
from skypoints.latest import MemberRecord, pick_latest


def rec(member_id, country, flight, source="file.txt", file_date=date(2024, 1, 15), row_num=1):
    return MemberRecord(
        member_id=member_id,
        country_code=country,
        last_flight_date=flight,
        enrollment_date=date(2020, 1, 1),
        file_date=file_date,
        row_num=row_num,
        source_file=source,
    )


def test_table_name_uses_the_country_code():
    assert table_name_for("IND") == "Table_IND"
    assert table_name_for("AUS") == "Table_AUS"


def test_unregistered_country_still_gets_its_own_table():
    # UK is registered by the country step. It is still a valid table.
    assert table_name_for("UK") == "Table_UK"


def test_each_winner_lands_in_its_country_table():
    result = pick_latest([
        rec("223457", "USA", date(2024, 1, 1)),
        rec("223458", "IND", date(2024, 1, 1)),
    ])

    gold = split_by_country(result)

    assert set(gold.tables) == {"Table_USA", "Table_IND"}
    assert [m.member_id for m in gold.tables["Table_USA"]] == ["223457"]
    assert [m.member_id for m in gold.tables["Table_IND"]] == ["223458"]


def test_member_who_moved_is_only_in_the_winning_country():
    # Mike: AUS last flew 2022-08-01, USA last flew 2021-12-30.
    result = pick_latest([
        rec("M1", "USA", date(2021, 12, 30), source="USA.xlsx"),
        rec("M1", "AUS", date(2022, 8, 1), source="AUS.xlsx"),
    ])

    gold = split_by_country(result)

    assert [m.member_id for m in gold.tables["Table_AUS"]] == ["M1"]
    assert "Table_USA" not in gold.tables


def test_removal_is_reported_for_the_old_country():
    result = pick_latest([
        rec("M1", "USA", date(2021, 12, 30)),
        rec("M1", "AUS", date(2022, 8, 1)),
    ])

    gold = split_by_country(result)

    assert gold.removals == [("M1", "USA")]


def test_no_member_is_in_two_tables():
    result = pick_latest([
        rec("A", "USA", date(2024, 1, 1)),
        rec("A", "AUS", date(2023, 1, 1)),
        rec("B", "IND", date(2024, 1, 1)),
        rec("C", "PHL", date(2024, 1, 1)),
        rec("C", "CAN", date(2021, 1, 1)),
    ])

    gold = split_by_country(result)

    seen = [m.member_id for rows in gold.tables.values() for m in rows]
    assert sorted(seen) == ["A", "B", "C"]
    assert len(seen) == len(set(seen))


def test_no_removal_when_superseded_record_is_in_the_same_country():
    # Two records for the same member in the same country (for example two
    # files on different days). Only the winner is kept, and there is no
    # other table to delete from.
    result = pick_latest([
        rec("M2", "IND", date(2022, 3, 1), file_date=date(2024, 1, 14)),
        rec("M2", "IND", date(2022, 3, 1), file_date=date(2024, 1, 15)),
    ])

    gold = split_by_country(result)

    assert [m.member_id for m in gold.tables["Table_IND"]] == ["M2"]
    assert gold.removals == []


def test_winner_without_a_country_is_rejected():
    result = pick_latest([rec("M3", None, date(2024, 1, 1))])
    with pytest.raises(ValueError, match="no country"):
        split_by_country(result)
