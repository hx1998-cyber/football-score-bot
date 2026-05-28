from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from football_score_bot.database import Database


class WalletService:
    def __init__(
        self,
        database: Database,
        *,
        currency: str = "USDT",
        referral_deposit_commission_rate: Decimal = Decimal("0.00"),
        referral_agent_enabled: bool = True,
    ) -> None:
        self._database = database
        self._currency = currency
        self._commission_rate = referral_deposit_commission_rate
        self._referral_agent_enabled = referral_agent_enabled

    async def get_or_create_wallet(self, user_id: int) -> dict:
        async with self._database.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO wallets (telegram_user_id, user_id, currency, updated_at)
                    VALUES ($1, $1, $2, NOW())
                    ON CONFLICT (user_id, currency) DO UPDATE SET updated_at = wallets.updated_at
                    RETURNING *
                    """,
                    user_id,
                    self._currency,
                )
                return dict(row)

    async def get_balance(self, user_id: int) -> dict:
        return await self.get_or_create_wallet(user_id)

    async def credit_deposit(self, user_id: int, deposit_order: dict, callback_payload: dict[str, Any] | None = None) -> bool:
        order_id = str(deposit_order["order_id"])
        trade_id = _optional_text((callback_payload or {}).get("trade_id") or deposit_order.get("trade_id"))
        chain_tx_id = _optional_text(
            (callback_payload or {}).get("chain_tx_id")
            or (callback_payload or {}).get("block_transaction_id")
            or (callback_payload or {}).get("txid")
            or deposit_order.get("chain_tx_id")
            or deposit_order.get("block_transaction_id")
        )
        actual_amount = Decimal(
            str((callback_payload or {}).get("actual_amount") or deposit_order.get("actual_amount") or deposit_order["amount_requested"])
        )
        async with self._database.pool.acquire() as conn:
            async with conn.transaction():
                order = await conn.fetchrow(
                    "SELECT * FROM deposit_orders WHERE order_id = $1 FOR UPDATE",
                    order_id,
                )
                if not order:
                    return False
                if order["status"] == "paid":
                    return False
                if trade_id:
                    duplicate_trade = await conn.fetchval(
                        """
                        SELECT order_id FROM deposit_orders
                        WHERE trade_id = $1 AND status = 'paid' AND order_id <> $2
                        """,
                        trade_id,
                        order_id,
                    )
                    if duplicate_trade:
                        return False
                if chain_tx_id:
                    duplicate = await conn.fetchval(
                        """
                        SELECT order_id FROM deposit_orders
                        WHERE (chain_tx_id = $1 OR block_transaction_id = $1) AND status = 'paid' AND order_id <> $2
                        """,
                        chain_tx_id,
                        order_id,
                    )
                    if duplicate:
                        return False
                wallet = await conn.fetchrow(
                    """
                    INSERT INTO wallets (telegram_user_id, user_id, currency, updated_at)
                    VALUES ($1, $1, $2, NOW())
                    ON CONFLICT (user_id, currency) DO UPDATE SET updated_at = wallets.updated_at
                    RETURNING *
                    """,
                    user_id,
                    self._currency,
                )
                balance_before = Decimal(str(wallet["balance"]))
                balance_after = balance_before + actual_amount
                ledger_id = await conn.fetchval(
                    """
                    INSERT INTO wallet_ledger (
                        user_id, currency, type, amount, balance_before, balance_after,
                        ref_type, ref_id, description
                    )
                    VALUES ($1, $2, 'deposit', $3, $4, $5, 'deposit_order', $6, 'GMPay deposit')
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """,
                    user_id,
                    self._currency,
                    actual_amount,
                    balance_before,
                    balance_after,
                    order_id,
                )
                if not ledger_id:
                    return False
                await conn.execute(
                    """
                    UPDATE wallets
                    SET balance = $3,
                        total_deposit = total_deposit + $4,
                        updated_at = NOW()
                    WHERE user_id = $1 AND currency = $2
                    """,
                    user_id,
                    self._currency,
                    balance_after,
                    actual_amount,
                )
                await conn.execute(
                    """
                    UPDATE deposit_orders
                    SET status = 'paid',
                        actual_amount = COALESCE($2, actual_amount),
                        trade_id = COALESCE($3, trade_id),
                        chain_tx_id = COALESCE($4, chain_tx_id),
                        block_transaction_id = COALESCE($4, block_transaction_id),
                        raw_callback_json = $5::jsonb,
                        paid_at = COALESCE(paid_at, NOW()),
                        updated_at = NOW()
                    WHERE order_id = $1
                    """,
                    order_id,
                    actual_amount,
                    trade_id,
                    chain_tx_id,
                    json.dumps(callback_payload or {}),
                )
                if self._referral_agent_enabled and self._commission_rate > 0:
                    parent_user_id = await conn.fetchval(
                        "SELECT parent_user_id FROM referral_relations WHERE user_id = $1",
                        user_id,
                    )
                    if parent_user_id and int(parent_user_id) != user_id:
                        commission = (actual_amount * self._commission_rate).quantize(Decimal("0.000001"))
                        if commission > 0:
                            await conn.execute(
                                """
                                INSERT INTO commission_records (
                                    user_id, source_user_id, source_type, source_ref_id,
                                    amount, rate, status
                                )
                                VALUES ($1, $2, 'deposit', $3, $4, $5, 'pending')
                                ON CONFLICT DO NOTHING
                                """,
                                int(parent_user_id),
                                user_id,
                                order_id,
                                commission,
                                self._commission_rate,
                            )
                return True

    async def add_ledger_entry(
        self,
        user_id: int,
        ledger_type: str,
        amount: Decimal,
        *,
        ref_type: str | None = None,
        ref_id: str | None = None,
        description: str | None = None,
    ) -> dict:
        async with self._database.pool.acquire() as conn:
            async with conn.transaction():
                wallet = await conn.fetchrow(
                    """
                    INSERT INTO wallets (telegram_user_id, user_id, currency, updated_at)
                    VALUES ($1, $1, $2, NOW())
                    ON CONFLICT (user_id, currency) DO UPDATE SET updated_at = wallets.updated_at
                    RETURNING *
                    """,
                    user_id,
                    self._currency,
                )
                before = Decimal(str(wallet["balance"]))
                after = before + amount
                if after < 0:
                    raise ValueError("insufficient wallet balance")
                await conn.execute(
                    "UPDATE wallets SET balance = $3, updated_at = NOW() WHERE user_id = $1 AND currency = $2",
                    user_id,
                    self._currency,
                    after,
                )
                row = await conn.fetchrow(
                    """
                    INSERT INTO wallet_ledger (
                        user_id, currency, type, amount, balance_before, balance_after,
                        ref_type, ref_id, description
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    RETURNING *
                    """,
                    user_id,
                    self._currency,
                    ledger_type,
                    amount,
                    before,
                    after,
                    ref_type,
                    ref_id,
                    description,
                )
                return dict(row)

    async def freeze_for_bet(self, user_id: int, amount: Decimal, ref_id: str) -> bool:
        async with self._database.pool.acquire() as conn:
            async with conn.transaction():
                wallet = await conn.fetchrow(
                    "SELECT * FROM wallets WHERE user_id = $1 AND currency = $2 FOR UPDATE",
                    user_id,
                    self._currency,
                )
                if not wallet or Decimal(str(wallet["balance"])) < amount:
                    return False
                before = Decimal(str(wallet["balance"]))
                after = before - amount
                await conn.execute(
                    """
                    UPDATE wallets
                    SET balance = $3, frozen_balance = frozen_balance + $4, updated_at = NOW()
                    WHERE user_id = $1 AND currency = $2
                    """,
                    user_id,
                    self._currency,
                    after,
                    amount,
                )
                await conn.execute(
                    """
                    INSERT INTO wallet_ledger (
                        user_id, currency, type, amount, balance_before, balance_after,
                        ref_type, ref_id, description
                    )
                    VALUES ($1, $2, 'bet_freeze', $3, $4, $5, 'bet', $6, 'Bet stake freeze')
                    """,
                    user_id,
                    self._currency,
                    -amount,
                    before,
                    after,
                    ref_id,
                )
                return True

    async def release_freeze(self, user_id: int, amount: Decimal, ref_id: str) -> None:
        async with self._database.pool.acquire() as conn:
            async with conn.transaction():
                wallet = await conn.fetchrow(
                    "SELECT * FROM wallets WHERE user_id = $1 AND currency = $2 FOR UPDATE",
                    user_id,
                    self._currency,
                )
                if not wallet:
                    return
                before = Decimal(str(wallet["balance"]))
                after = before + amount
                await conn.execute(
                    """
                    UPDATE wallets
                    SET balance = $3,
                        frozen_balance = GREATEST(frozen_balance - $4, 0),
                        updated_at = NOW()
                    WHERE user_id = $1 AND currency = $2
                    """,
                    user_id,
                    self._currency,
                    after,
                    amount,
                )
                await conn.execute(
                    """
                    INSERT INTO wallet_ledger (
                        user_id, currency, type, amount, balance_before, balance_after,
                        ref_type, ref_id, description
                    )
                    VALUES ($1, $2, 'bet_settle', $3, $4, $5, 'bet', $6, 'Bet freeze release')
                    """,
                    user_id,
                    self._currency,
                    amount,
                    before,
                    after,
                    ref_id,
                )

    async def manual_adjust(self, user_id: int, amount: Decimal, reason: str, admin_user_id: int) -> dict:
        return await self.add_ledger_entry(
            user_id,
            "manual_adjust",
            amount,
            ref_type="admin",
            ref_id=str(admin_user_id),
            description=reason,
        )


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
