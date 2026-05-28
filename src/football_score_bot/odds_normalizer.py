from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from football_score_bot.odds import PREFERRED_BOOKMAKERS


MARKET_TITLES = {
    "match_winner": "胜平负",
    "home_away": "主客胜",
    "correct_score": "波胆 / Correct Score",
    "correct_score_first_half": "上半场正确比分",
    "over_under": "大小球",
    "asian_handicap": "亚洲让球",
    "handicap": "让球",
    "ht_ft": "半场/全场",
    "btts": "双方进球",
    "double_chance": "双重机会",
    "corners_over_under": "角球大小",
    "goal_line": "进球线",
    "unknown": "其他赔率",
}


@dataclass
class OddsOutcome:
    label: str
    odds: str
    group: str | None = None
    suspended: bool = False


@dataclass
class OddsMarket:
    key: str
    title: str
    outcomes: list[OddsOutcome]


@dataclass
class NormalizedFixtureOdds:
    fixture_id: int
    bookmaker: str
    updated_at: str
    markets: dict[str, OddsMarket]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_fixture_odds(raw: dict[str, Any]) -> NormalizedFixtureOdds:
    fixture_id = _fixture_id(raw) or 0
    bookmaker = _choose_bookmaker(raw.get("bookmakers") or [])
    markets: dict[str, OddsMarket] = {}
    for bet in bookmaker.get("bets") or []:
        market_key = market_key_from_name(str(bet.get("name") or ""))
        outcomes = [
            OddsOutcome(
                label=str(value.get("value") or "-"),
                odds=str(value.get("odd") or "-"),
                group=_outcome_group(market_key, str(value.get("value") or "")),
                suspended=bool(value.get("suspended", False)),
            )
            for value in bet.get("values") or []
        ]
        if not outcomes:
            continue
        if market_key in markets:
            markets[market_key].outcomes.extend(outcomes)
        else:
            markets[market_key] = OddsMarket(
                key=market_key,
                title=MARKET_TITLES.get(market_key, bet.get("name") or "Odds"),
                outcomes=outcomes,
            )
    return NormalizedFixtureOdds(
        fixture_id=fixture_id,
        bookmaker=str(bookmaker.get("name") or "-"),
        updated_at=datetime.now(timezone.utc).isoformat(),
        markets=markets,
    )


def normalized_from_dict(data: dict[str, Any] | None) -> NormalizedFixtureOdds | None:
    if not data:
        return None
    markets = {
        key: OddsMarket(
            key=value.get("key") or key,
            title=value.get("title") or MARKET_TITLES.get(key, key),
            outcomes=[OddsOutcome(**outcome) for outcome in value.get("outcomes", [])],
        )
        for key, value in (data.get("markets") or {}).items()
    }
    return NormalizedFixtureOdds(
        fixture_id=int(data.get("fixture_id") or 0),
        bookmaker=str(data.get("bookmaker") or "-"),
        updated_at=str(data.get("updated_at") or ""),
        markets=markets,
    )


def market_key_from_name(name: str) -> str:
    normalized = name.lower()
    if normalized == "match winner" or any(token in normalized for token in ("1x2", "fulltime result")):
        return "match_winner"
    if normalized == "home/away":
        return "home_away"
    if normalized == "asian handicap":
        return "asian_handicap"
    if normalized == "handicap result":
        return "handicap"
    if normalized == "goals over/under":
        return "over_under"
    if normalized == "ht/ft double":
        return "ht_ft"
    if normalized == "both teams score":
        return "btts"
    if normalized == "exact score":
        return "correct_score"
    if normalized == "correct score - first half":
        return "correct_score_first_half"
    if normalized == "double chance":
        return "double_chance"
    if normalized == "corners over under":
        return "corners_over_under"
    if normalized == "goal line":
        return "goal_line"
    if "match winner" in normalized:
        return "match_winner"
    if any(token in normalized for token in ("correct score", "exact score")):
        return "correct_score"
    if any(token in normalized for token in ("over/under", "total goals")):
        return "over_under"
    if "asian handicap" in normalized:
        return "asian_handicap"
    if "handicap" in normalized:
        return "handicap"
    if any(token in normalized for token in ("ht/ft", "half time/full time", "half-time/full-time")):
        return "ht_ft"
    if any(token in normalized for token in ("both teams score", "btts")):
        return "btts"
    return "unknown"


def _fixture_id(raw: dict[str, Any]) -> int | None:
    fixture = raw.get("fixture")
    if isinstance(fixture, dict):
        value = fixture.get("id")
    else:
        value = raw.get("fixture_id")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _choose_bookmaker(bookmakers: list[dict[str, Any]]) -> dict[str, Any]:
    if not bookmakers:
        return {"name": "-", "bets": []}
    for preferred in PREFERRED_BOOKMAKERS:
        for bookmaker in bookmakers:
            if preferred in str(bookmaker.get("name") or "").lower():
                return bookmaker
    return bookmakers[0]


def _outcome_group(market_key: str, label: str) -> str | None:
    normalized = label.strip().lower()
    if market_key == "match_winner":
        if normalized in {"home", "1"}:
            return "home"
        if normalized in {"draw", "x"}:
            return "draw"
        if normalized in {"away", "2"}:
            return "away"
    if market_key in {"over_under", "corners_over_under", "goal_line"}:
        if normalized.startswith("over"):
            return "over"
        if normalized.startswith("under"):
            return "under"
    if market_key in {"correct_score", "correct_score_first_half"}:
        score = normalized.replace("-", ":")
        parts = score.split(":")
        if len(parts) == 2 and all(part.strip().isdigit() for part in parts):
            home, away = int(parts[0]), int(parts[1])
            if home > away:
                return "home"
            if home == away:
                return "draw"
            return "away"
    if market_key == "btts":
        if normalized in {"yes", "y"}:
            return "yes"
        if normalized in {"no", "n"}:
            return "no"
    return None
