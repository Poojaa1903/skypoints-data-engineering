"""Read the three source feeds into raw text records (the bronze step).

Nothing is typed or cleaned here. A value that arrived as "03051985"
stays "03051985". Cleaning and typing happen in silver.

* Flat file: pipe-delimited. The line starts with "|", so the first
  split element is empty and is dropped. H = header, D = detail.
* Country xlsx: each header is mapped to one canonical column name. An
  unknown header fails the file, so schema drift is loud, not silent.
* Redemption JSON: one object per file. member_id is always text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

FLAT_DETAIL_FIELD_COUNT = 10
_EXCEL_EPOCH = datetime(1899, 12, 30)

# Source header -> canonical column. All three country files are covered.
HEADER_MAP: dict[str, str] = {
    "Unique ID": "source_member_id",          # AUS
    "ID": "source_member_id",                 # IND, USA
    "Member Name": "member_name",             # AUS
    "Name": "member_name",                    # IND, USA
    "Tier Type": "tier_code",                 # AUS
    "TierCode": "tier_code",                  # IND, USA
    "Date of Birth": "dob_raw",               # AUS
    "DOB": "dob_raw",                         # IND
    "Date of Enrollment": "enrollment_date_raw",  # AUS
    "EnrollmentDate": "enrollment_date_raw",  # IND, USA
    "Date of Flight": "flight_date_raw",      # AUS
    "Flight Date": "flight_date_raw",         # IND
    "FlightDate": "flight_date_raw",          # USA
    "Individual or Corporate": "individual_or_corp",  # IND
}


@dataclass(frozen=True)
class FlatRecord:
    row_num: int
    raw_line: str
    record_type: str                      # H or D
    member_name: str | None = None
    member_id: str | None = None
    enrollment: str | None = None
    flight: str | None = None
    tier_code: str | None = None
    agent_name: str | None = None
    state: str | None = None
    country: str | None = None
    dob: str | None = None
    is_active: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class CountryRecord:
    source_file: str
    source_country: str                   # from the file name, e.g. AUS
    row_num: int
    source_member_id: str | None = None
    member_name: str | None = None
    tier_code: str | None = None
    dob_raw: str | None = None
    enrollment_date_raw: str | None = None
    flight_date_raw: str | None = None
    individual_or_corp: str | None = None


@dataclass(frozen=True)
class RedemptionRecord:
    source_file: str
    row_num: int
    member_id: str | None
    feed_date: str | None
    payload: dict[str, Any] = field(compare=False)


def read_flat_file(path: Path) -> list[FlatRecord]:
    records: list[FlatRecord] = []
    with open(path, encoding="utf-8") as f:
        for row_num, line in enumerate(f, start=1):
            raw = line.rstrip("\r\n")
            if not raw.strip():
                continue

            parts = raw.split("|")
            if parts and parts[0] == "":
                parts = parts[1:]           # leading "|" of every line
            record_type = parts[0] if parts else ""
            fields = parts[1:]

            if record_type == "H":
                records.append(FlatRecord(row_num, raw, "H"))
            elif record_type == "D":
                if len(fields) != FLAT_DETAIL_FIELD_COUNT:
                    records.append(FlatRecord(row_num, raw, "D", error="FIELD_COUNT_10_EXPECTED"))
                    continue
                (name, member_id, enrolled, flight, tier, agent,
                 state, country, dob, active) = fields
                records.append(FlatRecord(
                    row_num=row_num, raw_line=raw, record_type="D",
                    member_name=name, member_id=member_id, enrollment=enrolled,
                    flight=flight, tier_code=tier, agent_name=agent, state=state,
                    country=country, dob=dob, is_active=active,
                ))
            else:
                records.append(FlatRecord(row_num, raw, record_type, error="UNKNOWN_RECORD_TYPE"))
    return records


def read_country_xlsx(path: Path) -> list[CountryRecord]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        rows = sheet.iter_rows(values_only=True)
        header = next(rows)
        column_for = _map_header(header, path)
        source_country = path.stem.upper()

        records: list[CountryRecord] = []
        for row_num, values in enumerate(rows, start=2):   # row 1 is the header
            if all(v is None or str(v).strip() == "" for v in values):
                continue
            mapped: dict[str, str | None] = {}
            for index, canonical in column_for.items():
                mapped[canonical] = _to_text(values[index])
            records.append(CountryRecord(
                source_file=path.name,
                source_country=source_country,
                row_num=row_num,
                source_member_id=mapped.get("source_member_id"),
                member_name=mapped.get("member_name"),
                tier_code=mapped.get("tier_code"),
                dob_raw=mapped.get("dob_raw"),
                enrollment_date_raw=mapped.get("enrollment_date_raw"),
                flight_date_raw=mapped.get("flight_date_raw"),
                individual_or_corp=mapped.get("individual_or_corp"),
            ))
        return records
    finally:
        workbook.close()


def read_redemption_json(path: Path) -> list[RedemptionRecord]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    objects = data if isinstance(data, list) else [data]
    return [
        RedemptionRecord(
            source_file=path.name,
            row_num=index,
            member_id=_to_text(obj.get("member_id")),
            feed_date=_to_text(obj.get("feed_date")),
            payload=obj,
        )
        for index, obj in enumerate(objects, start=1)
    ]


def _map_header(header: tuple, path: Path) -> dict[int, str]:
    column_for: dict[int, str] = {}
    unknown: list[str] = []
    for index, name in enumerate(header):
        if name is None:
            continue
        key = str(name).strip()
        if key in HEADER_MAP:
            column_for[index] = HEADER_MAP[key]
        else:
            unknown.append(key)
    if unknown:
        raise ValueError(f"Unknown column(s) in {path.name}: {', '.join(unknown)}")
    return column_for


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        serial = (value - _EXCEL_EPOCH).total_seconds() / 86400
        return str(int(serial)) if serial.is_integer() else str(serial)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    return text or None
