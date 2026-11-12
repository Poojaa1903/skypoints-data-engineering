"""Latest record wins: keep one record per member when a member appears
in more than one country.

Ranking, most important first:

1. Latest last_flight_date. If it is missing, enrollment_date is used.
2. Later file_date.
3. Higher row_num.

Every losing record is returned as superseded, so the gold load can
remove it from the old country table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class MemberRecord:
    member_id: str                      # text, never converted to a number
    country_code: str | None
    last_flight_date: date | None
    enrollment_date: date | None
    file_date: date
    row_num: int
    source_file: str


@dataclass
class LatestResult:
    winners: dict[str, MemberRecord] = field(default_factory=dict)
    superseded: list[MemberRecord] = field(default_factory=list)


def pick_latest(records: list[MemberRecord]) -> LatestResult:
    by_member: dict[str, list[MemberRecord]] = {}
    for record in records:
        by_member.setdefault(record.member_id, []).append(record)

    result = LatestResult()
    for member_id, group in by_member.items():
        ordered = sorted(group, key=_rank, reverse=True)
        result.winners[member_id] = ordered[0]
        result.superseded.extend(ordered[1:])
    return result


def _rank(record: MemberRecord) -> tuple[date, date, int]:
    if record.last_flight_date is not None:
        effective = record.last_flight_date
    elif record.enrollment_date is not None:
        effective = record.enrollment_date
    else:
        effective = date.min
    return (effective, record.file_date, record.row_num)
