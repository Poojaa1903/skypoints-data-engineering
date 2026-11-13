"""End-to-end tests for the pipeline. The sample in data/ is landed into
a temporary bronze folder first, then the pipeline reads only from bronze.

Identity rule (agreed): a person is matched across sources only when
name and DOB both match. Otherwise a record is scoped to its own file,
so AUS ID 1 is never the same person as USA ID 1. Name-only matches go
to a review list and are not merged.

Expected sample results (as_of 2024-01-15):
* 12 clean members, 2 quarantined rows (Jonnathan, John).
* Tables: USA 3, IND 4, AUS 3, PHL 1, CAN 1.
* Mike (AUS and USA) is kept in both countries and listed for review.
* Elena's 2 redemptions join to her USA record.
"""

import csv
from datetime import date
from pathlib import Path

import pytest

from bronze.bronze import land_files
from pipeline import main, person_key, run

ROOT = Path(__file__).resolve().parents[3]
INPUT = ROOT / "data"
AS_OF = date(2024, 1, 15)


def land(tmp_path: Path) -> Path:
    """Copy the sample source files into a fresh bronze folder, as make bronze does."""
    bronze = tmp_path / "bronze"
    land_files(INPUT, bronze, AS_OF)
    return bronze


@pytest.fixture(scope="module")
def output(tmp_path_factory):
    base = tmp_path_factory.mktemp("run")
    out = base / "out"
    summary = run(land(base), out / "silver", out / "gold", AS_OF)
    return out, summary


def read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# --- counts ------------------------------------------------------------

def test_one_table_per_country_with_expected_counts(output):
    _, summary = output
    assert summary.tables == {
        "Table_USA": 3,
        "Table_IND": 4,
        "Table_AUS": 3,
        "Table_PHL": 1,
        "Table_CAN": 1,
    }


def test_each_country_table_is_a_file(output):
    out, _ = output
    for name in ["Table_USA", "Table_IND", "Table_AUS", "Table_PHL", "Table_CAN"]:
        assert (out / "gold" / "2024-01-15" / f"{name}.csv").exists()


def test_bad_rows_go_to_quarantine_not_to_tables(output):
    out, summary = output
    assert summary.quarantined == 2
    names = {row["member_name"] for row in read_csv(out / "silver" / "2024-01-15" / "quarantine.csv")}
    assert names == {"Jonnathan", "John"}


# --- identity across countries ---------------------------------------

def test_mike_is_kept_in_both_countries_and_listed_for_review(output):
    out, _ = output
    aus = [r for r in read_csv(out / "gold" / "2024-01-15" / "Table_AUS.csv") if r["member_name"] == "Mike"]
    usa = [r for r in read_csv(out / "gold" / "2024-01-15" / "Table_USA.csv") if r["member_name"] == "Mike"]
    assert [r["member_id"] for r in aus] == ["1"]
    assert [r["member_id"] for r in usa] == ["3"]

    review = read_csv(out / "gold" / "2024-01-15" / "review_possible_moves.csv")
    assert [r["name"] for r in review] == ["Mike"]


def test_ids_1_2_3_are_not_merged_across_countries(output):
    out, _ = output
    ind_names = {r["member_name"] for r in read_csv(out / "gold" / "2024-01-15" / "Table_IND.csv")}
    assert {"Vikas", "Rahul", "Sameer"} <= ind_names


# --- redemptions ------------------------------------------------------

def test_elena_redemptions_join_to_her_usa_record(output):
    out, summary = output
    assert summary.matched_redemptions == 2
    assert summary.orphan_redemptions == 0
    completed = read_csv(out / "gold" / "2024-01-10" / "redemptions.csv")
    pending = read_csv(out / "gold" / "2024-01-13" / "redemptions.csv")
    rows = completed + pending
    assert {r["txn_id"] for r in completed} == {"RX10091"}
    assert {r["txn_id"] for r in pending} == {"RX10092"}
    assert {r["country_code"] for r in rows} == {"USA"}


# --- derived fields are written ---------------------------------------

def test_elena_row_has_age_and_stale_flag(output):
    out, _ = output
    elena = next(r for r in read_csv(out / "gold" / "2024-01-15" / "Table_USA.csv") if r["member_name"] == "Elena")
    assert elena["age"] == "38"                      # DOB 1985-03-05, as of 2024-01-15
    assert elena["is_stale_member"] == "True"        # last flight 2012-10-13


# --- identity rule as a unit ------------------------------------------

def test_same_name_and_dob_across_sources_gives_the_same_person_key():
    a = person_key("Mike", date(1985, 3, 5), scope="AUS", member_id="1")
    b = person_key(" mike ", date(1985, 3, 5), scope="USA", member_id="3")
    assert a == b


def test_same_name_without_dob_stays_separate():
    a = person_key("Mike", None, scope="AUS", member_id="1")
    b = person_key("Mike", None, scope="USA", member_id="3")
    assert a != b


def test_same_id_in_different_countries_stays_separate():
    a = person_key("Vikas", None, scope="AUS", member_id="1")
    b = person_key("Sam", None, scope="USA", member_id="1")
    assert a != b


# --- command line -----------------------------------------------------

def test_cli_runs_from_bronze_and_writes_outputs(tmp_path):
    bronze = land(tmp_path)
    out = tmp_path / "out"
    code = main(["--bronze", str(bronze), "--silver", str(out / "silver"),
                 "--gold", str(out / "gold"), "--as-of", "2024-01-15"])
    assert code == 0
    assert (out / "gold" / "2024-01-15" / "Table_USA.csv").exists()
