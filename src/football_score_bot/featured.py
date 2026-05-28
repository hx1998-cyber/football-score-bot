from __future__ import annotations

from datetime import datetime
from typing import Any

from football_score_bot.config import Settings


LOWER_LEVEL_KEYWORDS = (
    "reserve",
    "reserves",
    "u19",
    "u20",
    "u21",
    "u23",
    "youth",
    "women reserve",
    "women reserves",
    " b ",
    "b team",
    " ii",
    "ii ",
    "league two china lower",
)


def is_featured_fixture(fixture: dict[str, Any], settings: Settings) -> bool:
    league = fixture.get("league", {})
    country = fixture.get("country", {}) or {}
    league_id = league.get("id")
    league_name = str(league.get("name") or "")
    country_name = str(country.get("name") or league.get("country") or "")
    haystack = f"{league_name} {country_name}".lower()

    if "world cup" in haystack:
        return True

    if isinstance(league_id, int) and league_id in settings.featured_league_ids:
        return True

    if _matches_any(league_name, settings.featured_keywords):
        return True

    if _matches_any(country_name, settings.featured_countries):
        return not _is_lower_level(league_name)

    return False


def filter_featured_fixtures(
    fixtures: list[dict[str, Any]],
    settings: Settings,
) -> list[dict[str, Any]]:
    featured = [item for item in fixtures if is_featured_fixture(item, settings)]
    featured.sort(key=_sort_key)
    return featured[: settings.max_featured_matches]


def _matches_any(value: str, patterns: list[str]) -> bool:
    normalized = value.lower()
    return any(pattern.lower() in normalized for pattern in patterns)


def _is_lower_level(league_name: str) -> bool:
    normalized = f" {league_name.lower()} "
    return any(keyword in normalized for keyword in LOWER_LEVEL_KEYWORDS)


def _sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
    league_name = str(item.get("league", {}).get("name") or "")
    timestamp = item.get("fixture", {}).get("timestamp")
    priority = 0 if "world cup" in league_name.lower() else 1
    if timestamp:
        return priority, datetime.fromtimestamp(timestamp).isoformat(), league_name
    return priority, str(item.get("fixture", {}).get("date") or ""), league_name
