from __future__ import annotations

import argparse
import asyncio

from football_score_bot.api_football import ApiFootballClient
from football_score_bot.config import load_settings
from football_score_bot.odds_normalizer import normalize_fixture_odds


async def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-id", type=int, required=True)
    args = parser.parse_args()

    settings = load_settings()
    client = ApiFootballClient(settings.api_football_key, settings.api_football_base_url)
    try:
        raw_items = await client.get_odds_by_fixture(args.fixture_id)
        raw = raw_items[0] if raw_items else {"fixture": {"id": args.fixture_id}, "bookmakers": []}
        normalized = normalize_fixture_odds(raw)
        market_keys = set(normalized.markets)

        print(f"fixture_id: {args.fixture_id}")
        print(f"bookmaker count: {len(raw.get('bookmakers') or [])}")
        print("available bet markets:")
        for market in normalized.markets.values():
            print(f"- {market.key}: {market.title} ({len(market.outcomes)} outcomes)")
        print(f"Match Winner exists: {'match_winner' in market_keys}")
        print(f"Correct Score exists: {'correct_score' in market_keys}")
        print(f"Over/Under exists: {'over_under' in market_keys}")
        print(f"Handicap exists: {'handicap' in market_keys}")
        print(f"HT/FT exists: {'ht_ft' in market_keys}")
        print("sample values:")
        for market in normalized.markets.values():
            sample = ", ".join(f"{outcome.label} {outcome.odds}" for outcome in market.outcomes[:5])
            print(f"- {market.title}: {sample}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(_main())
