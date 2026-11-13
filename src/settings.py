"""Read config/paths.env. One place for the folder paths."""

from __future__ import annotations

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
