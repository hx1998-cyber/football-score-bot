from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx


@dataclass(frozen=True)
class GMPayTransaction:
    order_id: str
    trade_id: str | None
    amount: Decimal
    actual_amount: Decimal
    payment_url: str
    token: str
    network: str
    expires_at: datetime
    raw_json: dict[str, Any]


def sign_payload(params: dict[str, Any], secret_key: str, *, sign_type: str = "md5") -> str:
    base = build_sign_base(params, secret_key=secret_key)
    if sign_type.lower() != "md5":
        raise ValueError(f"Unsupported GMPay sign type: {sign_type}")
    return hashlib.md5(base.encode("utf-8")).hexdigest()


def build_sign_base(params: dict[str, Any], *, secret_key: str) -> str:
    parts: list[str] = []
    for key in sorted(params):
        if key == "signature":
            continue
        value = params[key]
        if value is None or value == "":
            continue
        parts.append(f"{key}={value}")
    return f"{'&'.join(parts)}{secret_key}"


class GMPayClient:
    def __init__(
        self,
        *,
        pid: str,
        base_url: str,
        create_order_path: str,
        secret: str,
        sign_type: str = "md5",
        default_currency: str = "cny",
        default_token: str = "usdt",
        default_network: str = "tron",
        default_payment_type: str | None = None,
        order_expire_minutes: int = 30,
    ) -> None:
        self._pid = pid
        self._base_url = base_url.rstrip("/")
        self._create_order_path = create_order_path
        self._secret = secret
        self._sign_type = sign_type
        self._default_currency = default_currency
        self._default_token = default_token
        self._default_network = default_network
        self._default_payment_type = default_payment_type
        self._order_expire_minutes = order_expire_minutes
        self._client = httpx.AsyncClient(timeout=20)

    async def close(self) -> None:
        await self._client.aclose()

    def sign_payload(self, params: dict[str, Any]) -> str:
        return sign_payload(params, self._secret, sign_type=self._sign_type)

    def verify_signature(self, payload: dict[str, Any]) -> bool:
        supplied = str(payload.get("signature") or "")
        if not supplied or not self._secret:
            return False
        expected = self.sign_payload(payload)
        return hmac.compare_digest(supplied.lower(), expected.lower())

    async def create_transaction(
        self,
        *,
        order_id: str,
        amount: Decimal,
        user_id: int,
        notify_url: str,
        redirect_url: str | None = None,
    ) -> GMPayTransaction:
        if not self._pid or not self._base_url or not self._secret:
            raise RuntimeError("GMPAY_PID, GMPAY_BASE_URL and GMPAY_SECRET are required")
        payload: dict[str, Any] = {
            "pid": self._pid,
            "order_id": order_id,
            "currency": self._default_currency,
            "token": self._default_token,
            "network": self._default_network,
            "amount": _json_amount(amount),
            "notify_url": notify_url,
        }
        if redirect_url:
            payload["redirect_url"] = redirect_url
        if self._default_payment_type:
            payload["payment_type"] = self._default_payment_type
        payload["signature"] = self.sign_payload(payload)
        response = await self._client.post(
            f"{self._base_url}{self._create_order_path}",
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        data = _response_data(body)
        if not data:
            raise RuntimeError(f"GMPay create transaction failed: {body.get('message') or body.get('msg') or 'unknown error'}")
        return GMPayTransaction(
            order_id=str(data.get("order_id") or order_id),
            trade_id=_optional_text(data.get("trade_id")),
            amount=Decimal(str(data.get("amount") or amount)),
            actual_amount=Decimal(str(data.get("actual_amount") or data.get("amount") or amount)),
            payment_url=str(data.get("payment_url") or data.get("pay_url") or data.get("checkout_url") or ""),
            token=str(data.get("token") or self._default_token),
            network=str(data.get("network") or self._default_network),
            expires_at=_parse_expires_at(data) or datetime.now(timezone.utc) + timedelta(minutes=self._order_expire_minutes),
            raw_json=body,
        )

    def unsigned_create_payload(self, *, order_id: str, amount: Decimal, notify_url: str, redirect_url: str | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "pid": self._pid,
            "order_id": order_id,
            "currency": self._default_currency,
            "token": self._default_token,
            "network": self._default_network,
            "amount": _json_amount(amount),
            "notify_url": notify_url,
        }
        if redirect_url:
            payload["redirect_url"] = redirect_url
        if self._default_payment_type:
            payload["payment_type"] = self._default_payment_type
        return payload


def _response_data(body: dict[str, Any]) -> dict[str, Any]:
    data = body.get("data")
    if isinstance(data, dict):
        return data
    if any(key in body for key in ("payment_url", "pay_url", "trade_id")):
        return body
    return {}


def _parse_expires_at(data: dict[str, Any]) -> datetime | None:
    value = data.get("expires_at") or data.get("expiration_time") or data.get("expire_time")
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(int(value), timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.fromtimestamp(int(value), timezone.utc)
            except ValueError:
                return None
    return None


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _json_amount(value: Decimal) -> int | float:
    normalized = value.normalize()
    if normalized == normalized.to_integral_value():
        return int(normalized)
    return float(value)
