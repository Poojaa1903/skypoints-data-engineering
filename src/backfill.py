"""Restore missing days from the monitoring date through yesterday.

config/paths.env sets MONITORING_DATE. A run looks at every source file
from that day through yesterday:

* Bronze: copy a file that is not there yet. A file already copied, with
  the same checksum, is left alone. Files dated before the monitoring
  date are ignored.
* Silver and gold: process a day only when that day is missing or
  incomplete. A day that already has its outputs is skipped, so a rerun
  does not reload history.
* A calendar day with no file is not a gap. Nothing is created for it.

A file with no date in its name (AUS.xlsx) is part of the first day,
the monitoring date, and is not copied onto every later day.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from bronze.bronze import CONFLICT, land_window
from bronze.bronze import LandingResult
from pipeline import run
from settings import load_paths, monitoring_date, previous_day

SUCCESS = "_SUCCESS"


@dataclass
class BackfillResult:
    landing: list[LandingResult] = field(default_factory=list)
    processed: list[date] = field(default_factory=list)
    skipped: list[date] = field(default_factory=list)


def backfill(
    input_dir: Path,
    bronze_dir: Path,
    silver_dir: Path,
    gold_dir: Path,
    start: date,
    end: date,
    config_dir: Path | None = None,
    land_only: bool = False,
) -> BackfillResult:
    """Fill gaps from start through end. Complete days are not reprocessed."""
    result = BackfillResult(landing=land_window(input_dir, bronze_dir, start, end))
    if land_only:
        return result

    for day in bronze_days(bronze_dir, start, end):
        if is_complete(silver_dir, gold_dir, day):
            result.skipped.append(day)
            continue
        if config_dir is None:
            summary = run(bronze_dir, silver_dir, gold_dir, day)
        else:
            summary = run(bronze_dir, silver_dir, gold_dir, day, config_dir)
        _mark_success(gold_dir, day, summary.redemption_days)
        result.processed.append(day)
    return result


def bronze_days(bronze_dir: Path, start: date, end: date) -> list[date]:
    """Dates in the window that have at least one landed file."""
    if not bronze_dir.exists():
        return []
    found: set[date] = set()
    for feed in bronze_dir.iterdir():
        if not feed.is_dir():
            continue
        for day_dir in feed.iterdir():
            if not day_dir.is_dir():
                continue
            try:
                day = date.fromisoformat(day_dir.name)
            except ValueError:
                continue
            if start <= day <= end and any(day_dir.iterdir()):
                found.add(day)
    return sorted(found)


def is_complete(silver_dir: Path, gold_dir: Path, day: date) -> bool:
    """True when this day's silver and gold outputs are all still in place."""
    marker = gold_dir / day.isoformat() / SUCCESS
    if not marker.exists():
        return False
    if not (silver_dir / day.isoformat() / "quarantine.csv").exists():
        return False
    if not (gold_dir / day.isoformat() / "review_possible_moves.csv").exists():
        return False
    for line in marker.read_text(encoding="utf-8").splitlines():
        if not line.startswith("redemptions="):
            continue
        raw = line.split("=", 1)[1].strip()
        if not raw:
            return True
        for part in raw.split(","):
            if not (gold_dir / part / "redemptions.csv").exists():
                return False
    return True


def _mark_success(gold_dir: Path, day: date, redemption_days: list[date]) -> None:
    folder = gold_dir / day.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    days = ",".join(d.isoformat() for d in redemption_days)
    (folder / SUCCESS).write_text(
        f"as_of={day.isoformat()}\nredemptions={days}\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    paths = load_paths()
    parser = argparse.ArgumentParser(description="Backfill bronze, silver and gold from the monitoring date")
    parser.add_argument("--input", default=paths["SOURCE_DIR"], type=Path)
    parser.add_argument("--bronze", default=paths["BRONZE_DIR"], type=Path)
    parser.add_argument("--silver", default=paths["SILVER_DIR"], type=Path)
    parser.add_argument("--gold", default=paths["GOLD_DIR"], type=Path)
    parser.add_argument("--from", dest="start", default=None,
                        help="first day to restore, default MONITORING_DATE")
    parser.add_argument("--until", default=None, help="last day to restore, default yesterday")
    parser.add_argument("--land-only", action="store_true", help="copy into bronze and do not transform")
    args = parser.parse_args(argv)

    start = date.fromisoformat(args.start) if args.start else monitoring_date()
    end = date.fromisoformat(args.until) if args.until else previous_day()
    print(f"Backfill {start.isoformat()} through {end.isoformat()}")

    try:
        result = backfill(
            args.input, args.bronze, args.silver, args.gold, start, end, land_only=args.land_only,
        )
    except ValueError as exc:
        print(exc)
        return 1

    for item in result.landing:
        where = f" -> {item.bronze_path}" if item.bronze_path else ""
        print(f"{item.status:15} {item.source_file}{where}")
    for day in result.skipped:
        print(f"SKIP            {day.isoformat()} already in silver and gold")
    for day in result.processed:
        print(f"PROCESS         {day.isoformat()}")

    conflicts = [item for item in result.landing if item.status == CONFLICT]
    if conflicts:
        print(f"{len(conflicts)} file(s) changed since they were landed. Nothing was overwritten.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
