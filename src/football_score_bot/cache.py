from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from redis.asyncio import Redis


class RedisCache:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get_or_set(
        self,
        key: str,
        ttl_seconds: int,
        loader: Callable[[], Awaitable[list[dict[str, Any]]]],
    ) -> list[dict[str, Any]]:
        cached = await self._redis.get(key)
        if cached:
            return json.loads(cached)

        value = await loader()
        await self._redis.set(key, json.dumps(value), ex=ttl_seconds)
        return value

    async def get_json(self, key: str, default: Any = None) -> Any:
        cached = await self._redis.get(key)
        if not cached:
            return default
        return json.loads(cached)

    async def set_json(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        await self._redis.set(key, json.dumps(value), ex=ttl_seconds)

    async def get_text(self, key: str) -> str | None:
        return await self._redis.get(key)

    async def set_text(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        await self._redis.set(key, value, ex=ttl_seconds)

    async def acquire_lock(self, key: str, ttl_seconds: int) -> bool:
        return bool(await self._redis.set(key, "1", ex=ttl_seconds, nx=True))

    async def release_lock(self, key: str) -> None:
        await self._redis.delete(key)
