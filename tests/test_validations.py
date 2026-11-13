"""Tests for row-level and file-level data validations.

A row with any reject rule goes to silver.member_quarantine with the rule
name. Clean rows continue to silver. A bad row never stops the run.

Row rules (reject):
* member_id, member_name, enrollment date and country are mandatory.
* A date that is invalid or ambiguous is rejected.

Not rejected (optional or handled elsewhere):
* Missing DOB, missing last flight date, missing agent name.
* A country that is UNMAPPED. It loads and is registered (see countries.py).

File rule (reject duplicates):
* The same member_id twice in one file. Every copy is quarantined, because
  we cannot tell which one is right.
* The same member_id in two different country files is NOT a duplicate.
  That is the latest-record-wins case.
"""

from silver.parsers import DateFormat
from silver.validations import (
    RawMember,
    SourceFormats,
    duplicate_keys,
    validate_member,
)

FLAT = SourceFormats(
    enrollment=DateFormat.YYYYMMDD,
    flight=DateFormat.YYYYMMDD,
    dob=DateFormat.MMDDYYYY,
)
USA = SourceFormats(
    enrollment=DateFormat.MMDDYYYY,
    flight=DateFormat.MMDDYYYY,
    dob=DateFormat.MMDDYYYY,
)
AUS = SourceFormats(
    enrollment=DateFormat.EXCEL_SERIAL,
    flight=DateFormat.EXCEL_SERIAL,
    dob=DateFormat.EXCEL_SERIAL,
)


def rules(issues):
    return {issue.rule for issue in issues}


# --- a clean row ------------------------------------------------------

def test_clean_flat_file_row_has_no_issues():
    # Elena from the sample flat file.
    row = RawMember(
        member_id="223457", member_name="Elena", country="USA",
        enrollment="20101012", flight="20121013", dob="03051985",
    )
    assert validate_member(row, FLAT) == []


def test_aus_mike_with_null_dob_is_still_clean():
    # DOB is optional, so the text NULL is not a reject.
    row = RawMember(
        member_id="1", member_name="Mike", country="AUS",
        enrollment="44692", flight="44774", dob="NULL",
    )
    assert validate_member(row, AUS) == []


def test_missing_last_flight_is_not_a_reject():
    row = RawMember(
        member_id="223458", member_name="Ravi", country="IND",
        enrollment="20101012", flight=None, dob="03051985",
    )
    assert validate_member(row, FLAT) == []


def test_unmapped_country_is_not_a_reject():
    # UK is registered by the country step. Validation does not reject it.
    row = RawMember(
        member_id="999001", member_name="Priya", country="UK",
        enrollment="20101012", flight="20121013", dob="03051985",
    )
    assert validate_member(row, FLAT) == []


# --- mandatory fields -------------------------------------------------

def test_missing_member_id_is_rejected():
    row = RawMember(
        member_id=" ", member_name="Nora", country="CAN",
        enrollment="20101012", flight="20121013", dob="03051985",
    )
    assert "MEMBER_ID_MISSING" in rules(validate_member(row, FLAT))


def test_blank_member_name_is_rejected():
    row = RawMember(
        member_id="22345", member_name=None, country="CAN",
        enrollment="20101012", flight="20121013", dob="03051985",
    )
    assert "MEMBER_NAME_MISSING" in rules(validate_member(row, FLAT))


def test_missing_enrollment_date_is_rejected():
    row = RawMember(
        member_id="2256", member_name="Jacob", country="AUS",
        enrollment="NULL", flight="20121013", dob="03051985",
    )
    assert "ENROLLMENT_DATE_MISSING" in rules(validate_member(row, FLAT))


def test_missing_country_is_rejected():
    row = RawMember(
        member_id="223459", member_name="Mateo", country=None,
        enrollment="20101012", flight="20121013", dob="03051985",
    )
    assert "COUNTRY_MISSING" in rules(validate_member(row, FLAT))


# --- invalid and ambiguous dates -------------------------------------

def test_aus_text_date_2021_13_13_is_rejected():
    # AUS.xlsx has 2021-13-13 in a date column. It is not a real date.
    row = RawMember(
        member_id="2", member_name="Jonnathan", country="AUS",
        enrollment="2021-13-13", flight="44566", dob="35777",
    )
    assert "ENROLLMENT_DATE_INVALID" in rules(validate_member(row, AUS))


def test_usa_ambiguous_dates_are_rejected():
    # USA ID 2 (John): enrollment 1052022 and flight 1152022 can each be
    # read two ways, so both are flagged.
    row = RawMember(
        member_id="2", member_name="John", country="USA",
        enrollment="1052022", flight="1152022", dob=None,
    )
    assert rules(validate_member(row, USA)) == {
        "ENROLLMENT_DATE_AMBIGUOUS",
        "FLIGHT_DATE_AMBIGUOUS",
    }


def test_invalid_dob_is_rejected():
    row = RawMember(
        member_id="223457", member_name="Elena", country="USA",
        enrollment="20101012", flight="20121013", dob="02312000",
    )
    assert "DOB_INVALID" in rules(validate_member(row, FLAT))


# --- duplicate keys ---------------------------------------------------

def test_same_member_id_twice_in_one_file_is_a_duplicate():
    assert duplicate_keys(["1", "2", "2", "3"]) == {"2"}


def test_unique_ids_in_one_file_have_no_duplicates():
    assert duplicate_keys(["223457", "223458", "223459"]) == set()


def test_blank_ids_are_not_counted_as_duplicates():
    # Blank IDs are a mandatory-field reject, not a duplicate.
    assert duplicate_keys([None, None, "1"]) == set()


def test_ids_1_2_3_in_different_country_files_are_not_duplicates():
    # IDs 1, 2 and 3 appear in every country file. Each file is checked on
    # its own, so none of them is a duplicate.
    aus_ids = ["1", "2", "3"]
    usa_ids = ["1", "2", "3"]
    assert duplicate_keys(aus_ids) == set()
    assert duplicate_keys(usa_ids) == set()
