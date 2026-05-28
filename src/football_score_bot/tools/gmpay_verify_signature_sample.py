from __future__ import annotations

import json

from football_score_bot.config import load_settings
from football_score_bot.payments.gmpay import sign_payload


def main() -> None:
    settings = load_settings()
    sample = {
        "pid": settings.gmpay_pid or "1000",
        "order_id": "dep_sample_1",
        "trade_id": "trade_sample_1",
        "status": "success",
        "actual_amount": "10.00",
        "chain_tx_id": "tx_sample_1",
    }
    signature = sign_payload(sample, settings.gmpay_secret, sign_type=settings.gmpay_sign_type)
    signed = {**sample, "signature": signature}
    print(json.dumps(signed, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
