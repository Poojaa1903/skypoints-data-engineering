"""End-to-end pipeline: sample files in, per-country tables out.

Steps:
1. Read the raw files landed in bronze for the load date (raw text).
2. Validate each row. Bad rows go to quarantine.
3. Parse dates, resolve countries, derive age and stale flag.
4. Pick the latest record for each person (identity rule below).
5. Split winners into one table per country.
6. Flatten, dedupe and join redemptions.
7. Write CSV outputs under the date folder they belong to, and a summary.

Identity rule: a person is matched across sources only when name and DOB
both match. Otherwise the ID is scoped to its own file, so AUS ID 1 is never
merged with USA ID 1. Same name without a DOB match goes to review.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from bronze.ingest import read_country_xlsx, read_flat_file, read_redemption_json
from gold.gold import split_by_country
from gold.latest import MemberRecord, pick_latest
from gold.redemptions import (
    Transaction,
    dedupe_transactions,
    flatten_redemptions,
    join_to_members,
)
from silver.countries import load_lookups, resolve_country
from silver.derived import age_on, is_stale_member
from silver.parsers import DateFormat, parse_date
from silver.validations import RawMember, SourceFormats, duplicate_keys, validate_member
from quality import FileVolume, QualityFacts, evaluate, failed, load_limits, previous_member_count, write_report
from settings import load_paths, previous_day

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config"

FLAT_FORMATS = SourceFormats(
    enrollment=DateFormat.YYYYMMDD,
    flight=DateFormat.YYYYMMDD,
    dob=DateFormat.MMDDYYYY,
)
XLSX_FORMATS = {
    "AUS": SourceFormats(DateFormat.EXCEL_SERIAL, DateFormat.EXCEL_SERIAL, DateFormat.EXCEL_SERIAL),
    "IND": SourceFormats(DateFormat.EXCEL_SERIAL, DateFormat.EXCEL_SERIAL, DateFormat.EXCEL_SERIAL),
    "USA": SourceFormats(DateFormat.MMDDYYYY, DateFormat.MMDDYYYY, DateFormat.MMDDYYYY),
}

_REQUIRED_NULLS = {"MEMBER_ID_MISSING", "MEMBER_NAME_MISSING", "COUNTRY_MISSING", "ENROLLMENT_DATE_MISSING"}
_COUNT = {"bronze": 0, "loaded": 1, "rejected": 2, "nulls": 3}

TABLE_COLUMNS = [
    "member_key", "member_id", "source_file", "source_scope", "member_name",
    "tier_code", "country_code", "country_status", "enrollment_date",
    "last_flight_date", "dob", "age", "is_stale_member",
]


@dataclass
class Candidate:
    source_file: str
    row_num: int
    scope: str                 # FLAT or the country code of the xlsx file
    member_id: str
    member_name: str
    tier_code: str | None
    country_code: str
    country_status: str
    enrollment: date | None
    flight: date | None
    dob: date | None
    key: str                   # person key used by latest-record-wins


@dataclass
class PipelineSummary:
    tables: dict[str, int] = field(default_factory=dict)
    quarantined: int = 0
    review_items: int = 0
    matched_redemptions: int = 0
    orphan_redemptions: int = 0
    removals: int = 0
    unmapped_countries: list[str] = field(default_factory=list)
    redemption_days: list[date] = field(default_factory=list)
    quality_failed: bool = False


def person_key(name: str | None, dob: date | None, *, scope: str, member_id: str) -> str:
    """Same name and same DOB = same person across sources. Otherwise scope the ID."""
    if dob is not None:
        return f"{_norm(name)}|{dob.isoformat()}"
    return f"{scope}:{member_id}"


def run(bronze_dir: Path, silver_dir: Path, gold_dir: Path, as_of: date, config_dir: Path = DEFAULT_CONFIG) -> PipelineSummary:
    """Read the files landed in bronze for `as_of` and write silver and gold under that date.

    A redemption whose transaction date is a different day is written to
    that day's folder. Member rows stay with the file date: date of birth,
    enrollment and last flight are facts about the person, not the day
    the extract belongs to.
    """
    lookups = load_lookups(config_dir / "iso_countries.csv", config_dir / "country_aliases.csv")
    silver_day = _day_dir(silver_dir, as_of)

    quarantine: list[dict] = []
    candidates: list[Candidate] = []
    unmapped_rows = 0
    unmapped: set[str] = set()
    volumes: dict[str, list[int]] = {}

    # 1-3. Flat member file
    for path in _landed(bronze_dir, "members_flat", as_of, "members_*.txt"):
        details = [r for r in read_flat_file(path) if r.record_type == "D"]
        dups = duplicate_keys(r.member_id for r in details if not r.error)
        for rec in details:
            _count(volumes, path.name, "bronze")
            if rec.error:
                _count(volumes, path.name, "rejected")
                quarantine.append(_q(path.name, rec.row_num, None, None, [rec.error], rec.error))
                continue
            raw = RawMember(rec.member_id, rec.member_name, rec.country, rec.enrollment, rec.flight, rec.dob)
            issues = validate_member(raw, FLAT_FORMATS)
            rules = [i.rule for i in issues]
            if rec.member_id in dups:
                rules.append("DUPLICATE_MEMBER_ID_IN_FILE")
            if rules:
                _count(volumes, path.name, "rejected")
                if _REQUIRED_NULLS.intersection(rules):
                    _count(volumes, path.name, "nulls")
                detail = "; ".join(i.detail for i in issues) or "duplicate member_id in file"
                quarantine.append(_q(path.name, rec.row_num, rec.member_id, rec.member_name, rules, detail))
                continue
            _count(volumes, path.name, "loaded")

            match = resolve_country(rec.country, lookups)
            if match.register:
                unmapped_rows += 1
                unmapped.add(rec.country.strip().upper())
            dob = parse_date(rec.dob, FLAT_FORMATS.dob)
            candidates.append(Candidate(
                source_file=path.name, row_num=rec.row_num, scope="FLAT",
                member_id=rec.member_id, member_name=rec.member_name, tier_code=rec.tier_code,
                country_code=match.country_code, country_status=match.status.value,
                enrollment=parse_date(rec.enrollment, FLAT_FORMATS.enrollment),
                flight=parse_date(rec.flight, FLAT_FORMATS.flight),
                dob=dob,
                key=person_key(rec.member_name, dob, scope="FLAT", member_id=rec.member_id),
            ))

    # 1-3. Country xlsx files
    for path in _landed(bronze_dir, "country_xlsx", as_of, "*.xlsx"):
        source_country = path.stem.upper()
        formats = XLSX_FORMATS.get(source_country)
        if formats is None:
            raise ValueError(f"No date formats configured for {path.name}")
        rows = read_country_xlsx(path)
        dups = duplicate_keys(r.source_member_id for r in rows)
        for rec in rows:
            _count(volumes, path.name, "bronze")
            raw = RawMember(rec.source_member_id, rec.member_name, source_country,
                            rec.enrollment_date_raw, rec.flight_date_raw, rec.dob_raw)
            issues = validate_member(raw, formats)
            rules = [i.rule for i in issues]
            if rec.source_member_id in dups:
                rules.append("DUPLICATE_MEMBER_ID_IN_FILE")
            if rules:
                _count(volumes, path.name, "rejected")
                if _REQUIRED_NULLS.intersection(rules):
                    _count(volumes, path.name, "nulls")
                detail = "; ".join(i.detail for i in issues) or "duplicate member_id in file"
                quarantine.append(_q(path.name, rec.row_num, rec.source_member_id, rec.member_name, rules, detail))
                continue
            _count(volumes, path.name, "loaded")

            match = resolve_country(source_country, lookups)
            if match.register:
                unmapped_rows += 1
                unmapped.add(source_country)
            dob = parse_date(rec.dob_raw, formats.dob)
            candidates.append(Candidate(
                source_file=path.name, row_num=rec.row_num, scope=source_country,
                member_id=rec.source_member_id, member_name=rec.member_name, tier_code=rec.tier_code,
                country_code=match.country_code, country_status=match.status.value,
                enrollment=parse_date(rec.enrollment_date_raw, formats.enrollment),
                flight=parse_date(rec.flight_date_raw, formats.flight),
                dob=dob,
                key=person_key(rec.member_name, dob, scope=source_country, member_id=rec.source_member_id),
            ))

    # Redemptions are counted before the quality gate, and written after it passes.
    txns: list[Transaction] = []
    for path in _landed(bronze_dir, "redemptions", as_of, "redemptions_*.json"):
        flat = flatten_redemptions(read_redemption_json(path))
        for reject in flat.rejects:
            _count(volumes, path.name, "bronze")
            _count(volumes, path.name, "rejected")
            quarantine.append(_q(reject.source_file, reject.row_num, None, None, [reject.reason], reject.reason))
        for txn in flat.rows:
            _count(volumes, path.name, "bronze")
            _count(volumes, path.name, "loaded")
        txns.extend(flat.rows)
    txns = dedupe_transactions(txns)

    # 4-5. Latest record per person, then split by country
    records = [
        MemberRecord(
            member_id=c.key, country_code=c.country_code, last_flight_date=c.flight,
            enrollment_date=c.enrollment, file_date=as_of, row_num=c.row_num, source_file=c.source_file,
        )
        for c in candidates
    ]
    result = pick_latest(records)
    gold = split_by_country(result)
    flat_winner = {
        c.member_id: result.winners[c.key]
        for c in candidates
        if c.scope == "FLAT" and c.key in result.winners
    }
    joined = join_to_members(txns, flat_winner)

    member_files = [name for name in volumes if not name.startswith("redemptions_")]
    checks = evaluate(QualityFacts(
        files=[_volume(name, counts) for name, counts in sorted(volumes.items())],
        unmapped_rows=unmapped_rows,
        loaded_members=sum(volumes[name][1] for name in member_files),
        previous_members=previous_member_count(silver_dir, as_of),
        redemption_rows=len(joined.matched) + len(joined.orphans),
        orphan_redemptions=len(joined.orphans),
    ), load_limits())
    write_report(silver_day / "quality_report.csv", checks)
    _write_csv(
        silver_day / "quarantine.csv",
        ["source_file", "row_num", "member_id", "member_name", "rules", "detail"],
        quarantine,
    )
    summary = PipelineSummary(
        quarantined=len(quarantine),
        removals=len(gold.removals),
        matched_redemptions=len(joined.matched),
        orphan_redemptions=len(joined.orphans),
        unmapped_countries=sorted(unmapped),
        quality_failed=failed(checks),
    )
    if summary.quality_failed:
        return summary

    gold_day = _day_dir(gold_dir, as_of)
    by_location = {(c.source_file, c.row_num): c for c in candidates}
    for table, members in sorted(gold.tables.items()):
        cands = [by_location[(m.source_file, m.row_num)] for m in members]
        _write_table(gold_day / f"{table}.csv", cands, as_of)
        summary.tables[table] = len(cands)

    review = _review_rows(candidates)
    _write_csv(gold_day / "review_possible_moves.csv", ["name", "countries", "member_ids"], review)
    summary.review_items = len(review)
    summary.redemption_days = _write_redemptions_by_date(gold_dir, joined, as_of)
    return summary


def main(argv: list[str] | None = None) -> int:
    paths = load_paths()
    parser = argparse.ArgumentParser(description="SkyPoints member pipeline")
    parser.add_argument("--bronze", default=paths["BRONZE_DIR"], type=Path,
                        help="raw copies bronze wrote; silver reads this")
    parser.add_argument("--silver", default=paths["SILVER_DIR"], type=Path,
                        help="where quarantine and cleaned rows are written")
    parser.add_argument("--gold", default=paths["GOLD_DIR"], type=Path,
                        help="where country tables, review and redemptions are written")
    parser.add_argument("--as-of", default=previous_day().isoformat(), type=date.fromisoformat,
                        help="run date, default yesterday")
    args = parser.parse_args(argv)

    summary = run(args.bronze, args.silver, args.gold, args.as_of)
    print(f"Run date {args.as_of.isoformat()}")
    if summary.quality_failed:
        print("Quality checks failed. Silver was written. Gold was not.")
        return 1
    print(f"Silver written to {args.silver / args.as_of.isoformat()}")
    print(f"Gold tables written to {args.gold / args.as_of.isoformat()}:")
    for table, count in summary.tables.items():
        print(f"  {table}: {count} members")
    print(f"Quarantined rows: {summary.quarantined}")
    print(f"Possible moves for review: {summary.review_items}")
    print(f"Redemptions matched: {summary.matched_redemptions}, orphans: {summary.orphan_redemptions}")
    print(f"Removals from old countries: {summary.removals}")
    if summary.unmapped_countries:
        print(f"Unmapped country codes registered: {', '.join(summary.unmapped_countries)}")
    return 0


def _count(volumes: dict[str, list[int]], source_file: str, kind: str) -> None:
    volumes.setdefault(source_file, [0, 0, 0, 0])
    volumes[source_file][_COUNT[kind]] += 1


def _volume(source_file: str, counts: list[int]) -> FileVolume:
    return FileVolume(source_file, counts[0], counts[1], counts[2], counts[3])


def _landed(bronze_dir: Path, feed: str, load_date: date, pattern: str) -> list[Path]:
    """Files in bronze for one feed and load date. Empty if nothing landed."""
    folder = bronze_dir / feed / load_date.isoformat()
    return sorted(folder.glob(pattern)) if folder.exists() else []


def _write_table(path: Path, cands: list[Candidate], as_of: date) -> None:
    rows = []
    for c in cands:
        rows.append({
            "member_key": c.key,
            "member_id": c.member_id,
            "source_file": c.source_file,
            "source_scope": c.scope,
            "member_name": c.member_name,
            "tier_code": c.tier_code or "",
            "country_code": c.country_code,
            "country_status": c.country_status,
            "enrollment_date": _iso(c.enrollment),
            "last_flight_date": _iso(c.flight),
            "dob": _iso(c.dob),
            "age": "" if c.dob is None else age_on(c.dob, as_of),
            "is_stale_member": is_stale_member(c.flight, as_of),
        })
    _write_csv(path, TABLE_COLUMNS, rows)


def _write_redemptions_by_date(gold_dir: Path, joined, as_of: date) -> list[date]:
    """One redemptions file per transaction date.

    A file dated 2024-01-15 that contains a transaction on 2024-01-10
    writes that row under 2024-01-10, not under the file date.
    """
    columns = ["member_id", "feed_date", "txn_id", "txn_date", "partner",
               "miles_redeemed", "status", "country_code", "match"]
    by_day: dict[date, list[dict]] = {}
    for txn, country in joined.matched:
        by_day.setdefault(_event_day(txn.txn_date, as_of), []).append(_txn_row(txn, country, "MATCHED"))
    for txn in joined.orphans:
        by_day.setdefault(_event_day(txn.txn_date, as_of), []).append(_txn_row(txn, "", "ORPHAN"))
    for day, rows in sorted(by_day.items()):
        _write_csv(_day_dir(gold_dir, day) / "redemptions.csv", columns, rows)
    return sorted(by_day)


def _event_day(raw: str | None, fallback: date) -> date:
    """Transaction date when it parses. Otherwise the run date."""
    if not raw:
        return fallback
    try:
        return parse_date(raw, DateFormat.YYYYMMDD) or fallback
    except ValueError:
        return fallback


def _day_dir(root: Path, day: date) -> Path:
    folder = root / day.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _txn_row(txn: Transaction, country: str, match: str) -> dict:
    return {
        "member_id": txn.member_id, "feed_date": txn.feed_date, "txn_id": txn.txn_id,
        "txn_date": txn.txn_date, "partner": txn.partner, "miles_redeemed": txn.miles_redeemed,
        "status": txn.status, "country_code": country, "match": match,
    }


def _review_rows(candidates: list[Candidate]) -> list[dict]:
    by_name: dict[str, list[Candidate]] = {}
    for c in candidates:
        by_name.setdefault(_norm(c.member_name), []).append(c)
    rows = []
    for group in by_name.values():
        if len({c.key for c in group}) > 1:
            rows.append({
                "name": group[0].member_name,
                "countries": " / ".join(sorted({c.country_code for c in group})),
                "member_ids": " / ".join(f"{c.scope}:{c.member_id}" for c in group),
            })
    return rows


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in columns})


def _q(source_file, row_num, member_id, member_name, rules, detail) -> dict:
    return {
        "source_file": source_file, "row_num": row_num, "member_id": member_id or "",
        "member_name": member_name or "", "rules": ";".join(rules), "detail": detail,
    }


def _iso(value: date | None) -> str:
    return "" if value is None else value.isoformat()


def _norm(name: str | None) -> str:
    return " ".join((name or "").split()).upper()


if __name__ == "__main__":
    raise SystemExit(main())
