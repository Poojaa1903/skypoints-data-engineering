"""Schema and file audit for bronze. This is the change log.

Every file that lands is recorded in <date>/file_audit.csv. The first time a
feed is seen, and whenever its columns or types change, each column is
recorded in <date>/schema_audit.csv. A new file, a new column, a missing column
and a type change are the CDC events. Earlier date folders are read so a
change is still seen across days.

Bronze stores values as text. The type here is what the values look like
(TEXT, NUMBER, EMPTY, ARRAY, OBJECT, MIXED), not a cast.

A file that fails these checks is not passed to silver:

* unreadable, empty, or the wrong shape
* flat-file header is not the expected 10 columns
* an Excel header we do not know
* a redemption object missing member_id, feed_date or redemptions
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from openpyxl import load_workbook

from bronze.land import feed_for
from bronze.ingest import HEADER_MAP, read_flat_file

FILE_AUDIT = "file_audit.csv"
SCHEMA_AUDIT = "schema_audit.csv"

FILE_COLUMNS = [
    "checked_at", "load_date", "feed", "source_file", "sha256",
    "status", "row_count", "column_count", "detail",
]
SCHEMA_COLUMNS = [
    "checked_at", "load_date", "feed", "source_file",
    "column_position", "column_name", "data_type", "change",
]

FLAT_HEADER = [
    "Member_Name", "Member_Id", "Enrollment_Date", "Last_Flight_Date",
    "Tier_Code", "Agent_Name", "State", "Country", "DOB", "Is_Active",
]
XLSX_REQUIRED = [
    "source_member_id", "member_name", "tier_code",
    "enrollment_date_raw", "flight_date_raw",
]
JSON_REQUIRED = ["member_id", "feed_date", "redemptions"]
JSON_TXN_REQUIRED = ["txn_id", "txn_date", "partner", "miles_redeemed", "status"]

NEW_FILE = "NEW_FILE"
UNCHANGED = "UNCHANGED"
SCHEMA_CHANGED = "SCHEMA_CHANGED"
FAILED = "FAILED"
NEW_COLUMN = "NEW_COLUMN"
TYPE_CHANGED = "TYPE_CHANGED"
MISSING = "MISSING"


@dataclass(frozen=True)
class ColumnInfo:
    position: int
    name: str
    data_type: str


@dataclass
class Profile:
    columns: list[ColumnInfo] = field(default_factory=list)
    row_count: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AuditResult:
    source_file: str
    feed: str
    status: str
    detail: str


def audit_day(bronze_dir: Path, day: date) -> list[AuditResult]:
    """Profile every file landed on this day. Failures block silver."""
    results: list[AuditResult] = []
    known = _last_schema(bronze_dir)
    logged = _logged_sha(bronze_dir)
    for feed, path in files_for_day(bronze_dir, day):
        sha = _sha256(path)
        if sha in logged:
            status = logged[sha]
            if status == FAILED:
                results.append(AuditResult(path.name, feed, FAILED, "already failed bronze checks"))
            continue
        profile = profile_file(path, feed)
        key = _schema_key(feed, path.name)
        previous = known.get(key)
        status, detail, schema_rows = _decide(profile, previous)
        checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        day_dir = bronze_dir / day.isoformat()
        _append(day_dir / FILE_AUDIT, FILE_COLUMNS, {
            "checked_at": checked_at,
            "load_date": day.isoformat(),
            "feed": feed,
            "source_file": path.name,
            "sha256": sha,
            "status": status,
            "row_count": profile.row_count,
            "column_count": len(profile.columns),
            "detail": detail,
        })
        if schema_rows:
            for row in schema_rows:
                row["checked_at"] = checked_at
                row["load_date"] = day.isoformat()
                row["feed"] = feed
                row["source_file"] = path.name
            _append_many(day_dir / SCHEMA_AUDIT, SCHEMA_COLUMNS, schema_rows)
        if status != FAILED:
            known[key] = {column.name: column.data_type for column in profile.columns}
        logged[sha] = status
        results.append(AuditResult(path.name, feed, status, detail))
    return results


def files_for_day(bronze_dir: Path, day: date) -> list[tuple[str, Path]]:
    folder = bronze_dir / day.isoformat()
    if not folder.exists():
        return []
    found: list[tuple[str, Path]] = []
    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue
        feed = feed_for(path)
        if feed is not None:
            found.append((feed, path))
    return found


def profile_file(path: Path, feed: str) -> Profile:
    try:
        if feed == "members_flat":
            return _profile_flat(path)
        if feed == "country_xlsx":
            return _profile_xlsx(path)
        if feed == "redemptions":
            return _profile_json(path)
    except Exception as exc:
        return Profile(errors=[f"FILE_UNREADABLE: {exc}"])
    return Profile(errors=[f"FILE_UNREADABLE: unknown feed {feed}"])


def _profile_flat(path: Path) -> Profile:
    records = read_flat_file(path)
    header = next((record for record in records if record.record_type == "H"), None)
    details = [record for record in records if record.record_type == "D"]
    errors: list[str] = []
    if header is None:
        errors.append("MISSING_HEADER")
        names: list[str] = []
    else:
        names = _flat_names(header.raw_line)
        if names != FLAT_HEADER:
            errors.append("HEADER_MISMATCH: " + ", ".join(names))
    for record in records:
        if record.error:
            errors.append(f"row {record.row_num} {record.error}")
    if not details:
        errors.append("NO_DATA_ROWS")
    columns = [
        ColumnInfo(index + 1, name, _column_type(_flat_values(details, index)))
        for index, name in enumerate(names)
    ]
    return Profile(columns=columns, row_count=len(details), errors=errors)


def _profile_xlsx(path: Path) -> Profile:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        rows = list(sheet.iter_rows(values_only=True))
    finally:
        workbook.close()
    if not rows:
        return Profile(errors=["MISSING_HEADER", "NO_DATA_ROWS"])
    header = [("" if cell is None else str(cell).strip()) for cell in rows[0]]
    header = [name for name in header if name]
    unknown = [name for name in header if name not in HEADER_MAP]
    canonical = [HEADER_MAP[name] for name in header if name in HEADER_MAP]
    errors: list[str] = []
    if unknown:
        errors.append("UNKNOWN_COLUMN: " + ", ".join(unknown))
    missing = [name for name in XLSX_REQUIRED if name not in canonical]
    if missing:
        errors.append("MISSING_COLUMN: " + ", ".join(missing))
    data = [row for row in rows[1:] if not all(cell is None or str(cell).strip() == "" for cell in row)]
    if not data:
        errors.append("NO_DATA_ROWS")
    columns = []
    for index, name in enumerate(header):
        values = [row[index] for row in data if index < len(row)]
        columns.append(ColumnInfo(index + 1, name, _column_type(values)))
    return Profile(columns=columns, row_count=len(data), errors=errors)


def _profile_json(path: Path) -> Profile:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    objects = data if isinstance(data, list) else [data]
    errors: list[str] = []
    if not objects:
        errors.append("NO_DATA_ROWS")
    txn_rows: list[dict] = []
    for obj in objects:
        if not isinstance(obj, dict):
            errors.append("JSON_NOT_AN_OBJECT")
            continue
        missing = [key for key in JSON_REQUIRED if key not in obj]
        if missing:
            errors.append("MISSING_COLUMN: " + ", ".join(missing))
        items = obj.get("redemptions") or []
        if not isinstance(items, list):
            errors.append("REDEMPTIONS_NOT_A_LIST")
            continue
        for item in items:
            if not isinstance(item, dict):
                errors.append("REDEMPTION_NOT_AN_OBJECT")
                continue
            missing_txn = [key for key in JSON_TXN_REQUIRED if key not in item]
            if missing_txn:
                errors.append("MISSING_COLUMN: " + ", ".join(missing_txn))
            txn_rows.append(item)
    if objects and not txn_rows:
        errors.append("NO_DATA_ROWS")
    columns = [
        ColumnInfo(1, "member_id", _column_type([obj.get("member_id") for obj in objects if isinstance(obj, dict)])),
        ColumnInfo(2, "feed_date", _column_type([obj.get("feed_date") for obj in objects if isinstance(obj, dict)])),
        ColumnInfo(3, "redemptions", "ARRAY"),
    ]
    for offset, key in enumerate(JSON_TXN_REQUIRED, start=4):
        columns.append(ColumnInfo(offset, f"redemptions.{key}", _column_type([row.get(key) for row in txn_rows])))
    return Profile(columns=columns, row_count=len(txn_rows), errors=_unique(errors))


def _decide(profile: Profile, previous: dict[str, str] | None):
    if profile.errors:
        rows = _schema_rows(profile.columns, previous)
        return FAILED, "; ".join(profile.errors), rows
    rows = _schema_rows(profile.columns, previous)
    changes = {row["change"] for row in rows}
    if previous is None:
        return NEW_FILE, "", rows
    if changes & {NEW_COLUMN, TYPE_CHANGED, MISSING}:
        return SCHEMA_CHANGED, "", rows
    return UNCHANGED, "", rows


def _schema_rows(columns: list[ColumnInfo], previous: dict[str, str] | None) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for column in columns:
        seen.add(column.name)
        if previous is None:
            change = NEW_FILE
        elif column.name not in previous:
            change = NEW_COLUMN
        elif previous[column.name] != column.data_type:
            change = TYPE_CHANGED
        else:
            change = UNCHANGED
        rows.append({
            "column_position": column.position,
            "column_name": column.name,
            "data_type": column.data_type,
            "change": change,
        })
    for name, data_type in (previous or {}).items():
        if name not in seen:
            rows.append({
                "column_position": "",
                "column_name": name,
                "data_type": data_type,
                "change": MISSING,
            })
    return rows


def _column_type(values: list) -> str:
    kinds = {_value_type(value) for value in values if not _blank(value)}
    if not kinds:
        return "EMPTY"
    if len(kinds) == 1:
        return kinds.pop()
    return "MIXED"


def _value_type(value) -> str:
    if isinstance(value, bool):
        return "TEXT"
    if isinstance(value, (int, float)):
        return "NUMBER"
    if isinstance(value, list):
        return "ARRAY"
    if isinstance(value, dict):
        return "OBJECT"
    text = str(value).strip()
    if text and _is_number(text):
        return "NUMBER"
    return "TEXT"


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _blank(value) -> bool:
    return value is None or str(value).strip() == "" or str(value).strip().upper() == "NULL"


def _flat_names(raw_line: str) -> list[str]:
    parts = raw_line.split("|")
    if parts and parts[0] == "":
        parts = parts[1:]
    return parts[1:]


def _flat_values(details, index: int) -> list[str | None]:
    fields = [
        "member_name", "member_id", "enrollment", "flight", "tier_code",
        "agent_name", "state", "country", "dob", "is_active",
    ]
    if index >= len(fields):
        return []
    return [getattr(record, fields[index]) for record in details if record.error is None]


def _schema_key(feed: str, filename: str) -> str:
    """Country files each have their own columns. Other feeds share one shape."""
    if feed == "country_xlsx":
        return f"{feed}:{Path(filename).stem.upper()}"
    return feed


def _last_schema(bronze_dir: Path) -> dict[str, dict[str, str]]:
    """Latest accepted column types across every date folder."""
    failed = _failed_snapshots(bronze_dir)
    latest: dict[str, tuple[str, dict[str, str]]] = {}
    for path in _dated_files(bronze_dir, SCHEMA_AUDIT):
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if (row["checked_at"], row["source_file"]) in failed:
                    continue
                key = _schema_key(row["feed"], row["source_file"])
                stamp = row["checked_at"]
                current = latest.get(key)
                if current is None or stamp > current[0]:
                    latest[key] = (stamp, {})
                if stamp == latest[key][0] and row["change"] != MISSING:
                    latest[key][1][row["column_name"]] = row["data_type"]
    return {key: columns for key, (_, columns) in latest.items()}


def _failed_snapshots(bronze_dir: Path) -> set[tuple[str, str]]:
    failed: set[tuple[str, str]] = set()
    for path in _dated_files(bronze_dir, FILE_AUDIT):
        with open(path, newline="", encoding="utf-8") as handle:
            failed.update(
                (row["checked_at"], row["source_file"])
                for row in csv.DictReader(handle)
                if row["status"] == FAILED
            )
    return failed


def _logged_sha(bronze_dir: Path) -> dict[str, str]:
    logged: dict[str, str] = {}
    for path in _dated_files(bronze_dir, FILE_AUDIT):
        with open(path, newline="", encoding="utf-8") as handle:
            logged.update({row["sha256"]: row["status"] for row in csv.DictReader(handle)})
    return logged


def _dated_files(bronze_dir: Path, name: str) -> list[Path]:
    if not bronze_dir.exists():
        return []
    return sorted(bronze_dir.glob(f"*/{name}"))


def _append(path: Path, columns: list[str], row: dict) -> None:
    _append_many(path, columns, [row])


def _append_many(path: Path, columns: list[str], rows: list[dict]) -> None:
    if not rows:
        return
    is_new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
