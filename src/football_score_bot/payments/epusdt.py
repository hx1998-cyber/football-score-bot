from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx


@dataclass(frozen=True)
class EpusdtTransaction:
    trade_id: str
    order_id: str
    amount: Decimal
    actual_amount: Decimal
    token: str
    expiration_time: int
    payment_url: str
    raw_response: dict[str, Any]


def epusdt_signature(payload: dict[str, Any], secret: str) -> str:
    parts: list[str] = []
    for key in sorted(payload):
        if key == "signature":
            continue
        value = payload[key]
        if value is None or value == "":
            continue
        parts.append(f"{key}={value}")
    return hashlib.md5(("&".join(parts) + secret).encode("utf-8")).hexdigest()


class EpusdtClient:
    def __init__(self, base_url: str, api_secret: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_secret = api_secret
        self._client = httpx.AsyncClient(timeout=20)

    async def close(self) -> None:
        await self._client.aclose()

    async def create_transaction(
        self,
        order_id: str,
        amount: Decimal,
        notify_url: str,
        redirect_url: str | None = None,
    ) -> EpusdtTransaction:
        if not self._base_url or not self._api_secret:
            raise RuntimeError("EPUSDT_BASE_URL and EPUSDT_API_SECRET are required")
        payload: dict[str, Any] = {
            "order_id": order_id,
            "amount": f"{amount:.2f}",
            "notify_url": notify_url,
        }
        if redirect_url:
            payload["redirect_url"] = redirect_url
        payload["signature"] = epusdt_signature(payload, self._api_secret)
        response = await self._client.post(
            f"{self._base_url}/api/v1/order/create-transaction",
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        if int(body.get("status_code") or 0) != 200:
            raise RuntimeError(f"EPUSDT create transaction failed: {body.get('message') or 'unknown error'}")
        data = body.get("data") or {}
        return EpusdtTransaction(
            trade_id=str(data["trade_id"]),
            order_id=str(data["order_id"]),
            amount=Decimal(str(data["amount"])),
            actual_amount=Decimal(str(data["actual_amount"])),
            token=str(data["token"]),
            expiration_time=int(data["expiration_time"]),
            payment_url=str(data["payment_url"]),
            raw_response=body,
        )

    def verify_signature(self, payload: dict[str, Any]) -> bool:
        supplied = str(payload.get("signature") or "")
        if not supplied or not self._api_secret:
            return False
        expected = epusdt_signature(payload, self._api_secret)
        return hmac.compare_digest(supplied.lower(), expected.lower())
