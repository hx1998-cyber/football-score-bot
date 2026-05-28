from __future__ import annotations

from football_score_bot.payments.order_ids import GMPAY_ORDER_ID_MAX_LENGTH, generate_gmpay_order_id, is_valid_gmpay_order_id


def main() -> None:
    order_ids = [generate_gmpay_order_id() for _ in range(1000)]
    invalid = [order_id for order_id in order_ids if not is_valid_gmpay_order_id(order_id)]
    if invalid:
        raise SystemExit(f"invalid GMPay order_id generated: {invalid[0]}")
    if len(set(order_ids)) != len(order_ids):
        raise SystemExit("duplicate GMPay order_id generated")
    max_length = max(len(order_id) for order_id in order_ids)
    print(f"generated={len(order_ids)} max_length={max_length} limit={GMPAY_ORDER_ID_MAX_LENGTH}")


if __name__ == "__main__":
    main()
