"""Row-level and file-level data validations.

validate_member() returns the reject rules a row breaks. An empty list
means the row is clean and goes on to silver. A non-empty list means the
row goes to silver.member_quarantine with each rule name.

duplicate_keys() finds member IDs that appear twice in one file. It is
called once per file, never across country files.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from skypoints.parsers import AmbiguousDateError, DateFormat, InvalidDateError, parse_date

_BLANK_TOKENS = {"", "NULL"}


@dataclass(frozen=True)
class RawMember:
    """One member row as text, before any typing."""
    member_id: str | None
    member_name: str | None
    country: str | None
    enrollment: str | None
    flight: str | None
    dob: str | None


@dataclass(frozen=True)
class SourceFormats:
    """The date format each date column uses in this source."""
    enrollment: DateFormat
    flight: DateFormat
    dob: DateFormat


@dataclass(frozen=True)
class RuleIssue:
    rule: str     # e.g. ENROLLMENT_DATE_INVALID
    detail: str   # human-readable explanation


def validate_member(row: RawMember, formats: SourceFormats) -> list[RuleIssue]:
    issues: list[RuleIssue] = []

    if _blank(row.member_id):
        issues.append(RuleIssue("MEMBER_ID_MISSING", "member_id is blank"))
    if _blank(row.member_name):
        issues.append(RuleIssue("MEMBER_NAME_MISSING", "member_name is blank"))
    if _blank(row.country):
        issues.append(RuleIssue("COUNTRY_MISSING", "country is blank"))

    issues += _check_date("ENROLLMENT_DATE", row.enrollment, formats.enrollment, mandatory=True)
    issues += _check_date("FLIGHT_DATE", row.flight, formats.flight, mandatory=False)
    issues += _check_date("DOB", row.dob, formats.dob, mandatory=False)
    return issues


def duplicate_keys(member_ids: Iterable[str | None]) -> set[str]:
    """Member IDs that appear more than once. Blank IDs are ignored."""
    seen: set[str] = set()
    duplicates: set[str] = set()
    for raw in member_ids:
        if _blank(raw):
            continue
        key = raw.strip()
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    return duplicates


def _check_date(name: str, raw: str | None, fmt: DateFormat, *, mandatory: bool) -> list[RuleIssue]:
    try:
        value = parse_date(raw, fmt)
    except InvalidDateError as exc:
        return [RuleIssue(f"{name}_INVALID", str(exc))]
    except AmbiguousDateError as exc:
        return [RuleIssue(f"{name}_AMBIGUOUS", str(exc))]

    if value is None and mandatory:
        return [RuleIssue(f"{name}_MISSING", f"{name.lower()} is blank")]
    return []


def _blank(value: str | None) -> bool:
    return value is None or value.strip().upper() in _BLANK_TOKENS
