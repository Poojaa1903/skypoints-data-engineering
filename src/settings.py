"""Read config/paths.env. One place for the folder paths.

The daily run is yesterday (T-1). A scheduled job passes no date and
processes the day that just closed. The sample files are dated
2024-01-15, so the demo passes that date explicitly.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PATHS_FILE = PROJECT_ROOT / "config" / "paths.env"


def load_paths(paths_file: Path = PATHS_FILE) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for line in paths_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        paths[key.strip()] = Path(value.strip())
    return paths


def previous_day(today: date | None = None) -> date:
    """The day a daily run processes: yesterday."""
    return (today or date.today()) - timedelta(days=1)
