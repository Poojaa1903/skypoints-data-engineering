"""Dataset checks after silver, before gold.

Each check is PASS, WARN or FAIL. A WARN is reported and the day continues.
A FAIL writes the silver quarantine and this report, and does not write gold.

Thresholds live in config/quality.env. A file with fewer than
REJECT_MIN_ROWS rows warns instead of failing, because one bad row in the
sample extract is 33 percent and must not stop the demo.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from settings import PROJECT_ROOT

QUALITY_FILE = PROJECT_ROOT / "config" / "quality.env"
REPORT_COLUMNS = ["check", "status", "value", "threshold", "detail"]

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"


@dataclass(frozen=True)
class Limits:
    reject_warn: float = 0.02
    reject_fail: float = 0.05
    reject_min_rows: int = 20
    row_drop_fail: float = 0.50
    null_fail: float = 0.01
    unmapped_fail: float = 0.01
    orphan_warn: float = 0.10


@dataclass(frozen=True)
class FileVolume:
    source_file: str
    bronze_rows: int
    loaded: int
    rejected: int
    required_nulls: int = 0


@dataclass(frozen=True)
class QualityFacts:
    files: list[FileVolume]
    unmapped_rows: int
    loaded_members: int
    previous_members: int | None
    redemption_rows: int
    orphan_redemptions: int


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    value: str
    threshold: str
    detail: str


def load_limits(path: Path = QUALITY_FILE) -> Limits:
    raw = _read_env(path)
    return Limits(
        reject_warn=float(raw.get("REJECT_WARN", 0.02)),
        reject_fail=float(raw.get("REJECT_FAIL", 0.05)),
        reject_min_rows=int(raw.get("REJECT_MIN_ROWS", 20)),
        row_drop_fail=float(raw.get("ROW_DROP_FAIL", 0.50)),
        null_fail=float(raw.get("NULL_FAIL", 0.01)),
        unmapped_fail=float(raw.get("UNMAPPED_FAIL", 0.01)),
        orphan_warn=float(raw.get("ORPHAN_WARN", 0.10)),
    )


def evaluate(facts: QualityFacts, limits: Limits | None = None) -> list[Check]:
    limits = limits or Limits()
    checks = [reconciliation(facts)]
    checks.extend(reject_rate(volume, limits) for volume in facts.files)
    checks.append(row_count(facts, limits))
    checks.append(null_rate(facts, limits))
    checks.append(unmapped_rate(facts, limits))
    checks.append(orphan_rate(facts, limits))
    return checks


def failed(checks: list[Check]) -> bool:
    return any(check.status == FAIL for check in checks)


def reconciliation(facts: QualityFacts) -> Check:
    bad = [
        f"{volume.source_file}: bronze {volume.bronze_rows}, loaded {volume.loaded}, rejected {volume.rejected}"
        for volume in facts.files
        if volume.bronze_rows != volume.loaded + volume.rejected
    ]
    if bad:
        return Check("reconciliation", FAIL, "mismatch", "bronze = loaded + rejected", "; ".join(bad))
    detail = "; ".join(f"{volume.source_file} {volume.bronze_rows}={volume.loaded}+{volume.rejected}" for volume in facts.files)
    return Check("reconciliation", PASS, "match", "bronze = loaded + rejected", detail)


def reject_rate(volume: FileVolume, limits: Limits) -> Check:
    name = f"reject_rate:{volume.source_file}"
    if volume.bronze_rows == 0:
        return Check(name, PASS, "0", _reject_threshold(limits), "empty file")
    rate = volume.rejected / volume.bronze_rows
    shown = f"{rate:.1%}"
    if volume.rejected == 0:
        return Check(name, PASS, shown, _reject_threshold(limits), f"{volume.rejected} of {volume.bronze_rows}")
    if volume.bronze_rows < limits.reject_min_rows:
        status = WARN if rate > limits.reject_warn else PASS
        return Check(name, status, shown, _reject_threshold(limits),
                     f"{volume.rejected} of {volume.bronze_rows}; file is under {limits.reject_min_rows} rows, so this warns")
    if rate > limits.reject_fail:
        status = FAIL
    elif rate > limits.reject_warn:
        status = WARN
    else:
        status = PASS
    return Check(name, status, shown, _reject_threshold(limits), f"{volume.rejected} of {volume.bronze_rows}")


def row_count(facts: QualityFacts, limits: Limits) -> Check:
    today = str(facts.loaded_members)
    if facts.previous_members is None:
        return Check("row_count", PASS, today, f"drop <= {limits.row_drop_fail:.0%}", "no previous day")
    if facts.previous_members == 0:
        return Check("row_count", PASS, today, f"drop <= {limits.row_drop_fail:.0%}", "previous day loaded nothing")
    drop = (facts.previous_members - facts.loaded_members) / facts.previous_members
    status = FAIL if drop > limits.row_drop_fail else PASS
    return Check("row_count", status, today, f"drop <= {limits.row_drop_fail:.0%}",
                 f"previous {facts.previous_members}, drop {drop:.0%}")


def null_rate(facts: QualityFacts, limits: Limits) -> Check:
    bronze = sum(volume.bronze_rows for volume in facts.files if not volume.source_file.startswith("redemptions_"))
    nulls = sum(volume.required_nulls for volume in facts.files)
    if bronze == 0:
        return Check("null_rate", PASS, "0", f"<= {limits.null_fail:.0%}", "no member rows")
    rate = nulls / bronze
    status = FAIL if rate > limits.null_fail else PASS
    return Check("null_rate", status, f"{rate:.1%}", f"<= {limits.null_fail:.0%}", f"{nulls} of {bronze}")


def unmapped_rate(facts: QualityFacts, limits: Limits) -> Check:
    if facts.loaded_members == 0:
        return Check("unmapped_countries", PASS, "0", f"fail > {limits.unmapped_fail:.0%}", "no loaded members")
    rate = facts.unmapped_rows / facts.loaded_members
    if rate > limits.unmapped_fail:
        status = FAIL
    elif facts.unmapped_rows:
        status = WARN
    else:
        status = PASS
    return Check("unmapped_countries", status, f"{rate:.1%}", f"fail > {limits.unmapped_fail:.0%}",
                 f"{facts.unmapped_rows} of {facts.loaded_members}")


def orphan_rate(facts: QualityFacts, limits: Limits) -> Check:
    if facts.redemption_rows == 0:
        return Check("redemption_orphans", PASS, "0", f"warn > {limits.orphan_warn:.0%}", "no redemptions")
    rate = facts.orphan_redemptions / facts.redemption_rows
    status = WARN if rate > limits.orphan_warn else PASS
    return Check("redemption_orphans", status, f"{rate:.1%}", f"warn > {limits.orphan_warn:.0%}",
                 f"{facts.orphan_redemptions} of {facts.redemption_rows}")


def write_report(path: Path, checks: list[Check]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        for check in checks:
            writer.writerow({
                "check": check.name,
                "status": check.status,
                "value": check.value,
                "threshold": check.threshold,
                "detail": check.detail,
            })


def previous_member_count(silver_dir: Path, as_of: date) -> int | None:
    """Loaded members from the latest earlier quality report that did not fail."""
    if not silver_dir.exists():
        return None
    earlier: list[date] = []
    for folder in silver_dir.iterdir():
        if not folder.is_dir():
            continue
        try:
            day = date.fromisoformat(folder.name)
        except ValueError:
            continue
        if day < as_of and (folder / "quality_report.csv").exists():
            earlier.append(day)
    if not earlier:
        return None
    report = silver_dir / max(earlier).isoformat() / "quality_report.csv"
    with open(report, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["check"] == "row_count" and row["status"] != FAIL:
                return int(row["value"])
    return None


def _reject_threshold(limits: Limits) -> str:
    return f"warn > {limits.reject_warn:.0%}, fail > {limits.reject_fail:.0%} from {limits.reject_min_rows} rows"


def _read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values
