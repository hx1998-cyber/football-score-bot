from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation
from typing import Any

import uvicorn
from aiogram import Bot
from fastapi import FastAPI, HTTPException, Request, Response

from football_score_bot.config import Settings, load_settings
from football_score_bot.database import Database
from football_score_bot.payments.gmpay import GMPayClient
from football_score_bot.services.wallet_service import WalletService


logger = logging.getLogger(__name__)
SUCCESS_STATUSES = {"success", "paid", "2", "trade_success", "finished", "completed"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    database = await Database.connect(settings.database_url)
    bot = Bot(token=settings.telegram_bot_token)
    app.state.settings = settings
    app.state.database = database
    app.state.bot = bot
    app.state.gmpay = _build_gmpay_client(settings)
    app.state.wallets = WalletService(
        database,
        currency=settings.wallet_currency,
        referral_deposit_commission_rate=settings.referral_deposit_commission_rate,
        referral_agent_enabled=settings.referral_agent_enabled,
    )
    try:
        yield
    finally:
        await app.state.gmpay.close()
        await bot.session.close()
        await database.close()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhooks/gmpay")
async def gmpay_webhook(request: Request) -> Response:
    payload = await _read_payload(request)
    settings: Settings = request.app.state.settings
    gmpay: GMPayClient = request.app.state.gmpay
    database: Database = request.app.state.database
    wallets: WalletService = request.app.state.wallets
    bot: Bot = request.app.state.bot

    signature_valid = bool(payload and gmpay.verify_signature(payload))
    normalized = _normalize_callback(payload)
    order_id = normalized["order_id"]
    order = await database.get_deposit_order(order_id) if order_id else None
    status_before = str(order.get("status")) if order else None
    if not payload or not signature_valid:
        logger.warning(
            "gmpay callback received order_id=%s trade_id=%s status=%s actual_amount=%s signature_valid=%s matched_order=%s deposit_status_before=%s deposit_status_after=%s",
            order_id,
            normalized["trade_id"],
            normalized["status"],
            normalized["actual_amount"],
            signature_valid,
            bool(order),
            status_before,
            status_before,
        )
        raise HTTPException(status_code=401, detail="invalid signature")

    if not order_id:
        raise HTTPException(status_code=400, detail="missing order_id")
    if not order:
        logger.warning(
            "gmpay callback order not found order_id=%s trade_id=%s status=%s actual_amount=%s signature_valid=%s matched_order=false deposit_status_before=%s deposit_status_after=%s",
            order_id,
            normalized["trade_id"],
            normalized["status"],
            normalized["actual_amount"],
            signature_valid,
            None,
            None,
        )
        return Response("ok", media_type="text/plain")

    if order.get("status") == "paid":
        logger.info(
            "duplicate callback ignored order_id=%s trade_id=%s status=%s actual_amount=%s signature_valid=%s matched_order=true deposit_status_before=%s deposit_status_after=%s",
            order_id,
            normalized["trade_id"],
            normalized["status"],
            normalized["actual_amount"],
            signature_valid,
            status_before,
            order.get("status"),
        )
        return Response("ok", media_type="text/plain")
    if order.get("status") == "manual_review":
        logger.info(
            "duplicate manual review callback ignored order_id=%s trade_id=%s status=%s actual_amount=%s signature_valid=%s matched_order=true deposit_status_before=%s deposit_status_after=%s",
            order_id,
            normalized["trade_id"],
            normalized["status"],
            normalized["actual_amount"],
            signature_valid,
            status_before,
            order.get("status"),
        )
        return Response("ok", media_type="text/plain")
    if not _is_success_status(normalized["status"]):
        logger.info(
            "gmpay callback ignored non-paid order_id=%s trade_id=%s status=%s actual_amount=%s signature_valid=%s matched_order=true deposit_status_before=%s deposit_status_after=%s",
            order_id,
            normalized["trade_id"],
            normalized["status"],
            normalized["actual_amount"],
            signature_valid,
            status_before,
            status_before,
        )
        return Response("ok", media_type="text/plain")

    if normalized["trade_id"] and order.get("trade_id") and normalized["trade_id"] != str(order["trade_id"]):
        logger.warning("gmpay webhook trade_id mismatch order_id=%s", order_id)
        raise HTTPException(status_code=400, detail="trade_id mismatch")
    callback_payload = {
        **payload,
        "trade_id": normalized["trade_id"],
        "actual_amount": normalized["actual_amount"],
        "chain_tx_id": normalized["chain_tx_id"],
    }
    actual_amount = _parse_decimal(normalized["actual_amount"])
    requested_amount = _parse_decimal(order.get("amount_requested"))
    if actual_amount is None:
        note = "GMPay success callback missing actual_amount"
        updated_order = await database.mark_deposit_manual_review(
            order_id,
            note=note,
            callback_payload=callback_payload,
            trade_id=normalized["trade_id"],
            chain_tx_id=normalized["chain_tx_id"],
            error_message=note,
        )
        await _notify_deposit_manual_review(bot, settings, order, updated_order or order, note)
        return Response("ok", media_type="text/plain")
    if requested_amount is None:
        note = "Deposit order amount_requested is invalid"
        updated_order = await database.mark_deposit_manual_review(
            order_id,
            note=note,
            callback_payload=callback_payload,
            actual_amount=actual_amount,
            trade_id=normalized["trade_id"],
            chain_tx_id=normalized["chain_tx_id"],
            error_message=note,
        )
        await _notify_deposit_manual_review(bot, settings, order, updated_order or order, note)
        return Response("ok", media_type="text/plain")
    amount_diff = abs(actual_amount - requested_amount)
    if amount_diff > settings.payment_amount_tolerance_usdt:
        note = (
            f"Payment amount mismatch: requested={requested_amount} actual={actual_amount} "
            f"tolerance={settings.payment_amount_tolerance_usdt}"
        )
        updated_order = await database.mark_deposit_manual_review(
            order_id,
            note=note,
            callback_payload=callback_payload,
            actual_amount=actual_amount,
            trade_id=normalized["trade_id"],
            chain_tx_id=normalized["chain_tx_id"],
            error_message=note,
        )
        await _notify_deposit_manual_review(bot, settings, order, updated_order or order, note)
        logger.warning("gmpay callback moved to manual_review order_id=%s %s", order_id, note)
        return Response("ok", media_type="text/plain")

    paid = await wallets.credit_deposit(int(order["user_id"]), order, callback_payload)
    updated_order = await database.get_deposit_order(order_id)
    status_after = str(updated_order.get("status")) if updated_order else status_before
    logger.info(
        "gmpay callback processed order_id=%s trade_id=%s status=%s actual_amount=%s signature_valid=%s matched_order=true deposit_status_before=%s deposit_status_after=%s credited=%s",
        order_id,
        normalized["trade_id"],
        normalized["status"],
        normalized["actual_amount"],
        signature_valid,
        status_before,
        status_after,
        paid,
    )
    if paid:
        try:
            await bot.send_message(
                int(order["user_id"]),
                f"充值到账：{_amount_text(callback_payload.get('actual_amount'))} {settings.wallet_currency}",
            )
        except Exception:
            logger.info("failed to notify deposit user_id=%s order_id=%s", order["user_id"], order_id, exc_info=True)
    return Response("ok", media_type="text/plain")


async def _read_payload(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    form = await request.form()
    return dict(form)


def _normalize_callback(payload: dict[str, Any]) -> dict[str, str | None]:
    return {
        "order_id": _optional_text(payload.get("order_id") or payload.get("merchant_order_id")),
        "trade_id": _optional_text(payload.get("trade_id") or payload.get("transaction_id")),
        "status": _optional_text(payload.get("status") or payload.get("trade_status") or payload.get("state")),
        "actual_amount": _optional_text(payload.get("actual_amount") or payload.get("amount")),
        "chain_tx_id": _optional_text(
            payload.get("chain_tx_id")
            or payload.get("block_transaction_id")
            or payload.get("txid")
            or payload.get("tx_id")
            or payload.get("hash")
        ),
    }


def _is_success_status(status: str | None) -> bool:
    return bool(status and status.lower() in SUCCESS_STATUSES)


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _amount_text(value: Any) -> str:
    return str(value or "0").rstrip("0").rstrip(".") if "." in str(value or "") else str(value or "0")


async def _notify_deposit_manual_review(
    bot: Bot,
    settings: Settings,
    original_order: dict[str, Any],
    order: dict[str, Any],
    note: str,
) -> None:
    order_id = str(order.get("order_id") or original_order.get("order_id"))
    user_id = int(order.get("user_id") or original_order["user_id"])
    try:
        await bot.send_message(
            user_id,
            "充值订单金额或状态异常，已进入人工核查。\n"
            f"订单号：{order_id}\n"
            "请准备 txid 联系管理员。",
        )
    except Exception:
        logger.info("failed to notify manual review user_id=%s order_id=%s", user_id, order_id, exc_info=True)
    admin_text = (
        "充值订单进入人工核查\n"
        f"order_id={order_id}\n"
        f"user_id={user_id}\n"
        f"amount_requested={order.get('amount_requested') or original_order.get('amount_requested')}\n"
        f"actual_amount={order.get('actual_amount') or '-'}\n"
        f"note={note}"
    )
    for admin_id in settings.super_admin_user_ids | settings.admin_user_ids:
        try:
            await bot.send_message(admin_id, admin_text)
        except Exception:
            logger.info("failed to notify deposit admin_id=%s order_id=%s", admin_id, order_id, exc_info=True)


def _build_gmpay_client(settings: Settings) -> GMPayClient:
    return GMPayClient(
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


def main() -> None:
    uvicorn.run("football_score_bot.api_server:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
