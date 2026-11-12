"""Tests for resolving a raw country code to a stored country.

Order, using the real lookup files:

1. Blank or NULL -> no country, status MISSING. Nothing is registered.
2. Real ISO code, 2-letter or 3-letter -> ISO 3-letter code, status MAPPED.
3. A known alias such as PHIL -> the ISO code it means, status ALIAS.
4. Anything else -> keep the raw code, status UNMAPPED, and register it
   so the next file finds it. The run does not stop.

Lookup is case-insensitive and ignores surrounding spaces.
"""

from pathlib import Path

import pytest

from skypoints.countries import CountryStatus, load_lookups, resolve_country

ROOT = Path(__file__).resolve().parents[1]
LOOKUPS = None


@pytest.fixture(scope="module")
def lookups():
    return load_lookups(
        ROOT / "config" / "iso_countries.csv",
        ROOT / "config" / "country_aliases.csv",
    )


def test_usa_is_an_iso_code(lookups):
    # Elena's country in the flat file.
    match = resolve_country("USA", lookups)
    assert match.country_code == "USA"
    assert match.status is CountryStatus.MAPPED
    assert match.register is False


def test_au_two_letter_code_becomes_aus(lookups):
    # Jacob's country. AU is the 2-letter ISO code for Australia.
    match = resolve_country("AU", lookups)
    assert match.country_code == "AUS"
    assert match.status is CountryStatus.MAPPED
    assert match.register is False


def test_ind_and_can_are_iso_codes(lookups):
    # Ravi and Nora.
    assert resolve_country("IND", lookups).country_code == "IND"
    assert resolve_country("CAN", lookups).country_code == "CAN"


def test_phil_uses_the_alias_file(lookups):
    # Mateo. PHIL is not an ISO code. The alias file maps it to PHL.
    match = resolve_country("PHIL", lookups)
    assert match.country_code == "PHL"
    assert match.status is CountryStatus.ALIAS
    assert match.register is False


def test_unknown_code_is_kept_and_registered(lookups):
    # A code that arrives tomorrow and is in neither file.
    match = resolve_country("UK", lookups)
    assert match.country_code == "UK"
    assert match.status is CountryStatus.UNMAPPED
    assert match.register is True


def test_lookup_ignores_case_and_spaces(lookups):
    match = resolve_country("  au ", lookups)
    assert match.country_code == "AUS"
    assert match.status is CountryStatus.MAPPED


@pytest.mark.parametrize("raw", [None, "", "   ", "NULL", "null"])
def test_blank_country_is_missing_and_not_registered(raw, lookups):
    match = resolve_country(raw, lookups)
    assert match.country_code is None
    assert match.status is CountryStatus.MISSING
    assert match.register is False
