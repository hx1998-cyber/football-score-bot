from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from football_score_bot.api_football import ApiFootballClient
from football_score_bot.cache import RedisCache
from football_score_bot.config import Settings
from football_score_bot.database import Database
from football_score_bot.featured import filter_featured_fixtures
from football_score_bot.formatters import format_group_featured_live
from football_score_bot.i18n import t
from football_score_bot.odds import build_odds_first_matches
from football_score_bot.time_utils import now_hhmm

logger = logging.getLogger(__name__)

LIVE_KEY = "football:live_fixtures"
LAST_LIVE_KEY = "football:last_update:live"
LAST_FEATURED_KEY = "football:last_update:featured"


class ScoreCacheWorker:
    def __init__(
        self,
        api_client: ApiFootballClient,
        cache: RedisCache,
        settings: Settings,
        bot: Bot | None = None,
        database: Database | None = None,
        bot_username: str | None = None,
    ) -> None:
        self._api_client = api_client
        self._cache = cache
        self._settings = settings
        self._bot = bot
        self._database = database
        self._bot_username = bot_username
        self._stop_event = asyncio.Event()
        self._last_broadcast_signature: str | None = None
        self._last_failure_log: dict[str, datetime] = {}

    async def run(self) -> None:
        tasks = [
            asyncio.create_task(self._loop("live", self._refresh_live, self._settings.live_refresh_seconds)),
            asyncio.create_task(self._loop("today", self._refresh_today, self._settings.today_refresh_seconds)),
            asyncio.create_task(self._loop("featured", self._refresh_featured, 60)),
            asyncio.create_task(self._loop("odds", self._refresh_featured_odds, self._settings.odds_refresh_seconds)),
        ]
        if self._bot and self._database:
            tasks.append(asyncio.create_task(self._loop("group_broadcast", self._broadcast_groups, 60)))
        try:
            await self._stop_event.wait()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def stop(self) -> None:
        self._stop_event.set()

    async def _loop(self, name: str, callback: Any, seconds: int) -> None:
        while not self._stop_event.is_set():
            try:
                await callback()
            except Exception as exc:
                self._log_api_failure(f"worker:{name}", "score cache worker %s update failed: %s", name, exc)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=max(seconds, 1))
            except asyncio.TimeoutError:
                continue

    async def _refresh_live(self) -> None:
        if not await self._cache.acquire_lock("football:lock:update_live", 55):
            return
        try:
            fixtures = await self._api_client.get_live_fixtures()
            await self._cache.set_json(LIVE_KEY, fixtures)
            await self._cache.set_text(LAST_LIVE_KEY, _now_hhmm())
            logger.info("score cache live fixtures updated: %s", len(fixtures))
        finally:
            await self._cache.release_lock("football:lock:update_live")

    async def _refresh_today(self) -> None:
        total = 0
        for offset in range(max(1, self._settings.bettable_days_ahead)):
            fixture_date = date.today() + timedelta(days=offset)
            try:
                fixtures = await self._api_client.get_fixtures_by_date(fixture_date)
            except Exception as exc:
                self._log_api_failure(
                    f"fixtures:{fixture_date.isoformat()}",
                    "score cache fixtures update failed date=%s; keeping existing cache: %s",
                    fixture_date.isoformat(),
                    exc,
                )
                continue
            await self._cache.set_json(f"football:today_fixtures:{fixture_date.isoformat()}", fixtures, ttl_seconds=300)
            total += len(fixtures)
        logger.info("score cache fixtures updated: %s", total)

    async def _refresh_featured(self) -> None:
        if not await self._cache.acquire_lock("football:lock:update_featured", 55):
            return
        try:
            today = date.today()
            all_fixtures = await self._cache.get_json(f"football:today_fixtures:{today.isoformat()}", [])
            if not all_fixtures:
                try:
                    all_fixtures = await self._api_client.get_fixtures_by_date(today)
                    await self._cache.set_json(f"football:today_fixtures:{today.isoformat()}", all_fixtures)
                except Exception as exc:
                    self._log_api_failure(
                        f"featured:{today.isoformat()}",
                        "score cache featured fixtures fetch failed date=%s; keeping existing cache: %s",
                        today.isoformat(),
                        exc,
                    )
                    return
            featured = filter_featured_fixtures(all_fixtures, self._settings)
            await self._cache.set_json(f"football:featured_matches:{today.isoformat()}", featured)
            await self._cache.set_text(LAST_FEATURED_KEY, _now_hhmm())

            live = await self._cache.get_json(LIVE_KEY, [])
            await self._cache.set_json(
                f"football:featured_live:{today.isoformat()}",
                filter_featured_fixtures(live, self._settings),
            )
            logger.info("score cache featured fixtures updated: %s", len(featured))
        finally:
            await self._cache.release_lock("football:lock:update_featured")

    async def _refresh_featured_odds(self) -> None:
        total_odds = 0
        total_matches = 0
        for offset in range(max(1, self._settings.bettable_days_ahead)):
            fixture_date = date.today() + timedelta(days=offset)
            date_key = fixture_date.isoformat()
            try:
                odds_items = await self._api_client.get_pre_match_odds_by_date(fixture_date)
                await self._cache.set_json(f"football:odds_raw:{date_key}", odds_items, ttl_seconds=120)
            except Exception as exc:
                self._log_api_failure(
                    f"odds:{date_key}",
                    "score cache odds update failed date=%s; keeping existing cache: %s",
                    date_key,
                    exc,
                )
                continue
            fixtures = await self._cache.get_json(f"football:today_fixtures:{date_key}", [])
            if not fixtures:
                try:
                    fixtures = await self._api_client.get_fixtures_by_date(fixture_date)
                    await self._cache.set_json(f"football:today_fixtures:{date_key}", fixtures, ttl_seconds=300)
                except Exception as exc:
                    self._log_api_failure(
                        f"odds-fixtures:{date_key}",
                        "score cache odds fixtures fetch failed date=%s; keeping existing cache: %s",
                        date_key,
                        exc,
                    )
                    continue
            odds_first_matches, odds_by_fixture = build_odds_first_matches(odds_items, fixtures)
            await self._cache.set_json(f"football:odds_first_matches:{date_key}", odds_first_matches, ttl_seconds=120)
            await self._cache.set_json(f"football:featured_odds:{date_key}", odds_by_fixture, ttl_seconds=120)
            await self._cache.set_json(f"football:bettable_matches:{date_key}", odds_first_matches, ttl_seconds=120)
            await self._cache.set_text(f"football:odds_first_matches:updated_at:{date_key}", _now_hhmm(), ttl_seconds=120)
            for item in odds_items:
                fixture_id = (item.get("fixture") or {}).get("id")
                if fixture_id is not None:
                    await self._cache.set_json(f"football:odds_raw:fixture:{fixture_id}", item, ttl_seconds=120)
            total_odds += len(odds_items)
            total_matches += len(odds_first_matches)
        logger.info(
            "score cache odds-first updated: odds_results=%s fixtures_with_match_winner=%s",
            total_odds,
            total_matches,
        )

    async def _broadcast_groups(self) -> None:
        today = date.today()
        featured_live = await self._cache.get_json(f"football:featured_live:{today.isoformat()}", [])
        if not featured_live:
            return
        event_lines = await self._group_event_lines(featured_live[:5])
        if not event_lines:
            return
        signature = "\n".join(event_lines)
        if signature == self._last_broadcast_signature:
            return
        self._last_broadcast_signature = signature

        last_update = await self._cache.get_text(LAST_LIVE_KEY) or _now_hhmm()
        text = "重点事件播报\n" + f"更新：{last_update}\n" + "\n".join(event_lines)
        groups = await self._database.list_subscribed_groups() if self._database else []
        open_bot_button = (
            InlineKeyboardButton(text=t("zh-CN", "group_link"), url=f"https://t.me/{self._bot_username}")
            if self._bot_username
            else InlineKeyboardButton(text=t("zh-CN", "group_link"), callback_data="home")
        )
        for chat_id in groups:
            try:
                await self._bot.send_message(
                    chat_id,
                    text,
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(text=t("zh-CN", "live_scores"), callback_data="live_featured"),
                                InlineKeyboardButton(text=t("zh-CN", "featured_matches"), callback_data="today_featured"),
                            ],
                            [open_bot_button],
                        ]
                    ),
                )
            except Exception:
                logger.warning("failed to broadcast featured live score to group %s", chat_id, exc_info=True)

    async def _group_event_lines(self, fixtures: list[dict[str, Any]]) -> list[str]:
        lines: list[str] = []
        for fixture in fixtures:
            fixture_id = fixture.get("fixture", {}).get("id")
            if fixture_id is None:
                continue
            key = f"football:fixture_events:{fixture_id}"
            events = await self._cache.get_json(key, None)
            if events is None:
                try:
                    events = await self._api_client.get_fixture_events(int(fixture_id))
                    await self._cache.set_json(key, events, ttl_seconds=300)
                    logger.info("fixture_events fixture_id=%s count=%s", fixture_id, len(events))
                except Exception as exc:
                    self._log_api_failure(
                        f"fixture-events:{fixture_id}",
                        "fixture_events fixture_id=%s failed; keeping existing cache: %s",
                        fixture_id,
                        exc,
                    )
                    continue
            teams = fixture.get("teams", {})
            label = f"{teams.get('home', {}).get('name', '主队')} vs {teams.get('away', {}).get('name', '客队')}"
            for event in events[-8:]:
                event_type = event.get("type")
                detail = str(event.get("detail") or "")
                if event_type != "Goal" and not (event_type == "Card" and "Red" in detail):
                    continue
                minute = event.get("time", {}).get("elapsed")
                player = event.get("player", {}).get("name") or "-"
                team = event.get("team", {}).get("name") or "-"
                icon = "⚽" if event_type == "Goal" else "🟥"
                lines.append(f"{icon} {minute}' {player} {team}｜{label}")
        return lines

    def _log_api_failure(self, key: str, message: str, *args: Any) -> None:
        now = datetime.now()
        last = self._last_failure_log.get(key)
        if last and (now - last).total_seconds() < 300:
            return
        self._last_failure_log[key] = now
        logger.warning(message, *args)


def _now_hhmm() -> str:
    return now_hhmm()
