"""Split the latest member records into one gold table per country.

Each winner goes into Table_<CODE>. Every superseded record whose old
country is different from the winner's country becomes a removal, so the
gold load can delete that member from the old table.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gold.latest import LatestResult, MemberRecord


@dataclass
class GoldSplit:
    tables: dict[str, list[MemberRecord]] = field(default_factory=dict)
    removals: list[tuple[str, str]] = field(default_factory=list)  # (member_id, old country)


def table_name_for(country_code: str) -> str:
    return f"Table_{country_code}"


def split_by_country(result: LatestResult) -> GoldSplit:
    gold = GoldSplit()

    for member_id, winner in result.winners.items():
        if not winner.country_code:
            raise ValueError(f"member {member_id} has no country and cannot be placed")
        gold.tables.setdefault(table_name_for(winner.country_code), []).append(winner)

    for loser in result.superseded:
        winner = result.winners[loser.member_id]
        if loser.country_code and loser.country_code != winner.country_code:
            gold.removals.append((loser.member_id, loser.country_code))

    return gold
