from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import asyncpg
from aiogram.types import Chat, User


class Database:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @property
    def pool(self) -> asyncpg.Pool:
        return self._pool

    @classmethod
    async def connect(cls, database_url: str) -> "Database":
        pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
        database = cls(pool)
        async with pool.acquire() as conn:
            await conn.execute("SELECT pg_advisory_lock(2026052801)")
            try:
                await database.ensure_schema()
            finally:
                await conn.execute("SELECT pg_advisory_unlock(2026052801)")
        return database

    async def ensure_schema(self) -> None:
        await self._pool.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS language TEXT")
        await self._pool.execute(
            "ALTER TABLE telegram_groups ADD COLUMN IF NOT EXISTS is_subscribed BOOLEAN NOT NULL DEFAULT FALSE"
        )
        await self._ensure_betting_schema()
        await self._ensure_wallet_schema()
        await self._ensure_futures_schema()
        await self.ensure_futures_seeded()

    async def _ensure_wallet_schema(self) -> None:
        await self._pool.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code TEXT")
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS wallets (
                id BIGSERIAL PRIMARY KEY,
                telegram_user_id BIGINT,
                user_id BIGINT,
                currency TEXT NOT NULL DEFAULT 'USDT',
                balance NUMERIC(18, 6) NOT NULL DEFAULT 0,
                frozen_balance NUMERIC(18, 6) NOT NULL DEFAULT 0,
                total_deposit NUMERIC(18, 6) NOT NULL DEFAULT 0,
                total_withdraw NUMERIC(18, 6) NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        for statement in (
            "ALTER TABLE wallets ADD COLUMN IF NOT EXISTS telegram_user_id BIGINT",
            "ALTER TABLE wallets ADD COLUMN IF NOT EXISTS user_id BIGINT",
            "ALTER TABLE wallets ADD COLUMN IF NOT EXISTS balance NUMERIC(18, 6) NOT NULL DEFAULT 0",
            "ALTER TABLE wallets ADD COLUMN IF NOT EXISTS frozen_balance NUMERIC(18, 6) NOT NULL DEFAULT 0",
            "ALTER TABLE wallets ADD COLUMN IF NOT EXISTS total_deposit NUMERIC(18, 6) NOT NULL DEFAULT 0",
            "ALTER TABLE wallets ADD COLUMN IF NOT EXISTS total_withdraw NUMERIC(18, 6) NOT NULL DEFAULT 0",
        ):
            await self._pool.execute(statement)
        await self._pool.execute("UPDATE wallets SET user_id = COALESCE(user_id, telegram_user_id)")
        await self._pool.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_wallets_user_currency ON wallets (user_id, currency)"
        )
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS deposit_orders (
                id BIGSERIAL PRIMARY KEY,
                order_id TEXT NOT NULL UNIQUE,
                user_id BIGINT NOT NULL,
                amount_requested NUMERIC(18, 6) NOT NULL,
                actual_amount NUMERIC(18, 6),
                trade_id TEXT,
                currency TEXT NOT NULL DEFAULT 'USDT',
                token TEXT,
                network TEXT,
                payment_url TEXT,
                expiration_time TIMESTAMPTZ,
                expires_at TIMESTAMPTZ,
                status TEXT NOT NULL DEFAULT 'pending',
                block_transaction_id TEXT,
                chain_tx_id TEXT,
                raw_response_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                raw_callback_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                paid_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await self._pool.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_deposit_orders_trade_id ON deposit_orders (trade_id) WHERE trade_id IS NOT NULL"
        )
        await self._pool.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_deposit_orders_block_tx ON deposit_orders (block_transaction_id) WHERE block_transaction_id IS NOT NULL"
        )
        for statement in (
            "ALTER TABLE deposit_orders ADD COLUMN IF NOT EXISTS currency TEXT NOT NULL DEFAULT 'USDT'",
            "ALTER TABLE deposit_orders ADD COLUMN IF NOT EXISTS network TEXT",
            "ALTER TABLE deposit_orders ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ",
            "ALTER TABLE deposit_orders ADD COLUMN IF NOT EXISTS chain_tx_id TEXT",
        ):
            await self._pool.execute(statement)
        await self._pool.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_deposit_orders_chain_tx ON deposit_orders (chain_tx_id) WHERE chain_tx_id IS NOT NULL"
        )
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS wallet_ledger (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                currency TEXT NOT NULL DEFAULT 'USDT',
                type TEXT NOT NULL,
                amount NUMERIC(18, 6) NOT NULL,
                balance_before NUMERIC(18, 6) NOT NULL,
                balance_after NUMERIC(18, 6) NOT NULL,
                ref_type TEXT,
                ref_id TEXT,
                description TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await self._pool.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_wallet_ledger_ref ON wallet_ledger (ref_type, ref_id, type) WHERE ref_type IS NOT NULL AND ref_id IS NOT NULL"
        )
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS referral_relations (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL UNIQUE,
                parent_user_id BIGINT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS commission_records (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                source_user_id BIGINT NOT NULL,
                source_type TEXT NOT NULL,
                source_ref_id TEXT NOT NULL,
                amount NUMERIC(18, 6) NOT NULL,
                rate NUMERIC(10, 6) NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                settled_at TIMESTAMPTZ
            )
            """
        )
        await self._pool.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_commission_source ON commission_records (user_id, source_type, source_ref_id)"
        )
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_audit_logs (
                id BIGSERIAL PRIMARY KEY,
                admin_user_id BIGINT NOT NULL,
                action TEXT NOT NULL,
                target_type TEXT,
                target_id TEXT,
                payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS withdraw_requests (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount NUMERIC(18, 6) NOT NULL,
                address TEXT,
                network TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )

    async def _ensure_betting_schema(self) -> None:
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS bets (
                id BIGSERIAL PRIMARY KEY,
                telegram_user_id BIGINT,
                user_id BIGINT,
                fixture_id BIGINT,
                fixture_label TEXT,
                market_key TEXT,
                market_title TEXT,
                selection TEXT,
                stake NUMERIC(12, 2),
                odds NUMERIC(10, 2),
                potential_payout NUMERIC(12, 2),
                bettable_status_at_submit TEXT,
                amount_cents BIGINT NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        for statement in (
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS telegram_user_id BIGINT",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS user_id BIGINT",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS fixture_id BIGINT",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS fixture_label TEXT",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS market_key TEXT",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS market_title TEXT",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS selection TEXT",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS stake NUMERIC(12, 2)",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS odds NUMERIC(10, 2)",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS potential_payout NUMERIC(12, 2)",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS bettable_status_at_submit TEXT",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS amount_cents BIGINT NOT NULL DEFAULT 0",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
        ):
            await self._pool.execute(statement)
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_market_overrides (
                id BIGSERIAL PRIMARY KEY,
                fixture_id BIGINT NOT NULL UNIQUE,
                is_suspended BOOLEAN NOT NULL DEFAULT FALSE,
                reason TEXT,
                updated_by BIGINT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await self._pool.execute("CREATE INDEX IF NOT EXISTS idx_bets_user ON bets (user_id, created_at DESC)")
        await self._pool.execute("CREATE INDEX IF NOT EXISTS idx_bets_fixture ON bets (fixture_id)")

    async def _ensure_futures_schema(self) -> None:
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS futures_markets (
                id BIGSERIAL PRIMARY KEY,
                market_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                description TEXT,
                category TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                settlement_rule TEXT,
                source TEXT NOT NULL DEFAULT 'manual',
                display_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS futures_options (
                id BIGSERIAL PRIMARY KEY,
                market_id BIGINT NOT NULL REFERENCES futures_markets(id) ON DELETE CASCADE,
                option_key TEXT NOT NULL,
                label TEXT NOT NULL,
                odds NUMERIC(10, 2) NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                display_order INTEGER NOT NULL DEFAULT 0,
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (market_id, option_key)
            )
            """
        )
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS user_predictions (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                market_id BIGINT NOT NULL REFERENCES futures_markets(id),
                option_id BIGINT NOT NULL REFERENCES futures_options(id),
                stake_simulated NUMERIC(12, 2) NOT NULL DEFAULT 0,
                odds NUMERIC(10, 2) NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await self._pool.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_predictions_user ON user_predictions (user_id, created_at DESC)"
        )

    async def ensure_futures_seeded(self) -> None:
        count = await self._pool.fetchval("SELECT COUNT(*) FROM futures_markets")
        if count:
            return
        await self._insert_futures_market(
            market_key="world_cup_winner",
            title="世界杯冠军预测",
            description="演示赔率，仅供功能测试。",
            category="world_cup",
            settlement_rule="球队赢得 2026 FIFA World Cup。",
            display_order=10,
            options=[
                ("brazil", "巴西", "5.50"),
                ("france", "法国", "6.00"),
                ("england", "英格兰", "7.00"),
                ("argentina", "阿根廷", "8.00"),
                ("spain", "西班牙", "8.50"),
                ("germany", "德国", "10.00"),
                ("portugal", "葡萄牙", "12.00"),
                ("netherlands", "荷兰", "15.00"),
                ("belgium", "比利时", "18.00"),
                ("uruguay", "乌拉圭", "21.00"),
            ],
        )
        await self._insert_futures_market(
            market_key="golden_boot",
            title="金靴奖预测",
            description="演示赔率，仅供功能测试。",
            category="world_cup",
            settlement_rule="球员获得 2026 FIFA World Cup Golden Boot。",
            display_order=20,
            options=[
                ("mbappe", "姆巴佩", "7.00"),
                ("haaland", "哈兰德", "8.00"),
                ("kane", "凯恩", "9.00"),
                ("vinicius", "维尼修斯", "12.00"),
                ("messi", "梅西", "15.00"),
            ],
        )

    async def _insert_futures_market(
        self,
        market_key: str,
        title: str,
        description: str,
        category: str,
        settlement_rule: str,
        display_order: int,
        options: list[tuple[str, str, str]],
    ) -> None:
        market_id = await self._pool.fetchval(
            """
            INSERT INTO futures_markets (
                market_key, title, description, category, settlement_rule, source, display_order, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, 'manual', $6, NOW())
            RETURNING id
            """,
            market_key,
            title,
            description,
            category,
            settlement_rule,
            display_order,
        )
        for index, (option_key, label, odds) in enumerate(options, start=1):
            await self._pool.execute(
                """
                INSERT INTO futures_options (
                    market_id, option_key, label, odds, status, display_order, metadata_json, updated_at
                )
                VALUES ($1, $2, $3, $4, 'active', $5, '{}'::jsonb, NOW())
                """,
                market_id,
                option_key,
                label,
                odds,
                index,
            )

    async def upsert_user(self, user: User) -> None:
        referral_code = _referral_code(user.id)
        await self._pool.execute(
            """
            INSERT INTO users (
                telegram_user_id, username, first_name, last_name, language_code, referral_code, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, NOW())
            ON CONFLICT (telegram_user_id)
            DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                language_code = EXCLUDED.language_code,
                language = COALESCE(users.language, EXCLUDED.language_code),
                referral_code = COALESCE(users.referral_code, EXCLUDED.referral_code),
                updated_at = NOW()
            """,
            user.id,
            user.username,
            user.first_name,
            user.last_name,
            user.language_code,
            referral_code,
        )

    async def upsert_group(self, chat: Chat) -> None:
        await self._pool.execute(
            """
            INSERT INTO telegram_groups (telegram_chat_id, title, chat_type, updated_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (telegram_chat_id)
            DO UPDATE SET
                title = EXCLUDED.title,
                chat_type = EXCLUDED.chat_type,
                updated_at = NOW()
            """,
            chat.id,
            chat.title,
            chat.type,
        )

    async def get_user_language(self, telegram_user_id: int, default: str) -> str:
        value = await self._pool.fetchval(
            "SELECT COALESCE(language, language_code) FROM users WHERE telegram_user_id = $1",
            telegram_user_id,
        )
        return value or default

    async def set_user_language(self, telegram_user_id: int, language: str) -> None:
        await self._pool.execute(
            """
            INSERT INTO users (telegram_user_id, language, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (telegram_user_id)
            DO UPDATE SET language = EXCLUDED.language, updated_at = NOW()
            """,
            telegram_user_id,
            language,
        )

    async def set_group_subscription(self, chat: Chat, is_subscribed: bool) -> None:
        await self.upsert_group(chat)
        await self._pool.execute(
            "UPDATE telegram_groups SET is_subscribed = $2, updated_at = NOW() WHERE telegram_chat_id = $1",
            chat.id,
            is_subscribed,
        )

    async def list_subscribed_groups(self) -> list[int]:
        rows = await self._pool.fetch(
            "SELECT telegram_chat_id FROM telegram_groups WHERE is_subscribed = TRUE"
        )
        return [int(row["telegram_chat_id"]) for row in rows]

    async def get_futures_market(self, market_key: str) -> dict | None:
        row = await self._pool.fetchrow(
            """
            SELECT id, market_key, title, description, category, status, settlement_rule, source, display_order
            FROM futures_markets
            WHERE market_key = $1
            """,
            market_key,
        )
        return dict(row) if row else None

    async def list_futures_options(self, market_key: str) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT
                m.id AS market_id,
                m.market_key,
                m.title AS market_title,
                m.description,
                o.id AS option_id,
                o.option_key,
                o.label,
                o.odds::TEXT AS odds,
                o.status,
                o.display_order
            FROM futures_markets m
            JOIN futures_options o ON o.market_id = m.id
            WHERE m.market_key = $1 AND m.status = 'open' AND o.status = 'active'
            ORDER BY o.display_order, o.id
            """,
            market_key,
        )
        return [dict(row) for row in rows]

    async def get_futures_option(self, option_id: int) -> dict | None:
        row = await self._pool.fetchrow(
            """
            SELECT
                m.id AS market_id,
                m.market_key,
                m.title AS market_title,
                o.id AS option_id,
                o.option_key,
                o.label,
                o.odds::TEXT AS odds
            FROM futures_markets m
            JOIN futures_options o ON o.market_id = m.id
            WHERE o.id = $1 AND m.status = 'open' AND o.status = 'active'
            """,
            option_id,
        )
        return dict(row) if row else None

    async def create_user_prediction(
        self,
        telegram_user_id: int,
        market_id: int,
        option_id: int,
        odds: str,
        stake_simulated: str = "10",
    ) -> int:
        return int(
            await self._pool.fetchval(
                """
                INSERT INTO user_predictions (
                    user_id, market_id, option_id, stake_simulated, odds, status
                )
                VALUES ($1, $2, $3, $4, $5, 'pending')
                RETURNING id
                """,
                telegram_user_id,
                market_id,
                option_id,
                stake_simulated,
                odds,
            )
        )

    async def list_user_predictions(self, telegram_user_id: int, limit: int = 10) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT
                p.id,
                p.stake_simulated::TEXT AS stake_simulated,
                p.odds::TEXT AS odds,
                p.status,
                p.created_at,
                m.title AS market_title,
                o.label AS option_label
            FROM user_predictions p
            JOIN futures_markets m ON m.id = p.market_id
            JOIN futures_options o ON o.id = p.option_id
            WHERE p.user_id = $1
            ORDER BY p.created_at DESC
            LIMIT $2
            """,
            telegram_user_id,
            limit,
        )
        return [dict(row) for row in rows]

    async def create_bet(
        self,
        telegram_user_id: int,
        fixture_id: int,
        fixture_label: str,
        market_key: str,
        market_title: str,
        selection: str,
        odds: str,
        stake: str,
        potential_payout: str,
        bettable_status_at_submit: str,
    ) -> int:
        return int(
            await self._pool.fetchval(
                """
                INSERT INTO bets (
                    telegram_user_id, user_id, fixture_id, fixture_label, market_key, market_title,
                    selection, odds, stake, potential_payout, status, bettable_status_at_submit, updated_at
                )
                VALUES ($1, $1, $2, $3, $4, $5, $6, $7, $8, $9, 'pending', $10, NOW())
                RETURNING id
                """,
                telegram_user_id,
                fixture_id,
                fixture_label,
                market_key,
                market_title,
                selection,
                odds,
                stake,
                potential_payout,
                bettable_status_at_submit,
            )
        )

    async def list_user_bets(self, telegram_user_id: int, status_group: str = "pending", limit: int = 20) -> list[dict]:
        if status_group == "settled":
            statuses = ("won", "lost", "cancelled", "void")
        else:
            statuses = ("pending",)
        rows = await self._pool.fetch(
            """
            SELECT
                id, fixture_id, fixture_label, market_key, market_title, selection,
                odds::TEXT AS odds, stake::TEXT AS stake, potential_payout::TEXT AS potential_payout,
                status, bettable_status_at_submit, created_at
            FROM bets
            WHERE COALESCE(user_id, telegram_user_id) = $1 AND status = ANY($2::TEXT[])
            ORDER BY created_at DESC
            LIMIT $3
            """,
            telegram_user_id,
            list(statuses),
            limit,
        )
        return [dict(row) for row in rows]

    async def count_user_pending_bets(self, telegram_user_id: int) -> int:
        return int(
            await self._pool.fetchval(
                "SELECT COUNT(*) FROM bets WHERE COALESCE(user_id, telegram_user_id) = $1 AND status = 'pending'",
                telegram_user_id,
            )
            or 0
        )

    async def get_market_override(self, fixture_id: int) -> dict | None:
        row = await self._pool.fetchrow(
            """
            SELECT fixture_id, is_suspended, reason, updated_by, created_at, updated_at
            FROM admin_market_overrides
            WHERE fixture_id = $1
            """,
            fixture_id,
        )
        return dict(row) if row else None

    async def get_market_overrides(self, fixture_ids: list[int]) -> dict[int, dict]:
        if not fixture_ids:
            return {}
        rows = await self._pool.fetch(
            """
            SELECT fixture_id, is_suspended, reason, updated_by, created_at, updated_at
            FROM admin_market_overrides
            WHERE fixture_id = ANY($1::BIGINT[])
            """,
            fixture_ids,
        )
        return {int(row["fixture_id"]): dict(row) for row in rows}

    async def set_market_suspended(
        self,
        fixture_id: int,
        is_suspended: bool,
        updated_by: int,
        reason: str | None = None,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO admin_market_overrides (fixture_id, is_suspended, reason, updated_by, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (fixture_id)
            DO UPDATE SET
                is_suspended = EXCLUDED.is_suspended,
                reason = EXCLUDED.reason,
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW()
            """,
            fixture_id,
            is_suspended,
            reason,
            updated_by,
        )

    async def create_deposit_order(self, user_id: int, order_id: str, amount: Decimal, currency: str = "USDT") -> dict:
        row = await self._pool.fetchrow(
            """
            INSERT INTO deposit_orders (order_id, user_id, amount_requested, currency, status, updated_at)
            VALUES ($1, $2, $3, $4, 'pending', NOW())
            RETURNING *
            """,
            order_id,
            user_id,
            amount,
            currency,
        )
        return dict(row)

    async def update_deposit_order_transaction(
        self,
        order_id: str,
        *,
        trade_id: str | None,
        actual_amount: Decimal,
        token: str,
        network: str | None = None,
        payment_url: str,
        expires_at: Any,
        raw_response: dict[str, Any],
    ) -> dict | None:
        row = await self._pool.fetchrow(
            """
            UPDATE deposit_orders
            SET trade_id = $2,
                actual_amount = $3,
                token = $4,
                payment_url = $5,
                expiration_time = $6,
                expires_at = $6,
                network = COALESCE($7, network),
                raw_response_json = $8::jsonb,
                updated_at = NOW()
            WHERE order_id = $1
            RETURNING *
            """,
            order_id,
            trade_id,
            actual_amount,
            token,
            payment_url,
            expires_at,
            network,
            json.dumps(raw_response),
        )
        return dict(row) if row else None

    async def get_deposit_order(self, order_id: str) -> dict | None:
        row = await self._pool.fetchrow("SELECT * FROM deposit_orders WHERE order_id = $1", order_id)
        return dict(row) if row else None

    async def list_deposit_orders(self, limit: int = 10) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT * FROM deposit_orders
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
        return [dict(row) for row in rows]

    async def list_user_deposit_orders(self, user_id: int, limit: int = 10) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT * FROM deposit_orders
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )
        return [dict(row) for row in rows]

    async def list_user_ledger(self, user_id: int, limit: int = 10) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT * FROM wallet_ledger
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )
        return [dict(row) for row in rows]

    async def get_referral_code(self, user_id: int) -> str:
        code = await self._pool.fetchval("SELECT referral_code FROM users WHERE telegram_user_id = $1", user_id)
        if code:
            return str(code)
        code = _referral_code(user_id)
        await self._pool.execute(
            "UPDATE users SET referral_code = $2, updated_at = NOW() WHERE telegram_user_id = $1",
            user_id,
            code,
        )
        return code

    async def bind_referral_parent(self, user_id: int, parent_user_id: int) -> bool:
        if user_id == parent_user_id:
            return False
        result = await self._pool.execute(
            """
            INSERT INTO referral_relations (user_id, parent_user_id)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO NOTHING
            """,
            user_id,
            parent_user_id,
        )
        return result.endswith("1")

    async def referral_parent_by_code(self, code: str) -> int | None:
        row = await self._pool.fetchrow(
            "SELECT telegram_user_id FROM users WHERE referral_code = $1",
            code,
        )
        if row:
            return int(row["telegram_user_id"])
        decoded = _decode_referral_code(code)
        if decoded:
            return decoded
        return None

    async def get_referral_summary(self, user_id: int) -> dict:
        row = await self._pool.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM referral_relations WHERE parent_user_id = $1) AS direct_count,
                COALESCE((
                    SELECT SUM(d.actual_amount)
                    FROM deposit_orders d
                    JOIN referral_relations r ON r.user_id = d.user_id
                    WHERE r.parent_user_id = $1 AND d.status = 'paid'
                ), 0) AS total_deposit,
                COALESCE((SELECT SUM(amount) FROM commission_records WHERE user_id = $1 AND status = 'pending'), 0) AS pending_commission,
                COALESCE((SELECT SUM(amount) FROM commission_records WHERE user_id = $1 AND status = 'settled'), 0) AS settled_commission
            """,
            user_id,
        )
        return dict(row)

    async def list_commissions(self, user_id: int | None = None, limit: int = 20) -> list[dict]:
        if user_id is None:
            rows = await self._pool.fetch(
                "SELECT * FROM commission_records ORDER BY created_at DESC LIMIT $1",
                limit,
            )
        else:
            rows = await self._pool.fetch(
                "SELECT * FROM commission_records WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
                user_id,
                limit,
            )
        return [dict(row) for row in rows]

    async def list_referrals(self, user_id: int, limit: int = 20) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT r.user_id, u.username, u.first_name, r.created_at
            FROM referral_relations r
            LEFT JOIN users u ON u.telegram_user_id = r.user_id
            WHERE r.parent_user_id = $1
            ORDER BY r.created_at DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )
        return [dict(row) for row in rows]

    async def settle_commission(self, commission_id: int) -> dict | None:
        row = await self._pool.fetchrow(
            """
            UPDATE commission_records
            SET status = 'settled', settled_at = NOW()
            WHERE id = $1 AND status = 'pending'
            RETURNING *
            """,
            commission_id,
        )
        return dict(row) if row else None

    async def add_admin_audit_log(
        self,
        admin_user_id: int,
        action: str,
        target_type: str | None,
        target_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO admin_audit_logs (admin_user_id, action, target_type, target_id, payload_json)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            """,
            admin_user_id,
            action,
            target_type,
            target_id,
            json.dumps(payload),
        )

    async def close(self) -> None:
        await self._pool.close()


def _referral_code(user_id: int) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    value = int(user_id)
    if value == 0:
        return "0"
    chars: list[str] = []
    while value:
        value, rem = divmod(value, 36)
        chars.append(alphabet[rem])
    return "".join(reversed(chars))


def _decode_referral_code(code: str) -> int | None:
    try:
        return int(code.lower(), 36)
    except ValueError:
        return None
