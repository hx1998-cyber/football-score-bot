from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from decimal import Decimal

from football_score_bot.config import load_settings
from football_score_bot.payments.gmpay import GMPayClient


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--amount", default="10")
    args = parser.parse_args()
    settings = load_settings()
    amount = Decimal(args.amount)
    order_id = f"dep_test_{int(time.time())}_{uuid.uuid4().hex[:8]}"
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
        unsigned = client.unsigned_create_payload(
            order_id=order_id,
            amount=amount,
            notify_url=settings.gmpay_notify_url,
            redirect_url=settings.gmpay_redirect_url,
        )
        print("order_id:", order_id)
        print("request payload without secret:")
        print(json.dumps({**unsigned, "signature": client.sign_payload(unsigned)}, ensure_ascii=False, indent=2))
        tx = await client.create_transaction(
            order_id=order_id,
            amount=amount,
            user_id=0,
            notify_url=settings.gmpay_notify_url,
            redirect_url=settings.gmpay_redirect_url,
        )
        print("payment_url:", tx.payment_url)
        print("trade_id:", tx.trade_id)
        print("actual_amount:", tx.actual_amount)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
