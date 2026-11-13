"""Parse date text from each source feed into a real date.

The format is chosen per feed (see config/source_mappings.yaml), never
guessed from the value. Rules:

* Blank-like values ("", spaces, "NULL") mean "no date" and return None.
* A value that cannot be a real date raises InvalidDateError.
* A value that could be two different real dates raises
  AmbiguousDateError, so the caller can quarantine it instead of guessing.
"""

from __future__ import annotations

import math
import re
from datetime import date, timedelta
from enum import Enum

EXCEL_EPOCH = date(1899, 12, 30)  # Excel serial 1 is 1900-01-01; this offset matches it for dates after 1900-02-28

_NULL_TOKENS = {"", "NULL"}
_EIGHT_DIGITS = re.compile(r"\d{8}")
_SEVEN_DIGITS = re.compile(r"\d{7}")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class DateFormat(Enum):
    YYYYMMDD = "YYYYMMDD"        # 20121013
    MMDDYYYY = "MMDDYYYY"        # 03051985, or 6152022 with the leading zero dropped
    EXCEL_SERIAL = "EXCEL_SERIAL"  # 44692 = 2022-05-11
    ISO_DATE = "ISO_DATE"        # 2022-05-11


class InvalidDateError(ValueError):
    """The text is not a real date in the given format."""


class AmbiguousDateError(ValueError):
    """The text is a valid date in two different ways. Do not guess."""


def parse_date(raw: str | None, fmt: DateFormat) -> date | None:
    """Return the date for `raw`, or None if it is blank or NULL."""
    text = _clean(raw)
    if text is None:
        return None
    if fmt is DateFormat.YYYYMMDD:
        return _parse_yyyymmdd(text)
    if fmt is DateFormat.MMDDYYYY:
        return _parse_mmddyyyy(text)
    if fmt is DateFormat.EXCEL_SERIAL:
        return _parse_excel_serial(text)
    if fmt is DateFormat.ISO_DATE:
        return _parse_iso_date(text)
    raise ValueError(f"Unknown date format: {fmt}")


def _clean(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = raw.strip()
    if text.upper() in _NULL_TOKENS:
        return None
    return text


def _to_date(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise InvalidDateError(f"not a real date: {year}-{month}-{day}") from exc


def _parse_yyyymmdd(text: str) -> date:
    if not _EIGHT_DIGITS.fullmatch(text):
        raise InvalidDateError(f"expected 8 digits YYYYMMDD, got {text!r}")
    return _to_date(int(text[:4]), int(text[4:6]), int(text[6:]))


def _parse_mmddyyyy(text: str) -> date:
    if _EIGHT_DIGITS.fullmatch(text):
        return _to_date(int(text[4:]), int(text[:2]), int(text[2:4]))

    if _SEVEN_DIGITS.fullmatch(text):
        # Leading zero was dropped, so the month is 1 digit or 2 digits:
        #   reading A: M  DD YYYY   (e.g. 6152022 -> 6/15/2022)
        #   reading B: MM D  YYYY   (e.g. 1152022 -> 11/5/2022)
        year = int(text[3:])
        candidates = []
        for month, day in ((int(text[0]), int(text[1:3])),
                           (int(text[0:2]), int(text[2]))):
            try:
                candidates.append(date(year, month, day))
            except ValueError:
                pass
        distinct = set(candidates)
        if len(distinct) == 1:
            return distinct.pop()
        if len(distinct) == 2:
            raise AmbiguousDateError(f"{text!r} could be two different dates")
        raise InvalidDateError(f"not a real date: {text!r}")

    raise InvalidDateError(f"expected 7 or 8 digits MMDDYYYY, got {text!r}")


def _parse_excel_serial(text: str) -> date:
    try:
        serial = float(text)
    except ValueError as exc:
        raise InvalidDateError(f"not a number: {text!r}") from exc
    if not math.isfinite(serial) or serial < 1:
        raise InvalidDateError(f"not a valid Excel date serial: {text!r}")
    # Whole days only. A fraction would be the time of day.
    return EXCEL_EPOCH + timedelta(days=int(serial))


def _parse_iso_date(text: str) -> date:
    if not _ISO_DATE.fullmatch(text):
        raise InvalidDateError(f"expected YYYY-MM-DD, got {text!r}")
    return _to_date(int(text[:4]), int(text[5:7]), int(text[8:]))
