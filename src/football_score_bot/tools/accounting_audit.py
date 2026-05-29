from __future__ import annotations

import asyncio
import os
from decimal import Decimal

import asyncpg


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://football:football_password@postgres:5432/football_score_bot",
)
REAL_BETTING_ENABLED = os.getenv("REAL_BETTING_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
BET_REQUIRE_BALANCE_FOR_SIMULATION = os.getenv("BET_REQUIRE_BALANCE_FOR_SIMULATION", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


async def main() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    failures: list[str] = []
    try:
        await _check_non_negative_wallets(conn, failures)
        await _check_pending_bets_frozen(conn, failures)
        await _check_simulated_bets_do_not_freeze(conn, failures)
        await _check_simulation_balance_gate(conn, failures)
        await _check_ledger_running_balances(conn, failures)
        await _check_paid_deposits_have_ledger(conn, failures)
        await _check_settled_bets_have_ledger(conn, failures)
        await _check_pending_withdraws_frozen(conn, failures)
    finally:
        await conn.close()

    if failures:
        print("accounting_audit FAILED")
        for item in failures:
            print(f"- {item}")
        raise SystemExit(1)
    print("accounting_audit OK")


async def _check_non_negative_wallets(conn: asyncpg.Connection, failures: list[str]) -> None:
    rows = await conn.fetch(
        "SELECT user_id, currency, balance, frozen_balance FROM wallets WHERE balance < 0 OR frozen_balance < 0"
    )
    for row in rows:
        failures.append(
            f"negative wallet user={row['user_id']} currency={row['currency']} "
            f"balance={row['balance']} frozen={row['frozen_balance']}"
        )


async def _check_pending_bets_frozen(conn: asyncpg.Connection, failures: list[str]) -> None:
    if not REAL_BETTING_ENABLED:
        return
    rows = await conn.fetch(
        """
        SELECT id
        FROM bets
        WHERE status = 'pending' AND COALESCE(is_simulated, TRUE) = FALSE AND balance_frozen = FALSE
        """
    )
    for row in rows:
        failures.append(f"real pending bet not marked frozen bet_id={row['id']}")
    rows = await conn.fetch(
        """
        SELECT COALESCE(user_id, telegram_user_id) AS user_id, COALESCE(SUM(stake), 0) AS pending_stake
        FROM bets
        WHERE status = 'pending' AND COALESCE(is_simulated, TRUE) = FALSE AND balance_frozen = TRUE
        GROUP BY COALESCE(user_id, telegram_user_id)
        """
    )
    for row in rows:
        frozen = await conn.fetchval("SELECT frozen_balance FROM wallets WHERE user_id = $1", row["user_id"])
        if Decimal(str(frozen or 0)) < Decimal(str(row["pending_stake"] or 0)):
            failures.append(
                f"pending bet stake exceeds frozen balance user={row['user_id']} "
                f"stake={row['pending_stake']} frozen={frozen}"
            )


async def _check_simulated_bets_do_not_freeze(conn: asyncpg.Connection, failures: list[str]) -> None:
    rows = await conn.fetch(
        """
        SELECT id
        FROM bets
        WHERE COALESCE(is_simulated, TRUE) = TRUE AND COALESCE(balance_frozen, FALSE) = TRUE
        """
    )
    for row in rows:
        failures.append(f"simulated bet has frozen balance flag bet_id={row['id']}")


async def _check_simulation_balance_gate(conn: asyncpg.Connection, failures: list[str]) -> None:
    if not BET_REQUIRE_BALANCE_FOR_SIMULATION:
        return
    rows = await conn.fetch(
        """
        SELECT b.id, COALESCE(b.user_id, b.telegram_user_id) AS user_id, b.stake, COALESCE(w.balance, 0) AS balance
        FROM bets b
        LEFT JOIN wallets w ON w.user_id = COALESCE(b.user_id, b.telegram_user_id)
        WHERE b.status = 'pending'
          AND COALESCE(b.is_simulated, TRUE) = TRUE
          AND COALESCE(w.balance, 0) < b.stake
        """
    )
    for row in rows:
        failures.append(
            f"simulated pending bet exceeds current wallet balance bet_id={row['id']} "
            f"user={row['user_id']} stake={row['stake']} balance={row['balance']}"
        )


async def _check_ledger_running_balances(conn: asyncpg.Connection, failures: list[str]) -> None:
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (user_id, currency)
            user_id, currency, balance_after, frozen_after
        FROM wallet_ledger
        ORDER BY user_id, currency, created_at DESC, id DESC
        """
    )
    for row in rows:
        wallet = await conn.fetchrow(
            "SELECT balance, frozen_balance FROM wallets WHERE user_id = $1 AND currency = $2",
            row["user_id"],
            row["currency"],
        )
        if not wallet:
            failures.append(f"ledger without wallet user={row['user_id']} currency={row['currency']}")
            continue
        if Decimal(str(wallet["balance"])) != Decimal(str(row["balance_after"])):
            failures.append(
                f"wallet balance differs from last ledger user={row['user_id']} "
                f"wallet={wallet['balance']} ledger={row['balance_after']}"
            )


async def _check_paid_deposits_have_ledger(conn: asyncpg.Connection, failures: list[str]) -> None:
    rows = await conn.fetch(
        """
        SELECT d.order_id
        FROM deposit_orders d
        LEFT JOIN wallet_ledger l
          ON l.ref_type = 'deposit_order' AND l.ref_id = d.order_id AND l.type IN ('deposit', 'deposit_manual')
        WHERE d.status = 'paid' AND l.id IS NULL
        """
    )
    for row in rows:
        failures.append(f"paid deposit missing ledger order_id={row['order_id']}")


async def _check_settled_bets_have_ledger(conn: asyncpg.Connection, failures: list[str]) -> None:
    rows = await conn.fetch(
        """
        SELECT b.id, b.status, COALESCE(b.is_simulated, TRUE) AS is_simulated
        FROM bets b
        LEFT JOIN wallet_ledger l
          ON l.ref_type = 'bet' AND l.ref_id = b.id::TEXT
         AND l.type IN ('bet_win_payout', 'bet_loss', 'bet_void_refund', 'bet_cancel_refund')
        WHERE b.status IN ('won', 'lost', 'void', 'cancelled')
          AND COALESCE(b.is_simulated, TRUE) = FALSE
          AND l.id IS NULL
        """
    )
    for row in rows:
        failures.append(f"settled bet missing ledger bet_id={row['id']} status={row['status']}")


async def _check_pending_withdraws_frozen(conn: asyncpg.Connection, failures: list[str]) -> None:
    rows = await conn.fetch(
        """
        SELECT user_id, COALESCE(SUM(amount), 0) AS pending_amount
        FROM withdraw_requests
        WHERE status IN ('pending', 'approved')
        GROUP BY user_id
        """
    )
    for row in rows:
        frozen = await conn.fetchval("SELECT frozen_balance FROM wallets WHERE user_id = $1", row["user_id"])
        if Decimal(str(frozen or 0)) < Decimal(str(row["pending_amount"] or 0)):
            failures.append(
                f"pending withdraw exceeds frozen balance user={row['user_id']} "
                f"withdraw={row['pending_amount']} frozen={frozen}"
            )


if __name__ == "__main__":
    asyncio.run(main())
