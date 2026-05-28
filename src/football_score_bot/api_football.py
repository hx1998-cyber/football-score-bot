from __future__ import annotations

from datetime import date
from typing import Any

import httpx


class ApiFootballClient:
    def __init__(self, api_key: str, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"x-apisports-key": api_key},
            timeout=httpx.Timeout(connect=5, read=30, write=5, pool=5),
        )

    async def get_live_fixtures(self) -> list[dict[str, Any]]:
        data = await self._get("/fixtures", params={"live": "all"})
        return data.get("response", [])

    async def get_fixtures_by_date(self, fixture_date: date) -> list[dict[str, Any]]:
        data = await self._get("/fixtures", params={"date": fixture_date.isoformat()})
        return data.get("response", [])

    async def search_leagues(self, keyword: str) -> list[dict[str, Any]]:
        data = await self._get("/leagues", params={"search": keyword})
        return data.get("response", [])

    async def search_teams(self, keyword: str) -> list[dict[str, Any]]:
        data = await self._get("/teams", params={"search": keyword})
        return data.get("response", [])

    async def get_fixture_events(self, fixture_id: int) -> list[dict[str, Any]]:
        data = await self._get("/fixtures/events", params={"fixture": fixture_id})
        return data.get("response", [])

    async def get_fixture_detail(self, fixture_id: int) -> dict[str, Any] | None:
        data = await self._get("/fixtures", params={"id": fixture_id})
        response = data.get("response", [])
        return response[0] if response else None

    async def get_live_odds(self) -> list[dict[str, Any]]:
        data = await self._get("/odds/live", params={})
        return data.get("response", [])

    async def get_live_odds_by_fixture(self, fixture_id: int) -> list[dict[str, Any]]:
        try:
            data = await self._get("/odds/live", params={"fixture": fixture_id})
            response = data.get("response", [])
            filtered = [
                item
                for item in response
                if str((item.get("fixture") or {}).get("id") or item.get("fixture_id")) == str(fixture_id)
            ]
            return filtered or response
        except httpx.HTTPStatusError:
            live_odds = await self.get_live_odds()
            return [
                item
                for item in live_odds
                if str((item.get("fixture") or {}).get("id") or item.get("fixture_id")) == str(fixture_id)
            ]

    async def get_pre_match_odds_by_date(self, fixture_date: date) -> list[dict[str, Any]]:
        data = await self._get("/odds", params={"date": fixture_date.isoformat()})
        return data.get("response", [])

    async def get_odds_by_fixture(self, fixture_id: int) -> list[dict[str, Any]]:
        data = await self._get("/odds", params={"fixture": fixture_id})
        return data.get("response", [])

    async def get_odds_bets(self) -> list[dict[str, Any]]:
        data = await self._get("/odds/bets", params={})
        return data.get("response", [])

    async def get_odds_bookmakers(self) -> list[dict[str, Any]]:
        data = await self._get("/odds/bookmakers", params={})
        return data.get("response", [])

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()
