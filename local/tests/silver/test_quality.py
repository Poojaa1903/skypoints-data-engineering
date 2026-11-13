"""Dataset quality checks. A FAIL stops gold. A WARN does not."""

from datetime import date
from pathlib import Path

from bronze.land import land_files
from pipeline import run
from utils.quality import (
    FAIL,
    PASS,
    WARN,
    FileVolume,
    Limits,
    QualityFacts,
    evaluate,
    failed,
)

LIMITS = Limits()


def facts(**overrides) -> QualityFacts:
    base = dict(
        files=[FileVolume("members.txt", bronze_rows=100, loaded=100, rejected=0)],
        unmapped_rows=0,
        loaded_members=100,
        previous_members=100,
        redemption_rows=10,
        orphan_redemptions=0,
    )
    base.update(overrides)
    return QualityFacts(**base)


def status(name: str, checks) -> str:
    return next(check.status for check in checks if check.name == name)


def test_rows_that_do_not_add_up_fail():
    checks = evaluate(facts(files=[FileVolume("members.txt", 10, 7, 2)]), LIMITS)
    assert status("reconciliation", checks) == FAIL
    assert failed(checks)


def test_rows_that_add_up_pass():
    checks = evaluate(facts(), LIMITS)
    assert status("reconciliation", checks) == PASS


def test_small_file_with_one_bad_row_warns_and_does_not_fail():
    volume = FileVolume("AUS.xlsx", bronze_rows=3, loaded=2, rejected=1)
    checks = evaluate(facts(files=[volume], loaded_members=2, previous_members=2), LIMITS)
    assert status("reject_rate:AUS.xlsx", checks) == WARN
    assert not failed(checks)


def test_three_percent_of_a_large_file_warns():
    volume = FileVolume("members.txt", 100, 97, 3)
    checks = evaluate(facts(files=[volume], loaded_members=97), LIMITS)
    assert status("reject_rate:members.txt", checks) == WARN
    assert not failed(checks)


def test_ten_percent_of_a_large_file_fails():
    volume = FileVolume("members.txt", 100, 90, 10)
    checks = evaluate(facts(files=[volume], loaded_members=90), LIMITS)
    assert status("reject_rate:members.txt", checks) == FAIL
    assert failed(checks)


def test_a_drop_of_more_than_half_fails():
    checks = evaluate(facts(loaded_members=40, previous_members=100), LIMITS)
    assert status("row_count", checks) == FAIL


def test_the_first_day_has_no_drop_to_compare():
    checks = evaluate(facts(previous_members=None), LIMITS)
    assert status("row_count", checks) == PASS


def test_too_many_blank_required_fields_fail():
    volume = FileVolume("members.txt", 100, 98, 2, required_nulls=2)
    checks = evaluate(facts(files=[volume], loaded_members=98), LIMITS)
    assert status("null_rate", checks) == FAIL


def test_one_unmapped_country_warns_and_many_fail():
    warned = evaluate(facts(unmapped_rows=1), LIMITS)
    assert status("unmapped_countries", warned) == WARN
    failed_run = evaluate(facts(unmapped_rows=2), LIMITS)
    assert status("unmapped_countries", failed_run) == FAIL


def test_orphan_redemptions_warn_and_do_not_fail():
    checks = evaluate(facts(redemption_rows=10, orphan_redemptions=2), LIMITS)
    assert status("redemption_orphans", checks) == WARN
    assert not failed(checks)


def test_a_large_reject_rate_writes_silver_and_not_gold(tmp_path: Path):
    header = (
        "|H|Member_Name|Member_Id|Enrollment_Date|Last_Flight_Date|"
        "Tier_Code|Agent_Name|State|Country|DOB|Is_Active\n"
    )
    lines = [header]
    for index in range(20):
        name = "" if index < 4 else "Elena"
        lines.append(f"|D|{name}|{index}|20101012|20121013|GLD|Sam|CA|USA|03051985|A\n")
    source = tmp_path / "input"
    source.mkdir()
    (source / "members_20240120.txt").write_text("".join(lines), encoding="utf-8")
    bronze = tmp_path / "bronze"
    land_files(source, bronze, date(2024, 1, 20))

    summary = run(bronze, tmp_path / "silver", tmp_path / "gold", date(2024, 1, 20))

    assert summary.quality_failed
    assert (tmp_path / "silver" / "2024-01-20" / "quarantine.csv").exists()
    assert (tmp_path / "silver" / "2024-01-20" / "quality_report.csv").exists()
    assert not (tmp_path / "gold" / "2024-01-20" / "Table_USA.csv").exists()
