from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from football_score_bot.config import Settings


PRE_MATCH_STATUSES = {"NS", "TBD"}
LIVE_STATUSES = {"1H", "2H", "HT", "ET", "BT", "P", "LIVE", "INT"}
FINISHED_STATUSES = {"FT", "AET", "PEN", "CANC", "PST", "SUSP", "ABD", "AWD", "WO"}


@dataclass(frozen=True)
class BettableStatus:
    is_bettable: bool
    reason: str


def is_bettable_fixture(
    fixture: dict[str, Any],
    odds: Any,
    settings: Settings,
    *,
    is_suspended_by_admin: bool = False,
) -> BettableStatus:
    if is_suspended_by_admin:
        return BettableStatus(False, "suspended_by_admin")

    status = str((fixture.get("fixture") or {}).get("status", {}).get("short") or "").upper()
    if status in FINISHED_STATUSES:
        return BettableStatus(False, "finished")
    if status in LIVE_STATUSES and not settings.enable_live_betting:
        return BettableStatus(False, "already_started")
    if status not in PRE_MATCH_STATUSES:
        return BettableStatus(False, "unsupported_status")

    if not _has_odds(odds):
        return BettableStatus(False, "no_odds")
    if not _has_display_market(odds):
        return BettableStatus(False, "no_market")

    kickoff = _kickoff_datetime(fixture)
    if kickoff and datetime.now() >= kickoff - timedelta(minutes=settings.bet_cutoff_minutes):
        return BettableStatus(False, "cutoff_reached")

    return BettableStatus(True, "bettable")


def reason_label(reason: str) -> str:
    return {
        "bettable": "可投注",
        "no_odds": "赔率暂未开放",
        "already_started": "已开赛",
        "cutoff_reached": "已封盘",
        "finished": "已完场",
        "suspended_by_admin": "已封盘",
        "unsupported_status": "暂不可投注",
        "no_market": "赔率暂未开放",
    }.get(reason, "暂不可投注")


def _has_odds(odds: Any) -> bool:
    if not odds:
        return False
    markets = getattr(odds, "markets", None)
    if markets is not None:
        return bool(markets)
    if isinstance(odds, dict):
        return bool(odds.get("bookmakers") or odds.get("markets") or odds.get("home_odds"))
    return True


def _has_display_market(odds: Any) -> bool:
    markets = getattr(odds, "markets", None)
    if isinstance(markets, dict):
        return any(market.outcomes for market in markets.values())
    if isinstance(odds, dict):
        markets = odds.get("markets")
        if isinstance(markets, dict):
            return any((market.get("outcomes") or []) for market in markets.values())
        return any(odds.get(key) for key in ("home_odds", "draw_odds", "away_odds"))
    return False


def _kickoff_datetime(fixture: dict[str, Any]) -> datetime | None:
    fixture_info = fixture.get("fixture") or {}
    timestamp = fixture_info.get("timestamp")
    if timestamp:
        try:
            return datetime.fromtimestamp(int(timestamp))
        except (TypeError, ValueError, OSError):
            return None
    raw = fixture_info.get("date")
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
        except ValueError:
            return None
    return None
