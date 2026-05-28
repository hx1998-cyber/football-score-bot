from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


PREFERRED_BOOKMAKERS = (
    "bet365",
    "pinnacle",
    "william hill",
    "1xbet",
    "marathonbet",
)

WIN_MARKETS = ("match winner", "1x2", "fulltime result")
HOME_LABELS = {"home", "1"}
DRAW_LABELS = {"draw", "x"}
AWAY_LABELS = {"away", "2"}


def normalize_odds_response(items: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    normalized: dict[int, dict[str, Any]] = {}
    for item in items:
        fixture_id = _fixture_id(item)
        if fixture_id is None:
            continue
        odds = normalize_fixture_odds(item)
        if odds:
            normalized[fixture_id] = odds
    return normalized


def normalize_fixture_odds(item: dict[str, Any]) -> dict[str, Any] | None:
    fixture_id = _fixture_id(item)
    bookmakers = item.get("bookmakers") or []
    if fixture_id is None or not bookmakers:
        return None

    bookmaker, market = _choose_bookmaker_market(bookmakers)
    if not bookmaker or not market:
        return None

    values = market.get("values") or []
    home_odds = draw_odds = away_odds = None
    for value in values:
        label = str(value.get("value") or "").strip().lower()
        odd = value.get("odd")
        if label in HOME_LABELS:
            home_odds = odd
        elif label in DRAW_LABELS:
            draw_odds = odd
        elif label in AWAY_LABELS:
            away_odds = odd

    return {
        "fixture_id": fixture_id,
        "home_odds": home_odds,
        "draw_odds": draw_odds,
        "away_odds": away_odds,
        "bookmaker": bookmaker.get("name") or "-",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def build_odds_first_matches(
    odds_items: list[dict[str, Any]],
    fixtures: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    fixture_index = {
        fixture_id: item
        for item in fixtures
        if (fixture_id := _fixture_id(item)) is not None
    }
    matches: list[dict[str, Any]] = []
    odds_by_fixture: dict[int, dict[str, Any]] = {}
    for odds_item in odds_items:
        fixture_id = _fixture_id(odds_item)
        if fixture_id is None:
            continue
        match_winner = normalize_fixture_odds(odds_item)
        if not match_winner:
            continue
        match = _merge_odds_fixture(odds_item, fixture_index.get(fixture_id))
        matches.append(match)
        odds_by_fixture[fixture_id] = match_winner
    matches.sort(key=lambda item: int((item.get("fixture") or {}).get("timestamp") or 0))
    return matches, odds_by_fixture


def available_market_names(item: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for bookmaker in item.get("bookmakers") or []:
        for bet in bookmaker.get("bets") or []:
            name = str(bet.get("name") or "").strip()
            if name and name not in names:
                names.append(name)
    return names


def _fixture_id(item: dict[str, Any]) -> int | None:
    fixture = item.get("fixture")
    if isinstance(fixture, dict):
        fixture_id = fixture.get("id")
    else:
        fixture_id = item.get("fixture_id")
    try:
        return int(fixture_id)
    except (TypeError, ValueError):
        return None


def _choose_bookmaker(bookmakers: list[dict[str, Any]]) -> dict[str, Any]:
    for preferred in PREFERRED_BOOKMAKERS:
        for bookmaker in bookmakers:
            if preferred in str(bookmaker.get("name") or "").lower():
                return bookmaker
    return bookmakers[0]


def _choose_bookmaker_market(bookmakers: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    ordered = []
    for preferred in PREFERRED_BOOKMAKERS:
        ordered.extend(
            bookmaker
            for bookmaker in bookmakers
            if preferred in str(bookmaker.get("name") or "").lower() and bookmaker not in ordered
        )
    ordered.extend(bookmaker for bookmaker in bookmakers if bookmaker not in ordered)
    for bookmaker in ordered:
        market = _choose_market(bookmaker.get("bets") or [])
        if market:
            return bookmaker, market
    return None, None


def _choose_market(markets: list[dict[str, Any]]) -> dict[str, Any] | None:
    for market in markets:
        name = str(market.get("name") or "").lower()
        if any(win_market in name for win_market in WIN_MARKETS):
            return market
    return None


def _merge_odds_fixture(odds_item: dict[str, Any], fixture_item: dict[str, Any] | None) -> dict[str, Any]:
    fixture = dict((fixture_item or {}).get("fixture") or {})
    league = dict((fixture_item or {}).get("league") or {})
    teams = dict((fixture_item or {}).get("teams") or {})
    goals = dict((fixture_item or {}).get("goals") or {})

    odds_fixture = odds_item.get("fixture")
    if isinstance(odds_fixture, dict):
        fixture.update({key: value for key, value in odds_fixture.items() if value is not None})
    odds_league = odds_item.get("league")
    if isinstance(odds_league, dict):
        league.update({key: value for key, value in odds_league.items() if value is not None})

    if "id" not in fixture:
        fixture["id"] = _fixture_id(odds_item)
    return {
        "fixture": fixture,
        "league": league,
        "teams": teams,
        "goals": goals,
        "odds_item": odds_item,
    }
