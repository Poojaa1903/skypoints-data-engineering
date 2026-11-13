"""Read local/pipeline.env. One file for paths, the monitoring date, and quality limits.

A run restores every day from MONITORING_DATE through yesterday. Days
before the monitoring date are left alone. The sample date is 2024-01-15.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / "local" / "pipeline.env"


PATH_KEYS = {"SOURCE_DIR", "OUTPUT_DIR", "BRONZE_DIR", "SILVER_DIR", "GOLD_DIR"}


def load_env(env_file: Path = ENV_FILE) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def load_paths(env_file: Path = ENV_FILE) -> dict[str, Path]:
    return {key: Path(value) for key, value in load_env(env_file).items() if key in PATH_KEYS}


def monitoring_date(env: dict[str, str] | None = None) -> date:
    """First day a backfill may restore. Set MONITORING_DATE in local/pipeline.env."""
    raw = (env if env is not None else load_env()).get("MONITORING_DATE", "")
    if not raw:
        raise ValueError("Set MONITORING_DATE in local/pipeline.env")
    return date.fromisoformat(raw)


def previous_day(today: date | None = None) -> date:
    """The day a daily run processes: yesterday."""
    return (today or date.today()) - timedelta(days=1)
