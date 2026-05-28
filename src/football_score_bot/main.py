from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from redis.asyncio import Redis

from football_score_bot.api_football import ApiFootballClient
from football_score_bot.bot_commands import setup_bot_commands
from football_score_bot.cache import RedisCache
from football_score_bot.config import load_settings
from football_score_bot.database import Database
from football_score_bot.handlers import build_router
from football_score_bot.workers.score_cache_worker import ScoreCacheWorker
from football_score_bot.workers.settlement_worker import SettlementWorker


async def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    bot = Bot(token=settings.telegram_bot_token)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    database = await Database.connect(settings.database_url)
    api_client = ApiFootballClient(
        api_key=settings.api_football_key,
        base_url=settings.api_football_base_url,
    )

    cache = RedisCache(redis)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(api_client, cache, database, settings))
    bot_info = await bot.get_me()
    worker = ScoreCacheWorker(
        api_client,
        cache,
        settings,
        bot=bot,
        database=database,
        bot_username=bot_info.username,
    )
    worker_task = asyncio.create_task(worker.run())
    settlement_worker = SettlementWorker(
        api_client,
        database,
        settings,
        bot=bot,
        bot_username=bot_info.username,
    )
    settlement_worker_task = asyncio.create_task(settlement_worker.run())

    try:
        await setup_bot_commands(bot)
        await dispatcher.start_polling(bot)
    finally:
        worker.stop()
        settlement_worker.stop()
        await worker_task
        await settlement_worker_task
        await api_client.close()
        await database.close()
        await redis.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
