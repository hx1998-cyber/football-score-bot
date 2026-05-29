from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from football_score_bot.config import Settings
from football_score_bot.database import Database
from football_score_bot.services.wallet_service import WalletService

logger = logging.getLogger(__name__)


class PayoutUnlockWorker:
    def __init__(self, database: Database, settings: Settings, *, bot: Bot | None = None) -> None:
        self._database = database
        self._settings = settings
        self._bot = bot
        self._stopped = asyncio.Event()
        self._wallet_service = WalletService(
            database,
            currency=settings.wallet_currency,
            referral_deposit_commission_rate=settings.referral_deposit_commission_rate,
            referral_agent_enabled=settings.referral_agent_enabled,
            payout_freeze_enabled=settings.payout_freeze_enabled,
            payout_freeze_hours=settings.payout_freeze_hours,
        )

    async def run(self) -> None:
        if not self._settings.payout_freeze_enabled:
            return
        while not self._stopped.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.warning("payout unlock worker iteration failed", exc_info=True)
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stopped.set()

    async def run_once(self) -> None:
        rows = await self._database.pool.fetch(
            """
            SELECT * FROM payout_freezes
            WHERE status IN ('frozen', 'extended') AND unlock_at <= NOW()
            ORDER BY unlock_at, id
            LIMIT 100
            """
        )
        for row in rows:
            freeze_id = int(row["id"])
            try:
                unlocked = await self._wallet_service.unlock_payout_freeze(freeze_id, reason="auto unlock")
            except ValueError:
                logger.warning("payout unlock failed freeze_id=%s", freeze_id, exc_info=True)
                continue
            if unlocked and self._bot:
                await self._notify_user(int(unlocked["user_id"]), str(unlocked["amount"]))

    async def _notify_user(self, user_id: int, amount: str) -> None:
        try:
            await self._bot.send_message(
                user_id,
                f"派彩已解冻，可用余额增加 {amount} {self._settings.wallet_currency}。",
            )
        except Exception:
            logger.info("failed to notify payout unfreeze user_id=%s", user_id, exc_info=True)
