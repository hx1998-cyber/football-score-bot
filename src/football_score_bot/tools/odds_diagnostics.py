from __future__ import annotations

import argparse
import asyncio
from datetime import date
from typing import Any

from football_score_bot.api_football import ApiFootballClient
from football_score_bot.config import load_settings
from football_score_bot.odds import available_market_names, normalize_fixture_odds
from football_score_bot.odds_normalizer import market_key_from_name


async def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--fixture-id", type=int)
    args = parser.parse_args()
    if not args.date and not args.fixture_id:
        parser.error("one of --date or --fixture-id is required")

    settings = load_settings()
    client = ApiFootballClient(settings.api_football_key, settings.api_football_base_url)
    try:
        if args.fixture_id:
            await _diagnose_fixture(client, args.fixture_id)
        else:
            await _diagnose_date(client, args.date)
    finally:
        await client.close()


async def _diagnose_date(client: ApiFootballClient, fixture_date: date) -> None:
    odds_items = await client.get_pre_match_odds_by_date(fixture_date)
    market_names: list[str] = []
    fixture_ids: list[int] = []
    league_names: list[str] = []
    match_winner_count = exact_score_count = asian_handicap_count = over_under_count = 0

    for item in odds_items:
        fixture = item.get("fixture") or {}
        league = item.get("league") or {}
        fixture_id = fixture.get("id")
        if fixture_id is not None:
            fixture_ids.append(int(fixture_id))
        league_name = league.get("name")
        if league_name:
            league_names.append(str(league_name))

        item_market_names = available_market_names(item)
        for name in item_market_names:
            if name not in market_names:
                market_names.append(name)
        keys = {market_key_from_name(name) for name in item_market_names}
        if normalize_fixture_odds(item):
            match_winner_count += 1
        if "correct_score" in keys:
            exact_score_count += 1
        if "asian_handicap" in keys:
            asian_handicap_count += 1
        if "over_under" in keys:
            over_under_count += 1

    print(f"odds_results: {len(odds_items)}")
    print(f"odds fixtures count: {len(set(fixture_ids))}")
    print(f"fixtures with Match Winner count: {match_winner_count}")
    print(f"fixtures with Exact Score count: {exact_score_count}")
    print(f"fixtures with Asian Handicap count: {asian_handicap_count}")
    print(f"fixtures with Goals Over/Under count: {over_under_count}")
    print(f"first 10 fixture ids: {_first_unique(fixture_ids, 10)}")
    print(f"first 10 league names: {_first_unique(league_names, 10)}")
    print(f"first 10 available market names: {_first_unique(market_names, 10)}")


async def _diagnose_fixture(client: ApiFootballClient, fixture_id: int) -> None:
    odds_items = await client.get_odds_by_fixture(fixture_id)
    raw = odds_items[0] if odds_items else {"fixture": {"id": fixture_id}, "bookmakers": []}
    print(f"fixture_id: {fixture_id}")
    print(f"odds_results: {len(odds_items)}")
    for bookmaker in raw.get("bookmakers") or []:
        bookmaker_name = bookmaker.get("name") or "-"
        print(f"bookmaker: {bookmaker_name}")
        for bet in bookmaker.get("bets") or []:
            values = bet.get("values") or []
            sample = ", ".join(_value_label(value) for value in values[:5])
            print(f"- {bet.get('name') or '-'}: {sample}")


def _value_label(value: dict[str, Any]) -> str:
    return f"{value.get('value') or '-'} {value.get('odd') or '-'}"


def _first_unique(values: list[Any], limit: int) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if value in result:
            continue
        result.append(value)
        if len(result) >= limit:
            break
    return result


if __name__ == "__main__":
    asyncio.run(_main())
