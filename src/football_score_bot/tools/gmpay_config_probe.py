from __future__ import annotations

import asyncio
import json
from typing import Any

from football_score_bot.config import load_settings
from football_score_bot.payments.gmpay import GMPayClient


async def main() -> None:
    settings = load_settings()
    client = GMPayClient(
        pid=settings.gmpay_pid,
        base_url=settings.gmpay_base_url,
        create_order_path=settings.gmpay_create_order_path,
        secret=settings.gmpay_secret,
        sign_type=settings.gmpay_sign_type,
        default_currency=settings.gmpay_default_currency,
        default_token=settings.gmpay_default_token,
        default_network=settings.gmpay_default_network,
        default_payment_type=settings.gmpay_default_payment_type,
        order_expire_minutes=settings.gmpay_order_expire_minutes,
    )
    try:
        config = await client.get_gmpay_config()
        print(json.dumps(_public_config_view(config), ensure_ascii=False, indent=2, default=str))
    finally:
        await client.close()


def _public_config_view(config: dict[str, Any]) -> dict[str, Any]:
    data = config.get("data") if isinstance(config.get("data"), dict) else config
    return {
        "supported_assets": data.get("supported_assets") or data.get("assets") or data.get("supportedAssets") or [],
        "site": data.get("site") or data.get("site_info") or data.get("siteInfo") or {},
    }


if __name__ == "__main__":
    asyncio.run(main())
