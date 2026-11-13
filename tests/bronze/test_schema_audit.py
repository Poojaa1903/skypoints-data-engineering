"""Schema audit logs columns, and a bronze failure never reaches silver."""

import csv
from datetime import date
from pathlib import Path

from backfill import backfill
from bronze.schema_audit import audit_day

START = date(2024, 1, 15)
END = date(2024, 1, 20)
HEADER = (
    "|H|Member_Name|Member_Id|Enrollment_Date|Last_Flight_Date|"
    "Tier_Code|Agent_Name|State|Country|DOB|Is_Active\n"
)
GOOD = HEADER + "|D|Elena|223457|20101012|20121013|GLD|Sam|CA|USA|03051985|A\n"
BAD_HEADER = "|H|Member_Name|Extra\n|D|Elena|223457\n"


def _dirs(tmp_path: Path):
    source = tmp_path / "input"
    source.mkdir()
    return source, tmp_path / "bronze", tmp_path / "silver", tmp_path / "gold"


def _rows(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_a_new_file_logs_every_column_and_its_type(tmp_path):
    source, bronze, silver, gold = _dirs(tmp_path)
    (source / "members_20240115.txt").write_text(GOOD, encoding="utf-8")

    backfill(source, bronze, silver, gold, START, END)

    schema = _rows(bronze / "schema_audit.csv")
    names = {row["column_name"]: row["data_type"] for row in schema}
    assert names["Member_Name"] == "TEXT"
    assert names["Member_Id"] == "NUMBER"
    assert {row["change"] for row in schema} == {"NEW_FILE"}
    files = _rows(bronze / "file_audit.csv")
    assert files[0]["status"] == "NEW_FILE"
    assert (silver / "2024-01-15" / "quarantine.csv").exists()


def test_the_same_file_is_not_logged_twice(tmp_path):
    source, bronze, silver, gold = _dirs(tmp_path)
    (source / "members_20240115.txt").write_text(GOOD, encoding="utf-8")
    backfill(source, bronze, silver, gold, START, END)
    first = len(_rows(bronze / "schema_audit.csv"))

    backfill(source, bronze, silver, gold, START, END)

    assert len(_rows(bronze / "schema_audit.csv")) == first
    assert len(_rows(bronze / "file_audit.csv")) == 1


def test_a_type_change_is_logged_as_cdc(tmp_path):
    bronze = tmp_path / "bronze"
    day = bronze / "members_flat" / "2024-01-15"
    day.mkdir(parents=True)
    (day / "members_20240115.txt").write_text(GOOD, encoding="utf-8")
    audit_day(bronze, START)

    later = bronze / "members_flat" / "2024-01-16"
    later.mkdir(parents=True)
    changed = HEADER + "|D|Elena|223457|20101012|20121013|GLD|Sam|CA|USA|not-a-number|A\n"
    (later / "members_20240116.txt").write_text(changed, encoding="utf-8")
    audit_day(bronze, date(2024, 1, 16))

    dob = [
        row for row in _rows(bronze / "schema_audit.csv")
        if row["source_file"] == "members_20240116.txt" and row["column_name"] == "DOB"
    ]
    assert dob[0]["change"] == "TYPE_CHANGED"
    assert dob[0]["data_type"] == "TEXT"
    assert _rows(bronze / "file_audit.csv")[1]["status"] == "SCHEMA_CHANGED"


def test_a_broken_file_stays_in_bronze_and_does_not_reach_silver(tmp_path):
    source, bronze, silver, gold = _dirs(tmp_path)
    (source / "members_20240115.txt").write_text(BAD_HEADER, encoding="utf-8")

    result = backfill(source, bronze, silver, gold, START, END)

    assert result.processed == []
    assert result.blocked == [START]
    assert (bronze / "members_flat" / "2024-01-15" / "members_20240115.txt").exists()
    assert not silver.exists() or not any(silver.rglob("*.csv"))
    assert _rows(bronze / "file_audit.csv")[0]["status"] == "FAILED"
