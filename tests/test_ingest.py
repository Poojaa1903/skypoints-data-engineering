"""Tests for reading the three source feeds into raw (text) records.

Bronze keeps values exactly as they arrived. Nothing is typed or cleaned
here. These tests read the real sample files in data/input/.

* Flat file: pipe-delimited, leading "|", H and D records.
* Country xlsx: column names differ per country. Each header is mapped to
  one canonical name. An unknown header fails the file loudly.
* Redemption JSON: one object per file. member_id is always text.
"""

import json
from pathlib import Path

import pytest

from bronze.ingest import read_country_xlsx, read_flat_file, read_redemption_json

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "input"


# --- flat file --------------------------------------------------------

def test_flat_file_has_header_and_five_detail_rows():
    rows = read_flat_file(INPUT / "members_20240115.txt")
    assert [r.record_type for r in rows] == ["H", "D", "D", "D", "D", "D"]


def test_flat_file_detail_row_keeps_text_exactly():
    elena = read_flat_file(INPUT / "members_20240115.txt")[1]
    assert elena.row_num == 2                  # line 2 of the file
    assert elena.member_name == "Elena"
    assert elena.member_id == "223457"
    assert elena.enrollment == "20101012"
    assert elena.flight == "20121013"
    assert elena.tier_code == "GLD"
    assert elena.agent_name == "Sam"
    assert elena.state == "CA"
    assert elena.country == "USA"
    assert elena.dob == "03051985"             # leading zero kept
    assert elena.is_active == "A"
    assert elena.error is None


def test_short_detail_line_is_marked_not_crashed(tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_text(
        "|H|Member_Name|Member_Id|Enrollment_Date|Last_Flight_Date|Tier_Code|Agent_Name|State|Country|DOB|Is_Active\n"
        "|D|Elena|223457|20101012|20121013|GLD|Sam|CA|USA\n",
        encoding="utf-8",
    )
    detail = read_flat_file(bad)[1]
    assert detail.error == "FIELD_COUNT_10_EXPECTED"


# --- country xlsx -----------------------------------------------------

def test_aus_columns_are_mapped_to_canonical_names():
    rows = read_country_xlsx(INPUT / "AUS.xlsx")
    mike = rows[0]
    assert mike.source_country == "AUS"        # from the file name
    assert mike.row_num == 2                   # row 1 is the header
    assert mike.source_member_id == "1"
    assert mike.member_name == "Mike"
    assert mike.tier_code == "PLT"
    assert mike.enrollment_date_raw == "44692"
    assert mike.flight_date_raw == "44774"


def test_aus_null_dob_is_kept_as_text_null():
    # Bronze keeps the literal "NULL". Silver decides what it means.
    mike = read_country_xlsx(INPUT / "AUS.xlsx")[0]
    assert mike.dob_raw == "NULL"


def test_aus_invalid_date_is_kept_unchanged():
    jonnathan = read_country_xlsx(INPUT / "AUS.xlsx")[1]
    assert jonnathan.enrollment_date_raw == "2021-13-13"


def test_ind_keeps_individual_or_corporate_flag():
    rows = read_country_xlsx(INPUT / "IND.xlsx")
    assert rows[0].individual_or_corp == "I"
    assert rows[1].individual_or_corp == "C"
    assert rows[0].dob_raw == "36130"


def test_usa_has_no_dob_so_dob_is_none():
    sam = read_country_xlsx(INPUT / "USA.xlsx")[0]
    assert sam.source_country == "USA"
    assert sam.member_name == "Sam"
    assert sam.dob_raw is None
    assert sam.enrollment_date_raw == "6152022"
    assert sam.flight_date_raw == "8202022"


def test_unknown_header_fails_the_file(tmp_path):
    from openpyxl import Workbook

    path = tmp_path / "XYZ.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["ID", "Name", "Favourite Colour"])
    ws.append(["1", "Sam", "blue"])
    wb.save(path)

    with pytest.raises(ValueError, match="Favourite Colour"):
        read_country_xlsx(path)


# --- redemption json --------------------------------------------------

def test_redemption_file_is_one_record_with_member_and_date():
    records = read_redemption_json(INPUT / "redemptions_20240115.json")
    assert len(records) == 1
    assert records[0].member_id == "223457"
    assert records[0].feed_date == "20240115"
    assert len(records[0].payload["redemptions"]) == 2


def test_numeric_member_id_in_json_becomes_text(tmp_path):
    path = tmp_path / "numeric.json"
    path.write_text(json.dumps({"member_id": 223457, "feed_date": "20240115", "redemptions": []}))
    record = read_redemption_json(path)[0]
    assert record.member_id == "223457"
    assert isinstance(record.member_id, str)
