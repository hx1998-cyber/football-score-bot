from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
)

logger = logging.getLogger(__name__)


PRIVATE_CHAT_COMMANDS = [
    BotCommand(command="start", description="打开主菜单"),
    BotCommand(command="live", description="实时比分"),
    BotCommand(command="today", description="可投注赛事"),
    BotCommand(command="worldcup", description="世界杯专区"),
    BotCommand(command="search", description="搜索球队或比赛"),
    BotCommand(command="language", description="语言设置"),
    BotCommand(command="wallet", description="钱包与充值"),
    BotCommand(command="bets", description="我的注单"),
    BotCommand(command="admin", description="管理员控制台"),
    BotCommand(command="referrals", description="邀请返佣"),
    BotCommand(command="settings", description="设置"),
    BotCommand(command="help", description="帮助"),
]


GROUP_CHAT_COMMANDS = [
    BotCommand(command="live", description="群组实时比分"),
    BotCommand(command="today", description="可投注赛事"),
    BotCommand(command="match", description="搜索比赛"),
    BotCommand(command="subscribe", description="订阅本群重点比分播报"),
    BotCommand(command="unsubscribe", description="取消本群播报"),
    BotCommand(command="help", description="帮助"),
]


async def setup_bot_commands(bot: Bot) -> None:
    """Register Telegram command menus for private chats and groups."""
    try:
        await bot.set_my_commands(
            PRIVATE_CHAT_COMMANDS,
            scope=BotCommandScopeAllPrivateChats(),
        )
        await bot.set_my_commands(
            GROUP_CHAT_COMMANDS,
            scope=BotCommandScopeAllGroupChats(),
        )
    except Exception:
        logger.warning(
            "Failed to register scoped Telegram bot commands; falling back to global commands.",
            exc_info=True,
        )
        await bot.set_my_commands(PRIVATE_CHAT_COMMANDS)
