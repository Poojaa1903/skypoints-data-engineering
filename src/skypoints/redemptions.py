"""Flatten the redemption feed, remove repeats, and join it to members.

* flatten_redemptions(): one Transaction per item in each member's
  redemptions list. A value that is not a whole number is rejected.
* dedupe_transactions(): one row per txn_id, keeping the latest feed_date.
* join_to_members(): matches each transaction to a member country by
  member_id (text). Unmatched transactions are kept as orphans.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from skypoints.ingest import RedemptionRecord
from skypoints.latest import MemberRecord


@dataclass(frozen=True)
class Transaction:
    member_id: str | None
    feed_date: str | None
    txn_id: str | None
    txn_date: str | None
    partner: str | None
    miles_redeemed: int
    status: str | None
    source_file: str


@dataclass(frozen=True)
class Reject:
    source_file: str
    row_num: int
    reason: str


@dataclass
class FlattenResult:
    rows: list[Transaction] = field(default_factory=list)
    rejects: list[Reject] = field(default_factory=list)


@dataclass
class JoinResult:
    matched: list[tuple[Transaction, str]] = field(default_factory=list)
    orphans: list[Transaction] = field(default_factory=list)


def flatten_redemptions(records: list[RedemptionRecord]) -> FlattenResult:
    result = FlattenResult()
    for record in records:
        for item in record.payload.get("redemptions", []):
            miles = _whole_number(item.get("miles_redeemed"))
            if miles is None:
                result.rejects.append(Reject(record.source_file, record.row_num, "MILES_NOT_A_WHOLE_NUMBER"))
                continue
            result.rows.append(Transaction(
                member_id=record.member_id,
                feed_date=record.feed_date,
                txn_id=_text(item.get("txn_id")),
                txn_date=_text(item.get("txn_date")),
                partner=_text(item.get("partner")),
                miles_redeemed=miles,
                status=_text(item.get("status")),
                source_file=record.source_file,
            ))
    return result


def dedupe_transactions(rows: list[Transaction]) -> list[Transaction]:
    latest: dict[str, Transaction] = {}
    for row in rows:
        key = row.txn_id or ""
        current = latest.get(key)
        if current is None or (row.feed_date or "") > (current.feed_date or ""):
            latest[key] = row
    return list(latest.values())


def join_to_members(
    rows: list[Transaction], winners: dict[str, MemberRecord]
) -> JoinResult:
    result = JoinResult()
    for row in rows:
        member = winners.get(row.member_id or "")
        if member is None or not member.country_code:
            result.orphans.append(row)
        else:
            result.matched.append((row, member.country_code))
    return result


def _whole_number(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
