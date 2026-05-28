from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse

import asyncpg
import httpx
from dotenv import load_dotenv
from redis.asyncio import Redis


async def main() -> None:
    load_dotenv()
    database_url = os.getenv("DATABASE_URL", "postgresql://football:football_password@localhost:5432/football_score_bot")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    app_public_base_url = os.getenv("APP_PUBLIC_BASE_URL", "")
    checks: list[tuple[str, bool]] = [
        ("TELEGRAM_BOT_TOKEN present", bool(os.getenv("TELEGRAM_BOT_TOKEN"))),
        ("API_FOOTBALL_KEY present", bool(os.getenv("API_FOOTBALL_KEY"))),
        ("GMPAY_BASE_URL present", bool(os.getenv("GMPAY_BASE_URL"))),
        ("GMPAY_PID present", bool(os.getenv("GMPAY_PID"))),
        ("GMPAY_SECRET present", bool(os.getenv("GMPAY_SECRET"))),
        ("GMPAY_NOTIFY_URL is https", _valid_notify_url(os.getenv("GMPAY_NOTIFY_URL", ""))),
        ("super_admin configured", bool(os.getenv("SUPER_ADMIN_USER_IDS", "").strip())),
    ]
    checks.append(("DATABASE_URL works", await _check_database(database_url)))
    checks.append(("REDIS_URL works", await _check_redis(redis_url)))
    checks.append(("api /health works", await _check_health(app_public_base_url)))
    for name, ok in checks:
        print(f"{name}: {'ok' if ok else 'missing'}")


def _valid_notify_url(value: str) -> bool:
    parsed = urlparse(value or "")
    if parsed.scheme != "https":
        return False
    lowered = value.lower()
    return "placeholder" not in lowered and "example" not in lowered and bool(parsed.netloc)


async def _check_database(database_url: str) -> bool:
    try:
        conn = await asyncpg.connect(database_url)
        try:
            await conn.execute("SELECT 1")
        finally:
            await conn.close()
        return True
    except Exception:
        return False


async def _check_redis(redis_url: str) -> bool:
    try:
        redis = Redis.from_url(redis_url, decode_responses=True)
        try:
            return bool(await redis.ping())
        finally:
            await redis.aclose()
    except Exception:
        return False


async def _check_health(base_url: str) -> bool:
    candidates = [base_url.rstrip()] if base_url else []
    candidates.extend(["http://localhost:8000", "http://api:8000"])
    async with httpx.AsyncClient(timeout=5) as client:
        for candidate in candidates:
            if not candidate:
                continue
            try:
                response = await client.get(candidate.rstrip("/") + "/health")
            except Exception:
                continue
            if response.status_code == 200:
                return True
    return False


if __name__ == "__main__":
    asyncio.run(main())
