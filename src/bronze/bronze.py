"""Bronze landing: copy each raw file, unchanged, into a dated folder.

Layout:
    outputs/bronze/<feed>/<YYYY-MM-DD>/<file>
    outputs/bronze/load_log.csv   one row per file landed (what arrived, when, checksum)

The folder date comes from the file name when the name has one
(members_20240115.txt, redemptions_20240115.json, or a name like
members_24-11-2020.txt). A file with no date in the name (AUS.xlsx)
uses the run date, which defaults to yesterday.

The date is written YYYY-MM-DD. A slash, as in 24/11/2020, cannot be a
folder name. The same prefix is what cloud storage uses as a partition
(s3://.../members_flat/2020-11-24/). The raw file is still one copy:
rows for a different day are split later, in silver and gold.

Rules:
* The file is copied byte for byte. Nothing is parsed, typed or fixed.
* Landing the same file again does nothing (same checksum = already landed).
* A file with the same name but different content is a CONFLICT. The
  existing copy is never overwritten.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from settings import load_paths, previous_day

LOG_COLUMNS = [
    "feed", "source_file", "bronze_path", "load_date", "run_date",
    "sha256", "size_bytes", "loaded_at",
]

# 20240115 or 2024-01-15 or 2024_01_15. Year first, so it is not ambiguous.
_YEAR_FIRST = re.compile(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})")
# 24-11-2020 or 24_11_2020. Day first, matching a name written 24/11/2020.
_DAY_FIRST = re.compile(r"(\d{2})[-_](\d{2})[-_](20\d{2})")

LANDED = "LANDED"
ALREADY_LANDED = "ALREADY_LANDED"
CONFLICT = "CONFLICT"
UNKNOWN_FEED = "UNKNOWN_FEED"


@dataclass(frozen=True)
class LandingResult:
    source_file: str
    feed: str | None
    status: str
    bronze_path: Path | None


def feed_for(path: Path) -> str | None:
    """Which feed a file belongs to, from its name."""
    name = path.name.lower()
    if name.startswith("members_") and name.endswith(".txt"):
        return "members_flat"
    if name.endswith(".xlsx"):
        return "country_xlsx"
    if name.startswith("redemptions_") and name.endswith(".json"):
        return "redemptions"
    return None


def folder_date(filename: str, run_date: date) -> date:
    """Date folder for one raw file. From the name, otherwise the run date."""
    stem = Path(filename).stem
    year_first = _YEAR_FIRST.search(stem)
    if year_first:
        parsed = _safe_date(*(int(part) for part in year_first.groups()))
        if parsed is not None:
            return parsed
    day_first = _DAY_FIRST.search(stem)
    if day_first:
        day, month, year = (int(part) for part in day_first.groups())
        parsed = _safe_date(year, month, day)
        if parsed is not None:
            return parsed
    return run_date


def land_files(input_dir: Path, bronze_dir: Path, load_date: date) -> list[LandingResult]:
    results: list[LandingResult] = []
    for source in sorted(p for p in input_dir.iterdir() if p.is_file()):
        feed = feed_for(source)
        if feed is None:
            results.append(LandingResult(source.name, None, UNKNOWN_FEED, None))
            continue

        landed_on = folder_date(source.name, load_date)
        target = bronze_dir / feed / landed_on.isoformat() / source.name
        source_sha = _sha256(source)

        if target.exists():
            status = ALREADY_LANDED if _sha256(target) == source_sha else CONFLICT
            results.append(LandingResult(source.name, feed, status, target))
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if _sha256(target) != source_sha:
            target.unlink()
            raise OSError(f"copy of {source.name} does not match the source")

        _append_log(bronze_dir / "load_log.csv", {
            "feed": feed,
            "source_file": source.name,
            "bronze_path": target.relative_to(bronze_dir).as_posix(),
            "load_date": landed_on.isoformat(),
            "run_date": load_date.isoformat(),
            "sha256": source_sha,
            "size_bytes": target.stat().st_size,
            "loaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        results.append(LandingResult(source.name, feed, LANDED, target))
    return results


def main(argv: list[str] | None = None) -> int:
    paths = load_paths()
    parser = argparse.ArgumentParser(description="Land raw files into bronze")
    parser.add_argument("--input", default=paths["SOURCE_DIR"], type=Path,
                        help="folder bronze reads, from config/paths.env")
    parser.add_argument("--bronze", default=paths["BRONZE_DIR"], type=Path,
                        help="folder bronze writes, from config/paths.env")
    parser.add_argument("--load-date", default=previous_day().isoformat(), type=date.fromisoformat,
                        help="run date, default yesterday; files with no date in the name use this")
    args = parser.parse_args(argv)

    results = land_files(args.input, args.bronze, args.load_date)
    for r in results:
        where = f" -> {r.bronze_path}" if r.bronze_path else ""
        print(f"{r.status:15} {r.source_file}{where}")

    conflicts = [r for r in results if r.status == CONFLICT]
    if conflicts:
        print(f"{len(conflicts)} file(s) changed since they were landed. Nothing was overwritten.")
        return 1
    return 0


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _append_log(path: Path, row: dict) -> None:
    is_new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


if __name__ == "__main__":
    raise SystemExit(main())
