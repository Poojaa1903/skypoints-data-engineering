"""Tests for date parsing across the source formats.

Every source sends dates differently, so the format is chosen per feed,
never guessed. Rules these tests lock in:

* Text dates are stored as text, so a leading zero is never lost.
* Blank-like values ("", "NULL") mean "no date", not an error.
* Dates that cannot exist (month 13, Feb 31) are invalid.
* USA dates without a leading zero can be ambiguous (1152022 could be
  Jan 15 or Nov 5). These are flagged, not guessed.
"""

from datetime import date

import pytest

from silver.parsers import (
    AmbiguousDateError,
    DateFormat,
    InvalidDateError,
    parse_date,
)


# --- YYYYMMDD: flat file enrollment and flight dates ------------------

def test_yyyymmdd_parses_flight_date():
    assert parse_date("20121013", DateFormat.YYYYMMDD) == date(2012, 10, 13)


def test_yyyymmdd_strips_surrounding_spaces():
    assert parse_date("  20121013 ", DateFormat.YYYYMMDD) == date(2012, 10, 13)


@pytest.mark.parametrize("raw", ["2012-1013", "2010101", "abcdefgh"])
def test_yyyymmdd_rejects_wrong_shape(raw):
    with pytest.raises(InvalidDateError):
        parse_date(raw, DateFormat.YYYYMMDD)


def test_yyyymmdd_rejects_month_13():
    with pytest.raises(InvalidDateError):
        parse_date("20121313", DateFormat.YYYYMMDD)


# --- MMDDYYYY: flat file DOB and USA.xlsx dates -----------------------

def test_mmddyyyy_keeps_leading_zero_in_dob():
    # DOB 03051985 is March 5, 1985. The leading zero must not be lost.
    assert parse_date("03051985", DateFormat.MMDDYYYY) == date(1985, 3, 5)


def test_mmddyyyy_full_eight_digits():
    assert parse_date("12282021", DateFormat.MMDDYYYY) == date(2021, 12, 28)


def test_mmddyyyy_seven_digits_is_unambiguous_when_only_one_reading_is_valid():
    # 6152022: as M=6 DD=15 it is June 15. As MM=61 it is not a month.
    assert parse_date("6152022", DateFormat.MMDDYYYY) == date(2022, 6, 15)


def test_mmddyyyy_seven_digits_with_single_digit_day():
    # 8202022: as M=8 DD=20 it is August 20. As MM=82 it is not a month.
    assert parse_date("8202022", DateFormat.MMDDYYYY) == date(2022, 8, 20)


@pytest.mark.parametrize("raw", ["1152022", "1052022"])
def test_mmddyyyy_seven_digits_can_be_ambiguous(raw):
    # 1152022 is Jan 15 2022 or Nov 5 2022. Both are valid, so we flag it.
    with pytest.raises(AmbiguousDateError):
        parse_date(raw, DateFormat.MMDDYYYY)


def test_mmddyyyy_rejects_feb_31():
    with pytest.raises(InvalidDateError):
        parse_date("02312022", DateFormat.MMDDYYYY)


# --- EXCEL_SERIAL: AUS.xlsx and IND.xlsx dates -----------------------

@pytest.mark.parametrize(
    ("serial", "expected"),
    [
        ("44692", date(2022, 5, 11)),
        ("44774", date(2022, 8, 1)),
        ("35777", date(1997, 12, 13)),
        ("19219", date(1952, 8, 13)),
    ],
)
def test_excel_serial_converts_to_date(serial, expected):
    assert parse_date(serial, DateFormat.EXCEL_SERIAL) == expected


def test_excel_serial_accepts_decimal_text():
    # Some exports store the serial as "44692.0".
    assert parse_date("44692.0", DateFormat.EXCEL_SERIAL) == date(2022, 5, 11)


def test_excel_serial_rejects_text():
    with pytest.raises(InvalidDateError):
        parse_date("not-a-date", DateFormat.EXCEL_SERIAL)


# --- ISO_DATE: text dates such as AUS "2021-13-13" -------------------

def test_iso_date_parses_valid_text():
    assert parse_date("2022-05-11", DateFormat.ISO_DATE) == date(2022, 5, 11)


def test_iso_date_rejects_month_13():
    # AUS.xlsx has 2021-13-13 in the enrollment column. It must be rejected.
    with pytest.raises(InvalidDateError):
        parse_date("2021-13-13", DateFormat.ISO_DATE)


# --- Null-like values ------------------------------------------------

@pytest.mark.parametrize("raw", [None, "", "   ", "NULL", "null", " NULL "])
@pytest.mark.parametrize("fmt", list(DateFormat))
def test_null_like_values_return_none(raw, fmt):
    # AUS.xlsx stores the text NULL for a missing DOB.
    assert parse_date(raw, fmt) is None
