from __future__ import annotations

import json
import random
import string
import time
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

    async def credit_deposit(
        self,
        user_id: int,
        deposit_order: dict,
        callback_payload: dict[str, Any] | None = None,
        *,
        ledger_type: str = "deposit",
        description: str = "GMPay deposit",
    ) -> bool:
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
                    VALUES ($1, $2, $7, $3, $4, $5, 'deposit_order', $6, $8)
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """,
                    user_id,
                    self._currency,
                    actual_amount,
                    balance_before,
                    balance_after,
                    order_id,
                    ledger_type,
                    description,
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
                        manual_review_required = FALSE,
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

    async def submit_bet(
        self,
        *,
        user_id: int,
        fixture_id: int,
        fixture_label: str,
        market_key: str,
        market_title: str,
        selection: str,
        odds: str,
        stake: Decimal,
        potential_payout: Decimal,
        bettable_status_at_submit: str,
        real_betting_enabled: bool,
        league_name: str | None = None,
        home_team: str | None = None,
        away_team: str | None = None,
        fixture_start_time: Any | None = None,
    ) -> int | None:
        async with self._database.pool.acquire() as conn:
            async with conn.transaction():
                wallet = None
                balance_before = Decimal("0")
                frozen_before = Decimal("0")
                if real_betting_enabled:
                    wallet = await self._locked_wallet(conn, user_id)
                    balance_before = Decimal(str(wallet["balance"]))
                    frozen_before = Decimal(str(wallet["frozen_balance"]))
                    if balance_before < stake:
                        return None
                bet_id = None
                bet_no = ""
                for _ in range(8):
                    bet_no = _new_bet_no()
                    bet_id = await conn.fetchval(
                        """
                        INSERT INTO bets (
                            bet_no, telegram_user_id, user_id, fixture_id, fixture_label, league_name,
                            home_team, away_team, fixture_start_time, market_key, market_title,
                            selection, odds, stake, potential_payout, payout, status,
                            bettable_status_at_submit, balance_frozen, is_simulated, updated_at
                        )
                        VALUES (
                            $1, $2, $2, $3, $4, $5,
                            $6, $7, $8, $9, $10,
                            $11, $12, $13, $14, 0, 'pending',
                            $15, $16, $17, NOW()
                        )
                        ON CONFLICT (bet_no) DO NOTHING
                        RETURNING id
                        """,
                        bet_no,
                        user_id,
                        fixture_id,
                        fixture_label,
                        league_name,
                        home_team,
                        away_team,
                        fixture_start_time,
                        market_key,
                        market_title,
                        selection,
                        odds,
                        stake,
                        potential_payout,
                        bettable_status_at_submit,
                        real_betting_enabled,
                        not real_betting_enabled,
                    )
                    if bet_id:
                        break
                if not bet_id:
                    raise RuntimeError("failed to allocate bet number")
                if not real_betting_enabled:
                    return int(bet_id)

                balance_after = balance_before - stake
                frozen_after = frozen_before + stake
                await conn.execute(
                    """
                    UPDATE wallets
                    SET balance = $3, frozen_balance = $4, updated_at = NOW()
                    WHERE user_id = $1 AND currency = $2
                    """,
                    user_id,
                    self._currency,
                    balance_after,
                    frozen_after,
                )
                await conn.execute(
                    """
                    INSERT INTO wallet_ledger (
                        user_id, currency, type, amount, balance_before, balance_after,
                        frozen_before, frozen_after, ref_type, ref_id, description
                    )
                    VALUES ($1, $2, 'bet_freeze', $3, $4, $5, $6, $7, 'bet', $8, 'Bet stake freeze')
                    """,
                    user_id,
                    self._currency,
                    -stake,
                    balance_before,
                    balance_after,
                    frozen_before,
                    frozen_after,
                    str(bet_id),
                )
                return int(bet_id)

    async def cancel_bet(self, bet_id: int, user_id: int, *, real_betting_enabled: bool) -> dict | None:
        async with self._database.pool.acquire() as conn:
            async with conn.transaction():
                bet = await conn.fetchrow(
                    "SELECT * FROM bets WHERE id = $1 AND COALESCE(user_id, telegram_user_id) = $2 FOR UPDATE",
                    bet_id,
                    user_id,
                )
                if not bet or bet["status"] != "pending":
                    return None
                stake = Decimal(str(bet["stake"] or 0))
                if real_betting_enabled and bool(bet["balance_frozen"]):
                    wallet = await self._locked_wallet(conn, user_id)
                    balance_before = Decimal(str(wallet["balance"]))
                    frozen_before = Decimal(str(wallet["frozen_balance"]))
                    if frozen_before < stake:
                        raise ValueError("insufficient frozen balance")
                    balance_after = balance_before + stake
                    frozen_after = frozen_before - stake
                    await conn.execute(
                        """
                        UPDATE wallets
                        SET balance = $3, frozen_balance = $4, updated_at = NOW()
                        WHERE user_id = $1 AND currency = $2
                        """,
                        user_id,
                        self._currency,
                        balance_after,
                        frozen_after,
                    )
                    await conn.execute(
                        """
                        INSERT INTO wallet_ledger (
                            user_id, currency, type, amount, balance_before, balance_after,
                            frozen_before, frozen_after, ref_type, ref_id, description
                        )
                        VALUES ($1, $2, 'bet_cancel_refund', $3, $4, $5, $6, $7, 'bet', $8, 'Bet cancelled before lock')
                        ON CONFLICT DO NOTHING
                        """,
                        user_id,
                        self._currency,
                        stake,
                        balance_before,
                        balance_after,
                        frozen_before,
                        frozen_after,
                        str(bet_id),
                    )
                row = await conn.fetchrow(
                    """
                    UPDATE bets
                    SET status = 'cancelled',
                        payout = 0,
                        settlement_source = 'user',
                        settlement_note = 'cancelled by user',
                        settled_at = NOW(),
                        updated_at = NOW()
                    WHERE id = $1 AND status = 'pending'
                    RETURNING *
                    """,
                    bet_id,
                )
                return dict(row) if row else None

    async def settle_bet(
        self,
        bet_id: int,
        admin_user_id: int,
        outcome: str,
        *,
        source: str = "admin",
        result_score: str | None = None,
        note: str | None = None,
    ) -> dict | None:
        if outcome not in {"won", "lost", "void", "cancelled"}:
            raise ValueError("invalid bet outcome")
        async with self._database.pool.acquire() as conn:
            async with conn.transaction():
                bet = await conn.fetchrow("SELECT * FROM bets WHERE id = $1 FOR UPDATE", bet_id)
                if not bet or bet["status"] not in {"pending", "manual_required"}:
                    return None
                user_id = int(bet["user_id"] or bet["telegram_user_id"])
                stake = Decimal(str(bet["stake"] or 0))
                payout = Decimal(str(bet["potential_payout"] or 0))
                wallet = await self._locked_wallet(conn, user_id)
                balance_before = Decimal(str(wallet["balance"]))
                frozen_before = Decimal(str(wallet["frozen_balance"]))
                if bool(bet["balance_frozen"]) and frozen_before < stake:
                    raise ValueError("insufficient frozen balance")
                frozen_after = frozen_before - stake if bet["balance_frozen"] else frozen_before
                if outcome == "won":
                    balance_delta = payout
                    ledger_type = "bet_win_payout"
                elif outcome == "lost":
                    balance_delta = Decimal("0")
                    ledger_type = "bet_loss"
                else:
                    balance_delta = stake if bet["balance_frozen"] else Decimal("0")
                    ledger_type = "bet_cancel_refund" if outcome == "cancelled" else "bet_void_refund"
                balance_after = balance_before + balance_delta
                await conn.execute(
                    """
                    UPDATE wallets
                    SET balance = $3, frozen_balance = $4, updated_at = NOW()
                    WHERE user_id = $1 AND currency = $2
                    """,
                    user_id,
                    self._currency,
                    balance_after,
                    frozen_after,
                )
                amount = balance_delta if outcome != "lost" else Decimal("0")
                await conn.execute(
                    """
                    INSERT INTO wallet_ledger (
                        user_id, currency, type, amount, balance_before, balance_after,
                        frozen_before, frozen_after, ref_type, ref_id, description
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'bet', $9, $10)
                    """,
                    user_id,
                    self._currency,
                    ledger_type,
                    amount,
                    balance_before,
                    balance_after,
                    frozen_before,
                    frozen_after,
                    str(bet_id),
                    f"Admin bet settlement: {outcome}",
                )
                await conn.execute(
                    """
                    UPDATE bets
                    SET status = $2,
                        payout = $4,
                        result_score = COALESCE($5, result_score),
                        settlement_source = $6,
                        settlement_note = $7,
                        settled_by_admin_id = $3,
                        settled_at = NOW(),
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                    bet_id,
                    outcome,
                    admin_user_id,
                    amount,
                    result_score,
                    source,
                    note or f"{source} settlement: {outcome}",
                )
                await conn.execute(
                    """
                    INSERT INTO settlement_logs (
                        bet_id, fixture_id, previous_status, new_status, result_score, payout, source
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    bet_id,
                    bet["fixture_id"],
                    bet["status"],
                    outcome,
                    result_score,
                    amount,
                    source,
                )
                return {"bet_id": bet_id, "user_id": user_id, "status": outcome, "balance_after": balance_after}

    async def create_withdraw_request(self, user_id: int, amount: Decimal, address: str, network: str) -> dict | None:
        async with self._database.pool.acquire() as conn:
            async with conn.transaction():
                wallet = await self._locked_wallet(conn, user_id)
                balance_before = Decimal(str(wallet["balance"]))
                frozen_before = Decimal(str(wallet["frozen_balance"]))
                if balance_before < amount:
                    return None
                balance_after = balance_before - amount
                frozen_after = frozen_before + amount
                row = await conn.fetchrow(
                    """
                    INSERT INTO withdraw_requests (user_id, amount, address, network, status)
                    VALUES ($1, $2, $3, $4, 'pending')
                    RETURNING *
                    """,
                    user_id,
                    amount,
                    address,
                    network,
                )
                await conn.execute(
                    """
                    UPDATE wallets
                    SET balance = $3, frozen_balance = $4, updated_at = NOW()
                    WHERE user_id = $1 AND currency = $2
                    """,
                    user_id,
                    self._currency,
                    balance_after,
                    frozen_after,
                )
                await conn.execute(
                    """
                    INSERT INTO wallet_ledger (
                        user_id, currency, type, amount, balance_before, balance_after,
                        frozen_before, frozen_after, ref_type, ref_id, description
                    )
                    VALUES ($1, $2, 'withdraw_freeze', $3, $4, $5, $6, $7, 'withdraw', $8, 'Withdraw request freeze')
                    """,
                    user_id,
                    self._currency,
                    -amount,
                    balance_before,
                    balance_after,
                    frozen_before,
                    frozen_after,
                    str(row["id"]),
                )
                return dict(row)

    async def approve_withdraw(self, withdraw_id: int, admin_user_id: int, note: str | None = None) -> dict | None:
        return await self._update_withdraw_status(withdraw_id, admin_user_id, "approved", note)

    async def mark_withdraw_paid(self, withdraw_id: int, admin_user_id: int, txid: str) -> dict | None:
        async with self._database.pool.acquire() as conn:
            async with conn.transaction():
                request = await conn.fetchrow("SELECT * FROM withdraw_requests WHERE id = $1 FOR UPDATE", withdraw_id)
                if not request or request["status"] not in {"approved", "pending"}:
                    return None
                user_id = int(request["user_id"])
                amount = Decimal(str(request["amount"]))
                wallet = await self._locked_wallet(conn, user_id)
                balance_before = Decimal(str(wallet["balance"]))
                frozen_before = Decimal(str(wallet["frozen_balance"]))
                if frozen_before < amount:
                    raise ValueError("insufficient frozen balance")
                frozen_after = frozen_before - amount
                await conn.execute(
                    """
                    UPDATE wallets
                    SET frozen_balance = $3, total_withdraw = total_withdraw + $4, updated_at = NOW()
                    WHERE user_id = $1 AND currency = $2
                    """,
                    user_id,
                    self._currency,
                    frozen_after,
                    amount,
                )
                await conn.execute(
                    """
                    INSERT INTO wallet_ledger (
                        user_id, currency, type, amount, balance_before, balance_after,
                        frozen_before, frozen_after, ref_type, ref_id, description
                    )
                    VALUES ($1, $2, 'withdraw_paid', $3, $4, $4, $5, $6, 'withdraw', $7, $8)
                    """,
                    user_id,
                    self._currency,
                    -amount,
                    balance_before,
                    frozen_before,
                    frozen_after,
                    str(withdraw_id),
                    f"Withdraw paid txid={txid}",
                )
                row = await conn.fetchrow(
                    """
                    UPDATE withdraw_requests
                    SET status = 'paid', admin_id = $2, admin_note = $3, reviewed_at = COALESCE(reviewed_at, NOW()), paid_at = NOW()
                    WHERE id = $1
                    RETURNING *
                    """,
                    withdraw_id,
                    admin_user_id,
                    txid,
                )
                return dict(row)

    async def reject_withdraw(self, withdraw_id: int, admin_user_id: int, reason: str) -> dict | None:
        async with self._database.pool.acquire() as conn:
            async with conn.transaction():
                request = await conn.fetchrow("SELECT * FROM withdraw_requests WHERE id = $1 FOR UPDATE", withdraw_id)
                if not request or request["status"] not in {"pending", "approved"}:
                    return None
                user_id = int(request["user_id"])
                amount = Decimal(str(request["amount"]))
                wallet = await self._locked_wallet(conn, user_id)
                balance_before = Decimal(str(wallet["balance"]))
                frozen_before = Decimal(str(wallet["frozen_balance"]))
                if frozen_before < amount:
                    raise ValueError("insufficient frozen balance")
                balance_after = balance_before + amount
                frozen_after = frozen_before - amount
                await conn.execute(
                    """
                    UPDATE wallets
                    SET balance = $3, frozen_balance = $4, updated_at = NOW()
                    WHERE user_id = $1 AND currency = $2
                    """,
                    user_id,
                    self._currency,
                    balance_after,
                    frozen_after,
                )
                await conn.execute(
                    """
                    INSERT INTO wallet_ledger (
                        user_id, currency, type, amount, balance_before, balance_after,
                        frozen_before, frozen_after, ref_type, ref_id, description
                    )
                    VALUES ($1, $2, 'withdraw_reject_refund', $3, $4, $5, $6, $7, 'withdraw', $8, $9)
                    """,
                    user_id,
                    self._currency,
                    amount,
                    balance_before,
                    balance_after,
                    frozen_before,
                    frozen_after,
                    str(withdraw_id),
                    reason,
                )
                row = await conn.fetchrow(
                    """
                    UPDATE withdraw_requests
                    SET status = 'rejected', admin_id = $2, admin_note = $3, reviewed_at = NOW()
                    WHERE id = $1
                    RETURNING *
                    """,
                    withdraw_id,
                    admin_user_id,
                    reason,
                )
                return dict(row)

    async def generate_rebates(self, period_start: Any, period_end: Any) -> int:
        async with self._database.pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    """
                    WITH stats AS (
                        SELECT
                            u.telegram_user_id AS user_id,
                            COALESCE((
                                SELECT SUM(stake)
                                FROM bets b
                                WHERE COALESCE(b.user_id, b.telegram_user_id) = u.telegram_user_id
                                  AND b.status IN ('won', 'lost')
                                  AND b.settled_at >= $1 AND b.settled_at < $2
                            ), 0) AS turnover,
                            COALESCE((
                                SELECT COUNT(*)
                                FROM referral_relations r
                                WHERE r.parent_user_id = u.telegram_user_id
                                  AND (
                                      EXISTS (
                                          SELECT 1 FROM deposit_orders d
                                          WHERE d.user_id = r.user_id AND d.status = 'paid'
                                            AND d.paid_at >= $1 AND d.paid_at < $2
                                      )
                                      OR EXISTS (
                                          SELECT 1 FROM bets cb
                                          WHERE COALESCE(cb.user_id, cb.telegram_user_id) = r.user_id
                                            AND cb.status IN ('won', 'lost')
                                            AND cb.settled_at >= $1 AND cb.settled_at < $2
                                      )
                                  )
                            ), 0) AS active_referrals
                        FROM users u
                    )
                    SELECT s.*, r.id AS rule_id, r.rebate_rate
                    FROM stats s
                    JOIN LATERAL (
                        SELECT *
                        FROM rebate_rules rr
                        WHERE rr.status = 'active'
                          AND (
                              (rr.mode = 'turnover' AND s.turnover >= rr.min_turnover)
                              OR (rr.mode = 'active_referrals' AND s.active_referrals >= rr.min_active_referrals)
                          )
                        ORDER BY rr.rebate_rate DESC, rr.id DESC
                        LIMIT 1
                    ) r ON TRUE
                    WHERE s.turnover > 0 OR s.active_referrals > 0
                    """
                    ,
                    period_start,
                    period_end,
                )
                count = 0
                for row in rows:
                    amount = (Decimal(str(row["turnover"])) * Decimal(str(row["rebate_rate"]))).quantize(Decimal("0.000001"))
                    if amount <= 0:
                        continue
                    result = await conn.execute(
                        """
                        INSERT INTO rebate_records (
                            user_id, period_start, period_end, turnover, active_referrals,
                            rebate_amount, rule_id, status
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending')
                        ON CONFLICT DO NOTHING
                        """,
                        int(row["user_id"]),
                        period_start,
                        period_end,
                        row["turnover"],
                        row["active_referrals"],
                        amount,
                        row["rule_id"],
                    )
                    if result.endswith("1"):
                        count += 1
                return count

    async def settle_rebate(self, rebate_record_id: int) -> dict | None:
        async with self._database.pool.acquire() as conn:
            async with conn.transaction():
                rebate = await conn.fetchrow("SELECT * FROM rebate_records WHERE id = $1 FOR UPDATE", rebate_record_id)
                if not rebate or rebate["status"] != "pending":
                    return None
                user_id = int(rebate["user_id"])
                amount = Decimal(str(rebate["rebate_amount"]))
                wallet = await self._locked_wallet(conn, user_id)
                balance_before = Decimal(str(wallet["balance"]))
                frozen_before = Decimal(str(wallet["frozen_balance"]))
                balance_after = balance_before + amount
                await conn.execute(
                    "UPDATE wallets SET balance = $3, updated_at = NOW() WHERE user_id = $1 AND currency = $2",
                    user_id,
                    self._currency,
                    balance_after,
                )
                await conn.execute(
                    """
                    INSERT INTO wallet_ledger (
                        user_id, currency, type, amount, balance_before, balance_after,
                        frozen_before, frozen_after, ref_type, ref_id, description
                    )
                    VALUES ($1, $2, 'rebate', $3, $4, $5, $6, $6, 'rebate', $7, 'Admin rebate settlement')
                    """,
                    user_id,
                    self._currency,
                    amount,
                    balance_before,
                    balance_after,
                    frozen_before,
                    str(rebate_record_id),
                )
                row = await conn.fetchrow(
                    """
                    UPDATE rebate_records
                    SET status = 'settled', settled_at = NOW()
                    WHERE id = $1
                    RETURNING *
                    """,
                    rebate_record_id,
                )
                return dict(row)

    async def _update_withdraw_status(
        self,
        withdraw_id: int,
        admin_user_id: int,
        status: str,
        note: str | None,
    ) -> dict | None:
        row = await self._database.pool.fetchrow(
            """
            UPDATE withdraw_requests
            SET status = $2, admin_id = $3, admin_note = $4, reviewed_at = NOW()
            WHERE id = $1 AND status = 'pending'
            RETURNING *
            """,
            withdraw_id,
            status,
            admin_user_id,
            note,
        )
        return dict(row) if row else None

    async def _locked_wallet(self, conn: Any, user_id: int) -> Any:
        return await conn.fetchrow(
            """
            INSERT INTO wallets (telegram_user_id, user_id, currency, updated_at)
            VALUES ($1, $1, $2, NOW())
            ON CONFLICT (user_id, currency) DO UPDATE SET updated_at = wallets.updated_at
            RETURNING *
            """,
            user_id,
            self._currency,
        )


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _new_bet_no() -> str:
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    value = int(time.time() * 1000)
    chars: list[str] = []
    while value:
        value, rem = divmod(value, 36)
        chars.append(alphabet[rem])
    suffix = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    return "B" + "".join(reversed(chars))[-7:] + suffix
