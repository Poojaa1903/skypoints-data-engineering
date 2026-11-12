"""Tests for the derived silver fields: age and stale member.

Both depend on an as_of_date passed in by the pipeline, never on today's
date. That keeps results repeatable and the tests stable.

Rules these tests lock in:

* Age is full years completed on as_of_date. The birthday itself counts.
* A Feb 29 birthday is treated as March 1 in non-leap years.
* A missing DOB gives no age (None). It is not an error.
* Stale means more than 90 days since the last flight. Exactly 90 days
  is NOT stale. Exactly 91 days IS stale.
* No last flight date at all counts as stale, because the member has
  not flown within the window.
"""

from datetime import date

import pytest

from skypoints.derived import age_on, is_stale_member

AS_OF = date(2024, 1, 15)


# --- age_on -----------------------------------------------------------

def test_age_is_full_years_before_birthday():
    # DOB 1985-03-05, as of 2024-01-15: birthday not reached yet this year.
    assert age_on(date(1985, 3, 5), AS_OF) == 38


def test_age_counts_birthday_on_the_day_itself():
    assert age_on(date(1985, 1, 15), AS_OF) == 39


def test_age_day_before_birthday_is_not_yet_reached():
    assert age_on(date(1985, 1, 16), AS_OF) == 38


def test_age_feb_29_birthday_in_non_leap_year_counts_on_march_1():
    # 2025 is not a leap year, so the 1996-02-29 birthday is reached on 2025-03-01.
    assert age_on(date(1996, 2, 29), date(2025, 2, 28)) == 28
    assert age_on(date(1996, 2, 29), date(2025, 3, 1)) == 29


def test_age_is_none_when_dob_missing():
    assert age_on(None, AS_OF) is None


def test_age_rejects_dob_after_as_of_date():
    with pytest.raises(ValueError):
        age_on(date(2025, 1, 1), AS_OF)


# --- is_stale_member --------------------------------------------------

def test_flight_exactly_90_days_ago_is_not_stale():
    # 2023-10-17 to 2024-01-15 is exactly 90 days.
    assert is_stale_member(date(2023, 10, 17), AS_OF) is False


def test_flight_91_days_ago_is_stale():
    assert is_stale_member(date(2023, 10, 16), AS_OF) is True


def test_flight_today_is_not_stale():
    assert is_stale_member(AS_OF, AS_OF) is False


def test_missing_last_flight_is_stale():
    assert is_stale_member(None, AS_OF) is True


def test_flight_after_as_of_date_is_rejected():
    with pytest.raises(ValueError):
        is_stale_member(date(2024, 2, 1), AS_OF)
