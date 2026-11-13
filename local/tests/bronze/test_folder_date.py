"""The bronze folder date comes from the file name when the name has one."""

from datetime import date

from bronze.land import folder_date

RUN = date(2026, 11, 12)


def test_yyyymmdd_in_the_name_is_the_folder():
    assert folder_date("members_20240115.txt", RUN) == date(2024, 1, 15)
    assert folder_date("redemptions_20240115.json", RUN) == date(2024, 1, 15)


def test_day_first_name_like_24_11_2020_is_24_november():
    assert folder_date("members_24-11-2020.txt", RUN) == date(2020, 11, 24)


def test_iso_name_is_year_first():
    assert folder_date("members_2020-11-25.txt", RUN) == date(2020, 11, 25)


def test_a_file_with_no_date_uses_the_run_date():
    assert folder_date("AUS.xlsx", RUN) == RUN


def test_an_impossible_date_in_the_name_uses_the_run_date():
    assert folder_date("members_20240231.txt", RUN) == RUN
