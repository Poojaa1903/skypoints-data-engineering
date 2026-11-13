"""Backfill restores only the gaps between the monitoring date and yesterday."""

from datetime import date
from pathlib import Path

from utils.backfill import backfill
from utils.settings import load_env, load_paths, monitoring_date

START = date(2024, 1, 15)
END = date(2024, 1, 20)
MEMBER = """\
|H|Member_Name|Member_Id|Enrollment_Date|Last_Flight_Date|Tier_Code|Agent_Name|State|Country|DOB|Is_Active
|D|Elena|223457|20101012|20121013|GLD|Sam|CA|USA|03051985|A
"""


def _dirs(tmp_path: Path):
    source = tmp_path / "input"
    source.mkdir()
    return source, tmp_path / "bronze", tmp_path / "silver", tmp_path / "gold"


def test_monitoring_date_is_read_from_the_env_file(tmp_path):
    env_file = tmp_path / "pipeline.env"
    env_file.write_text("MONITORING_DATE=2024-01-15\nSOURCE_DIR=data/input\n", encoding="utf-8")
    env = load_env(env_file)
    assert monitoring_date(env) == START
    assert load_paths(env_file) == {"SOURCE_DIR": Path("data/input")}


def test_days_outside_the_window_are_not_landed(tmp_path):
    source, bronze, silver, gold = _dirs(tmp_path)
    (source / "members_20200101.txt").write_text(MEMBER, encoding="utf-8")
    (source / "members_20240201.txt").write_text(MEMBER, encoding="utf-8")
    (source / "members_20240115.txt").write_text(MEMBER, encoding="utf-8")

    result = backfill(source, bronze, silver, gold, START, END)

    assert result.processed == [START]
    assert not (bronze / "members_flat" / "2020-01-01").exists()
    assert not (bronze / "members_flat" / "2024-02-01").exists()
    assert (bronze / "members_flat" / "2024-01-15" / "members_20240115.txt").exists()
    assert (silver / "2024-01-15" / "quarantine.csv").exists()
    assert (gold / "2024-01-15" / "Table_USA.csv").exists()
    assert not (silver / "2024-01-16").exists()


def test_a_complete_day_is_skipped_and_a_gap_is_filled(tmp_path):
    source, bronze, silver, gold = _dirs(tmp_path)
    (source / "members_20240115.txt").write_text(MEMBER, encoding="utf-8")

    first = backfill(source, bronze, silver, gold, START, END)
    assert first.processed == [START]

    second = backfill(source, bronze, silver, gold, START, END)
    assert second.processed == []
    assert second.skipped == [START]

    (silver / "2024-01-15" / "quarantine.csv").unlink()
    third = backfill(source, bronze, silver, gold, START, END)
    assert third.processed == [START]
    assert (silver / "2024-01-15" / "quarantine.csv").exists()


def test_a_file_with_no_date_is_landed_once_on_the_monitoring_date(tmp_path):
    source, bronze, silver, gold = _dirs(tmp_path)
    (source / "AUS.xlsx").write_bytes(b"snapshot")

    first = backfill(source, bronze, silver, gold, START, END, land_only=True)
    assert first.processed == []
    assert (bronze / "country_xlsx" / "2024-01-15" / "AUS.xlsx").exists()
    assert len(list((bronze / "country_xlsx").iterdir())) == 1

    second = backfill(source, bronze, silver, gold, START, END, land_only=True)
    assert [item.status for item in second.landing] == ["ALREADY_LANDED"]
    assert len(list((bronze / "country_xlsx").iterdir())) == 1
