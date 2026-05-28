from __future__ import annotations

import secrets
import string
from datetime import datetime


GMPAY_ORDER_ID_MAX_LENGTH = 32
_RANDOM_ALPHABET = string.ascii_uppercase + string.digits


def generate_gmpay_order_id(timestamp: int | None = None) -> str:
    unix_timestamp = int(timestamp if timestamp is not None else datetime.now().timestamp())
    random_suffix = "".join(secrets.choice(_RANDOM_ALPHABET) for _ in range(6))
    return f"D{unix_timestamp}{random_suffix}"


def is_valid_gmpay_order_id(order_id: str) -> bool:
    return (
        0 < len(order_id) <= GMPAY_ORDER_ID_MAX_LENGTH
        and all(char.isalnum() or char == "_" for char in order_id)
    )
