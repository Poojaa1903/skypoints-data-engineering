"""Tests for flattening the redemption feed and joining it to members.

Rules these tests lock in:

* One row per transaction. A member with no redemptions adds no rows.
* miles_redeemed is an integer. A value that is not a whole number is
  rejected with a reason, not guessed.
* The same txn_id can arrive on more than one day (PENDING, then
  COMPLETED). Keep the row from the latest feed_date only.
* A transaction joins to a member by member_id, as text.
* A transaction whose member is not in the member data (an orphan) is
  kept and reported. It is not dropped.
"""

from datetime import date
from pathlib import Path

from bronze.ingest import RedemptionRecord, read_redemption_json
from gold.latest import MemberRecord
from gold.redemptions import (
    Transaction,
    dedupe_transactions,
    flatten_redemptions,
    join_to_members,
)

ROOT = Path(__file__).resolve().parents[2]


def feed(member_id, feed_date, redemptions, row_num=1, source="redemptions.json"):
    return RedemptionRecord(
        source_file=source,
        row_num=row_num,
        member_id=member_id,
        feed_date=feed_date,
        payload={"member_id": member_id, "feed_date": feed_date, "redemptions": redemptions},
    )


def txn(txn_id, status="COMPLETED", miles=12000, feed_date="20240115", member_id="223457"):
    return {"txn_id": txn_id, "txn_date": "20240110", "partner": "AeroLink",
            "miles_redeemed": miles, "status": status}


# --- flatten ----------------------------------------------------------

def test_sample_feed_flattens_to_two_transactions():
    records = read_redemption_json(ROOT / "data" / "input" / "redemptions_20240115.json")
    result = flatten_redemptions(records)

    assert result.rejects == []
    assert [(t.txn_id, t.miles_redeemed, t.status) for t in result.rows] == [
        ("RX10091", 12000, "COMPLETED"),
        ("RX10092", 5000, "PENDING"),
    ]
    assert all(t.member_id == "223457" for t in result.rows)
    assert all(t.feed_date == "20240115" for t in result.rows)


def test_miles_are_integers():
    result = flatten_redemptions([feed("223457", "20240115", [txn("RX1", miles=12000)])])
    assert isinstance(result.rows[0].miles_redeemed, int)


def test_member_with_no_redemptions_adds_no_rows():
    result = flatten_redemptions([feed("223457", "20240115", [])])
    assert result.rows == []
    assert result.rejects == []


def test_non_whole_miles_are_rejected_with_a_reason():
    result = flatten_redemptions([feed("223457", "20240115", [txn("RX2", miles="12.5k")])])
    assert result.rows == []
    assert len(result.rejects) == 1
    assert result.rejects[0].reason == "MILES_NOT_A_WHOLE_NUMBER"


# --- dedupe -----------------------------------------------------------

def test_same_txn_on_two_days_keeps_the_latest_feed_date():
    pending = Transaction("223457", "20240113", "RX10092", "20240113", "SkyPoints",
                          5000, "PENDING", "day1.json")
    completed = Transaction("223457", "20240115", "RX10092", "20240113", "SkyPoints",
                            5000, "COMPLETED", "day2.json")

    kept = dedupe_transactions([pending, completed])

    assert len(kept) == 1
    assert kept[0].status == "COMPLETED"
    assert kept[0].feed_date == "20240115"


def test_different_txn_ids_are_all_kept():
    a = Transaction("223457", "20240115", "RX1", "20240110", "A", 1, "COMPLETED", "f.json")
    b = Transaction("223457", "20240115", "RX2", "20240110", "A", 2, "COMPLETED", "f.json")
    assert len(dedupe_transactions([a, b])) == 2


# --- join to members --------------------------------------------------

def _winner(member_id, country):
    return MemberRecord(
        member_id=member_id, country_code=country,
        last_flight_date=date(2024, 1, 1), enrollment_date=date(2020, 1, 1),
        file_date=date(2024, 1, 15), row_num=1, source_file="members.txt",
    )


def test_transaction_joins_to_the_member_country():
    txns = [Transaction("223457", "20240115", "RX1", "20240110", "A", 1, "COMPLETED", "f.json")]
    winners = {"223457": _winner("223457", "USA")}

    result = join_to_members(txns, winners)

    assert [(t.txn_id, country) for t, country in result.matched] == [("RX1", "USA")]
    assert result.orphans == []


def test_orphan_transaction_is_kept_and_reported():
    # Member 999999 is not in the member data yet.
    txns = [Transaction("999999", "20240115", "RX9", "20240110", "A", 1, "COMPLETED", "f.json")]

    result = join_to_members(txns, {"223457": _winner("223457", "USA")})

    assert result.matched == []
    assert [t.txn_id for t in result.orphans] == ["RX9"]


def test_member_id_joins_as_text():
    # "223457" in the feed must match "223457" in members, never a number.
    txns = [Transaction("223457", "20240115", "RX1", "20240110", "A", 1, "COMPLETED", "f.json")]
    result = join_to_members(txns, {"223457": _winner("223457", "IND")})
    assert result.matched[0][1] == "IND"
