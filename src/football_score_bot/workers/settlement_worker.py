from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

import httpx
from aiogram import Bot

from football_score_bot.api_football import ApiFootballClient
from football_score_bot.config import Settings
from football_score_bot.database import Database
from football_score_bot.services.settlement_service import SettlementService
from football_score_bot.services.wallet_service import WalletService

logger = logging.getLogger(__name__)


class SettlementWorker:
    def __init__(
        self,
        api_client: ApiFootballClient,
        database: Database,
        settings: Settings,
        *,
        bot: Bot | None = None,
        bot_username: str | None = None,
    ) -> None:
        self._api_client = api_client
        self._database = database
        self._settings = settings
        self._bot = bot
        self._bot_username = bot_username
        self._stopped = asyncio.Event()
        wallet_service = WalletService(
            database,
            currency=settings.wallet_currency,
            referral_deposit_commission_rate=settings.referral_deposit_commission_rate,
            referral_agent_enabled=settings.referral_agent_enabled,
            payout_freeze_enabled=settings.payout_freeze_enabled,
            payout_freeze_hours=settings.payout_freeze_hours,
        )
        self._settlement_service = SettlementService(
            database,
            wallet_service,
            real_betting_enabled=settings.real_betting_enabled,
        )

    async def run(self) -> None:
        if not self._settings.bet_auto_settlement_enabled:
            return
        while not self._stopped.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.warning("settlement worker iteration failed", exc_info=True)
            try:
                await asyncio.wait_for(
                    self._stopped.wait(),
                    timeout=self._settings.bet_settlement_interval_seconds,
                )
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stopped.set()

    async def run_once(self) -> None:
        bets = await self._database.list_pending_bets_for_settlement(200)
        by_fixture: dict[int, list[dict]] = defaultdict(list)
        for bet in bets:
            fixture_id = bet.get("fixture_id")
            if fixture_id is not None:
                by_fixture[int(fixture_id)].append(bet)
        for fixture_id, fixture_bets in by_fixture.items():
            try:
                fixture = await self._api_client.get_fixture_detail(fixture_id)
            except (httpx.HTTPError, OSError):
                logger.warning("fixture settlement fetch failed fixture_id=%s", fixture_id, exc_info=True)
                continue
            for bet in fixture_bets:
                outcome = await self._settlement_service.settle_bet_from_fixture(bet, fixture, source="auto")
                if outcome.get("settled"):
                    await self._notify_user(bet, outcome.get("status") or "")

    async def _notify_user(self, bet: dict, status: str) -> None:
        if not self._bot:
            return
        user_id = int(bet.get("user_id") or bet.get("telegram_user_id") or 0)
        if not user_id:
            return
        text = _settlement_message(bet, status, self._settings.wallet_currency)
        try:
            await self._bot.send_message(user_id, text)
        except Exception:
            logger.warning("failed to send settlement notification bet_id=%s", bet.get("id"), exc_info=True)
        if status != "won" or not self._settings.settlement_notify_group_enabled:
            return
        if not self._settings.settlement_group_chat_id:
            return
        try:
            payout = float(bet.get("potential_payout") or 0)
        except (TypeError, ValueError):
            payout = 0
        if payout < float(self._settings.settlement_public_win_min_payout):
            return
        link = f"https://t.me/{self._bot_username}" if self._bot_username else None
        group_text = (
            "🎉 恭喜玩家中奖\n\n"
            f"玩法：{bet.get('market_title') or bet.get('market_key')}\n"
            f"选择：{bet.get('selection')}\n"
            f"赔率：{bet.get('odds')}\n"
            f"返还：{bet.get('potential_payout')} {self._settings.wallet_currency}"
        )
        try:
            await self._bot.send_message(self._settings.settlement_group_chat_id, group_text + (f"\n\n继续参与：{link}" if link else ""))
        except Exception:
            logger.warning("failed to send public settlement notification", exc_info=True)


def _settlement_message(bet: dict, status: str, currency: str) -> str:
    bet_no = bet.get("bet_no") or bet.get("id")
    if status == "won":
        return (
            "🎉 注单中奖\n\n"
            f"注单号：{bet_no}\n"
            f"比赛：{bet.get('fixture_label')}\n"
            f"玩法：{bet.get('market_title') or bet.get('market_key')}\n"
            f"选择：{bet.get('selection')}\n"
            f"金额：{bet.get('stake')} {currency}\n"
            f"赔率：{bet.get('odds')}\n"
            f"返还：{bet.get('potential_payout')} {currency}"
        )
    if status == "void":
        return f"注单已作废退款\n\n注单号：{bet_no}\n原因：比赛取消/异常\n退款：{bet.get('stake')} {currency}"
    return (
        "📉 注单未中奖\n\n"
        f"注单号：{bet_no}\n"
        f"比赛：{bet.get('fixture_label')}\n"
        f"选择：{bet.get('selection')}\n"
        "状态：未中奖"
    )

# M11-Fix-3 wording override.
def _settlement_message(bet: dict, status: str, currency: str) -> str:
    bet_no = bet.get("bet_no") or bet.get("id")
    if status == "won":
        return (
            "🎉 注单已开奖：中奖\n\n"
            f"注单号：{bet_no}\n"
            f"比赛：{bet.get('fixture_label')}\n"
            f"玩法：{bet.get('market_title') or bet.get('market_key')}\n"
            f"选择：{bet.get('selection')}\n"
            f"金额：{bet.get('stake')} {currency}\n"
            f"赔率：{bet.get('odds')}\n"
            f"派彩：{bet.get('potential_payout')} {currency}"
        )
    if status == "void":
        return f"注单已开奖：作废退还\n\n注单号：{bet_no}\n原因：比赛取消或异常\n退还：{bet.get('stake')} {currency}"
    return (
        "📉 注单已开奖：未中奖\n\n"
        f"注单号：{bet_no}\n"
        f"比赛：{bet.get('fixture_label')}\n"
        f"选择：{bet.get('selection')}\n"
        "状态：未中奖"
    )
