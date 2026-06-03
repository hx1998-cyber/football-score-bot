from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from football_score_bot.api_football import ApiFootballClient
from football_score_bot.betting import is_bettable_fixture
from football_score_bot.cache import RedisCache
from football_score_bot.config import Settings
from football_score_bot.database import Database
from football_score_bot.odds import build_odds_first_matches
from football_score_bot.services.broadcast_service import safe_send_message

logger = logging.getLogger(__name__)


class CommunityBroadcastJob:
    def __init__(
        self,
        bot: Bot,
        api_client: ApiFootballClient,
        cache: RedisCache,
        database: Database,
        settings: Settings,
        *,
        bot_username: str | None = None,
    ) -> None:
        self._bot = bot
        self._api_client = api_client
        self._cache = cache
        self._database = database
        self._settings = settings
        self._bot_username = (bot_username or settings.bot_username or "").lstrip("@")
        self._stop_event = asyncio.Event()
        self._last_hour_key: str | None = None
        self._sent_reminders: set[str] = set()
        self._announced_results: set[int] = set()

    async def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.warning("community broadcast iteration failed", exc_info=True)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stop_event.set()

    async def run_once(self) -> None:
        now = datetime.now(timezone.utc)
        if now.minute == 0:
            hour_key = now.strftime("%Y%m%d%H")
            if hour_key != self._last_hour_key:
                self._last_hour_key = hour_key
                await self.send_hourly_featured()
        await self.send_match_reminders(now)
        await self.send_settlement_results()

    async def send_hourly_featured(self) -> None:
        fixtures, odds_by_fixture = await self._featured_bettable_matches()
        if not fixtures:
            logger.info("hourly_featured_skipped reason=no_matches")
            return
        await safe_send_message(
            self._bot,
            self._settings.announcement_channel_id,
            _format_hourly_featured(fixtures, odds_by_fixture, self._settings.bet_cutoff_minutes, "zh", mixed=True),
            reply_markup=_broadcast_keyboard("zh", self._bot_username),
        )
        await safe_send_message(
            self._bot,
            self._settings.community_group_cn_id,
            _format_hourly_featured(fixtures, odds_by_fixture, self._settings.bet_cutoff_minutes, "zh"),
            reply_markup=_broadcast_keyboard("zh", self._bot_username),
        )
        await safe_send_message(
            self._bot,
            self._settings.community_group_en_id,
            _format_hourly_featured(fixtures, odds_by_fixture, self._settings.bet_cutoff_minutes, "en"),
            reply_markup=_broadcast_keyboard("en", self._bot_username),
        )

    async def send_match_reminders(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        fixtures, odds_by_fixture = await self._featured_bettable_matches(limit=20)
        for fixture in fixtures:
            kickoff = _fixture_datetime(fixture)
            fixture_id = _fixture_id(fixture)
            if not kickoff or fixture_id is None:
                continue
            minutes_to_kickoff = int((kickoff - now).total_seconds() // 60)
            if not 25 <= minutes_to_kickoff <= 35:
                continue
            close_time = kickoff - timedelta(minutes=self._settings.bet_cutoff_minutes)
            close_minutes = int((close_time - now).total_seconds() // 60)
            if close_minutes <= 0:
                continue
            key = f"30:{fixture_id}"
            if key in self._sent_reminders:
                continue
            self._sent_reminders.add(key)
            odds = odds_by_fixture.get(fixture_id) or odds_by_fixture.get(str(fixture_id)) or {}
            await safe_send_message(
                self._bot,
                self._settings.community_group_cn_id,
                _format_match_reminder(fixture, odds, minutes_to_kickoff, close_minutes, "zh"),
                reply_markup=_bet_now_keyboard("zh", self._bot_username),
            )
            await safe_send_message(
                self._bot,
                self._settings.community_group_en_id,
                _format_match_reminder(fixture, odds, minutes_to_kickoff, close_minutes, "en"),
                reply_markup=_bet_now_keyboard("en", self._bot_username),
            )

    async def send_settlement_results(self) -> None:
        rows = await self._database.pool.fetch(
            """
            SELECT DISTINCT ON (b.fixture_id)
                b.fixture_id, b.fixture_label, b.home_team, b.away_team, b.result_score, b.settled_at
            FROM bets b
            WHERE b.fixture_id IS NOT NULL
              AND b.result_score IS NOT NULL
              AND b.settlement_source = 'auto'
              AND b.status IN ('won', 'lost', 'void')
              AND b.bettable_status_at_submit = 'bettable'
              AND b.settled_at >= NOW() - INTERVAL '24 hours'
            ORDER BY b.fixture_id, b.settled_at DESC
            LIMIT 20
            """
        )
        for row in rows:
            fixture_id = int(row["fixture_id"])
            if fixture_id in self._announced_results:
                continue
            self._announced_results.add(fixture_id)
            zh_text = _format_result_announcement(dict(row), "zh")
            en_text = _format_result_announcement(dict(row), "en")
            await safe_send_message(self._bot, self._settings.announcement_channel_id, zh_text + "\n\n" + en_text)
            await safe_send_message(self._bot, self._settings.community_group_cn_id, zh_text)
            await safe_send_message(self._bot, self._settings.community_group_en_id, en_text)

    async def send_test_broadcast(self) -> None:
        await safe_send_message(self._bot, self._settings.announcement_channel_id, "测试广播 / Test broadcast")
        await safe_send_message(self._bot, self._settings.community_group_cn_id, "测试广播：中文社区群")
        await safe_send_message(self._bot, self._settings.community_group_en_id, "Test broadcast: English community group")

    async def _featured_bettable_matches(self, limit: int = 5) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
        fixtures: list[dict[str, Any]] = []
        odds_by_fixture: dict[int, dict[str, Any]] = {}
        for offset in range(max(1, min(self._settings.bettable_days_ahead, 2))):
            fixture_date = date.today() + timedelta(days=offset)
            date_key = fixture_date.isoformat()
            date_fixtures = await self._cache.get_json(f"football:today_fixtures:{date_key}", [])
            odds_items = await self._cache.get_json(f"football:odds_raw:{date_key}", [])
            if not date_fixtures:
                date_fixtures = await self._api_client.get_fixtures_by_date(fixture_date)
                await self._cache.set_json(f"football:today_fixtures:{date_key}", date_fixtures, ttl_seconds=300)
            if not odds_items:
                odds_items = await self._api_client.get_pre_match_odds_by_date(fixture_date)
                await self._cache.set_json(f"football:odds_raw:{date_key}", odds_items, ttl_seconds=120)
            matches, odds_map = build_odds_first_matches(odds_items, date_fixtures)
            for item in matches:
                fixture_id = _fixture_id(item)
                odds = odds_map.get(fixture_id or 0)
                if fixture_id is None or not odds:
                    continue
                override = await self._database.get_market_override(fixture_id)
                status = is_bettable_fixture(
                    item,
                    odds,
                    self._settings,
                    is_suspended_by_admin=bool(override and override.get("is_suspended")),
                )
                if status.is_bettable:
                    fixtures.append(item)
                    odds_by_fixture[fixture_id] = odds
        fixtures.sort(key=_match_sort_key)
        return fixtures[:limit], odds_by_fixture


def _broadcast_keyboard(lang: str, bot_username: str) -> InlineKeyboardMarkup:
    url = f"https://t.me/{bot_username}" if bot_username else None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎯 Bettable Matches" if lang == "en" else "🎯 查看可投注赛事", url=url or "https://t.me/")],
            [InlineKeyboardButton(text="🤖 Open Bot" if lang == "en" else "🤖 打开下单机器人", url=url or "https://t.me/")],
        ]
    )


def _bet_now_keyboard(lang: str, bot_username: str) -> InlineKeyboardMarkup:
    url = f"https://t.me/{bot_username}" if bot_username else "https://t.me/"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎯 Bet Now" if lang == "en" else "🎯 前往投注", url=url)]])


def _format_hourly_featured(
    fixtures: list[dict[str, Any]],
    odds_by_fixture: dict[int, dict[str, Any]],
    cutoff_minutes: int,
    lang: str,
    *,
    mixed: bool = False,
) -> str:
    title = "🔥 Hourly Featured Matches" if lang == "en" else "🔥 每小时热门赛事"
    lines = [title, ""]
    for index, fixture in enumerate(fixtures[:5], start=1):
        fixture_id = _fixture_id(fixture)
        odds = odds_by_fixture.get(fixture_id or 0) or {}
        lines.extend(
            [
                f"{index}. {_match_title(fixture)}",
                f"   {_fixture_time(fixture)}",
                (
                    f"   Odds: Home {_odd(odds, 'home_odds')} | Draw {_odd(odds, 'draw_odds')} | Away {_odd(odds, 'away_odds')}"
                    if lang == "en"
                    else f"   赔率：主胜 {_odd(odds, 'home_odds')}｜平 {_odd(odds, 'draw_odds')}｜客胜 {_odd(odds, 'away_odds')}"
                ),
                (
                    f"   Bet closes: {cutoff_minutes} minutes before kickoff"
                    if lang == "en"
                    else f"   封盘：开赛前 {cutoff_minutes} 分钟"
                ),
                "",
            ]
        )
    lines.append("Open the bot below to view details." if lang == "en" else "点击下方按钮进入机器人查看详情。")
    if mixed:
        lines.append("Open the bot below to view details.")
    return "\n".join(lines)


def _format_match_reminder(fixture: dict[str, Any], odds: dict[str, Any], kickoff_minutes: int, close_minutes: int, lang: str) -> str:
    if lang == "en":
        return (
            "Match Reminder\n\n"
            f"{_match_title(fixture)}\n"
            f"Kickoff in {kickoff_minutes} minutes.\n"
            f"Betting closes in about {close_minutes} minutes.\n\n"
            "Current odds:\n"
            f"Home {_odd(odds, 'home_odds')} | Draw {_odd(odds, 'draw_odds')} | Away {_odd(odds, 'away_odds')}"
        )
    return (
        "开赛提醒\n\n"
        f"{_match_title(fixture)}\n"
        f"将在 {kickoff_minutes} 分钟后开始。\n"
        f"预计 {close_minutes} 分钟后截止下注。\n\n"
        "当前赔率：\n"
        f"主胜 {_odd(odds, 'home_odds')}｜平 {_odd(odds, 'draw_odds')}｜客胜 {_odd(odds, 'away_odds')}"
    )


def _format_result_announcement(row: dict[str, Any], lang: str) -> str:
    home = row.get("home_team") or "Home"
    away = row.get("away_team") or "Away"
    score = str(row.get("result_score") or "0:0").replace(":", " - ")
    outcome = _score_outcome(str(row.get("result_score") or "0:0"), lang)
    if lang == "en":
        return f"Match Result\n\n{home} {score} {away}\nResult: {outcome}\n\nThis bettable match has been settled."
    return f"赛果公告\n\n{home} {score} {away}\n结果：{outcome}\n\n本场可投注赛事已完成结算。"


def _score_outcome(score: str, lang: str) -> str:
    try:
        home_text, away_text = score.replace("-", ":").split(":", 1)
        home, away = int(home_text), int(away_text)
    except ValueError:
        return "Draw" if lang == "en" else "平局"
    if home > away:
        return "Home Win" if lang == "en" else "主胜"
    if home < away:
        return "Away Win" if lang == "en" else "客胜"
    return "Draw" if lang == "en" else "平局"


def _fixture_id(item: dict[str, Any]) -> int | None:
    try:
        return int((item.get("fixture") or {}).get("id"))
    except (TypeError, ValueError):
        return None


def _fixture_datetime(item: dict[str, Any]) -> datetime | None:
    fixture = item.get("fixture") or {}
    timestamp = fixture.get("timestamp")
    if timestamp is not None:
        try:
            return datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            pass
    raw_date = fixture.get("date")
    if raw_date:
        try:
            value = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _fixture_time(item: dict[str, Any]) -> str:
    kickoff = _fixture_datetime(item)
    return kickoff.astimezone().strftime("%H:%M") if kickoff else "--:--"


def _match_title(item: dict[str, Any]) -> str:
    teams = item.get("teams") or {}
    home = (teams.get("home") or {}).get("name") or "Home"
    away = (teams.get("away") or {}).get("name") or "Away"
    return f"{home} vs {away}"


def _odd(odds: dict[str, Any], key: str) -> str:
    return str(odds.get(key) or "-")


def _match_sort_key(item: dict[str, Any]) -> tuple[int, int]:
    league = str((item.get("league") or {}).get("name") or "").lower()
    worldcup = 0 if "world cup" in league else 1
    kickoff = _fixture_datetime(item)
    timestamp = int(kickoff.timestamp()) if kickoff else 9_999_999_999
    return worldcup, timestamp
