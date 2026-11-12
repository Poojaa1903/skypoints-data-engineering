"""Resolve the country code in a feed to a stored country code.

Lookup order:

1. Blank or NULL -> MISSING. Nothing is registered.
2. Real ISO code (2-letter or 3-letter) -> MAPPED, stored as the 3-letter code.
3. Known alias (for example PHIL -> PHL) -> ALIAS.
4. Anything else -> UNMAPPED. The raw code is kept and flagged for
   registration, so the next file finds it. The run does not stop.

Lookups are loaded once per run from the two CSV files in config/.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class CountryStatus(Enum):
    MAPPED = "MAPPED"
    ALIAS = "ALIAS"
    UNMAPPED = "UNMAPPED"
    MISSING = "MISSING"


@dataclass(frozen=True)
class Lookups:
    iso: dict[str, str]      # 2-letter or 3-letter ISO code -> 3-letter code
    aliases: dict[str, str]  # source code that is not ISO -> 3-letter code


@dataclass(frozen=True)
class CountryMatch:
    country_code: str | None
    status: CountryStatus
    register: bool  # True when the code is new and should be added to the reference


def load_lookups(iso_path: Path, alias_path: Path) -> Lookups:
    iso: dict[str, str] = {}
    with open(iso_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            alpha3 = row["alpha3"].strip().upper()
            iso[row["alpha2"].strip().upper()] = alpha3
            iso[alpha3] = alpha3

    aliases: dict[str, str] = {}
    with open(alias_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            aliases[row["source_code"].strip().upper()] = row["alpha3"].strip().upper()

    return Lookups(iso=iso, aliases=aliases)


def resolve_country(raw: str | None, lookups: Lookups) -> CountryMatch:
    if raw is None or raw.strip().upper() in {"", "NULL"}:
        return CountryMatch(country_code=None, status=CountryStatus.MISSING, register=False)

    code = raw.strip().upper()

    if code in lookups.iso:
        return CountryMatch(country_code=lookups.iso[code], status=CountryStatus.MAPPED, register=False)

    if code in lookups.aliases:
        return CountryMatch(country_code=lookups.aliases[code], status=CountryStatus.ALIAS, register=False)

    return CountryMatch(country_code=code, status=CountryStatus.UNMAPPED, register=True)
