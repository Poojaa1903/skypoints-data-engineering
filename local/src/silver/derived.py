"""Derived silver fields: age and stale member.

Both take an as_of_date from the pipeline. They never read today's date,
so a rerun on the same inputs gives the same result.
"""

from __future__ import annotations

from datetime import date

STALE_AFTER_DAYS = 90


def age_on(dob: date | None, as_of: date) -> int | None:
    """Full years completed on as_of. The birthday itself counts.

    A Feb 29 birthday is reached on March 1 in a non-leap year.
    A missing DOB returns None. A DOB after as_of is bad data.
    """
    if dob is None:
        return None
    if dob > as_of:
        raise ValueError(f"date of birth {dob} is after as_of {as_of}")

    years = as_of.year - dob.year
    if as_of < _birthday_in_year(dob, as_of.year):
        years -= 1
    return years


def is_stale_member(last_flight: date | None, as_of: date) -> bool:
    """True when the member has not flown in the last 90 days.

    Exactly 90 days is not stale. A missing flight date is stale,
    because there is no flight inside the window. A flight date after
    as_of is bad data.
    """
    if last_flight is None:
        return True
    if last_flight > as_of:
        raise ValueError(f"last flight {last_flight} is after as_of {as_of}")
    return (as_of - last_flight).days > STALE_AFTER_DAYS


def _birthday_in_year(dob: date, year: int) -> date:
    try:
        return dob.replace(year=year)
    except ValueError:
        # dob is Feb 29 and this year is not a leap year.
        return date(year, 3, 1)
