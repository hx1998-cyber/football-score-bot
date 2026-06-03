from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

logger = logging.getLogger(__name__)


async def safe_send_message(
    bot: Bot,
    chat_id: int | str | None,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
) -> bool:
    if chat_id in {None, ""}:
        logger.info("broadcast_skipped target=empty chat_id=%s", chat_id)
        return False
    try:
        await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        logger.warning("broadcast_failure target=telegram chat_id=%s", chat_id, exc_info=True)
        return False
    logger.info("broadcast_success target=telegram chat_id=%s", chat_id)
    return True


def announcement_targets(settings: Any) -> list[tuple[str, int | None]]:
    return [
        ("announcement", settings.announcement_channel_id),
        ("community_cn", settings.community_group_cn_id),
        ("community_en", settings.community_group_en_id),
    ]
