"""The shared SQL rules, run on DuckDB.

sql/silver/silver_load.sql, sql/gold/latest_and_split.sql and sql/gold/redemptions.sql are Snowflake and need a warehouse.
These tests run the same expressions on DuckDB, so a change to the
age, stale, latest-record or flatten rule fails here.

Snowflake names that differ: DATEDIFF/IFF/TO_CHAR there, date_diff/IF/
strftime here. The arithmetic is the same.
"""

from datetime import date

import duckdb


def age_sql(dob: date, as_of: date) -> int:
    row = duckdb.sql(f"""
        SELECT date_diff('year', DATE '{dob}', DATE '{as_of}')
             - IF(strftime(DATE '{as_of}', '%m%d') < strftime(DATE '{dob}', '%m%d'), 1, 0)
    """).fetchall()
    return row[0][0]


def stale_sql(flight: date | None, as_of: date) -> bool:
    flight_sql = "NULL" if flight is None else f"DATE '{flight}'"
    row = duckdb.sql(f"""
        SELECT IF({flight_sql} IS NULL, TRUE,
                  date_diff('day', {flight_sql}, DATE '{as_of}') > 90)
    """).fetchall()
    return row[0][0]


def test_age_before_birthday_matches_python_rule():
    # Elena: DOB 1985-03-05, as of 2024-01-15, birthday not reached. Age 38.
    assert age_sql(date(1985, 3, 5), date(2024, 1, 15)) == 38


def test_age_on_the_birthday():
    assert age_sql(date(1985, 1, 15), date(2024, 1, 15)) == 39


def test_feb_29_birthday_counts_on_march_1():
    assert age_sql(date(1996, 2, 29), date(2025, 2, 28)) == 28
    assert age_sql(date(1996, 2, 29), date(2025, 3, 1)) == 29


def test_stale_boundary_is_more_than_90_days():
    as_of = date(2024, 1, 15)
    assert stale_sql(date(2023, 10, 17), as_of) is False   # exactly 90
    assert stale_sql(date(2023, 10, 16), as_of) is True    # 91
    assert stale_sql(None, as_of) is True


def test_latest_record_keeps_one_row_per_person():
    # Mike cannot merge: no shared DOB, so two person keys, two winners.
    # A real move (same name and DOB) keeps the later flight only.
    rows = duckdb.sql("""
        WITH staged AS (
            SELECT * FROM (VALUES
                ('MIKE|1985-01-01', 'AUS', DATE '2022-08-01', 1),
                ('MIKE|1985-01-01', 'USA', DATE '2021-12-30', 2),
                ('AUS:1',           'AUS', DATE '2022-08-01', 3),
                ('USA:3',           'USA', DATE '2021-12-30', 4)
            ) t(person_key, country_code, last_flight_date, row_num)
        )
        SELECT person_key, country_code
        FROM staged
        QUALIFY row_number() OVER (
            PARTITION BY person_key
            ORDER BY last_flight_date DESC, row_num DESC
        ) = 1
        ORDER BY person_key
    """).fetchall()
    assert rows == [
        ("AUS:1", "AUS"),
        ("MIKE|1985-01-01", "AUS"),
        ("USA:3", "USA"),
    ]


def test_json_array_flattens_to_one_row_per_transaction():
    rows = duckdb.sql("""
        WITH feed AS (
            SELECT '223457' AS member_id,
                   '[{"txn_id":"RX10091","miles_redeemed":12000},
                     {"txn_id":"RX10092","miles_redeemed":5000}]' AS payload
        )
        SELECT member_id,
               json_extract_string(item, '$.txn_id') AS txn_id,
               json_extract(item, '$.miles_redeemed')::INTEGER AS miles
        FROM feed, LATERAL unnest(from_json(payload, '["JSON"]')) AS u(item)
        ORDER BY txn_id
    """).fetchall()
    assert rows == [("223457", "RX10091", 12000), ("223457", "RX10092", 5000)]
