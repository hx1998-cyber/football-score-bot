from __future__ import annotations

import json
import logging
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any

import asyncpg
from aiogram.types import Chat, User

from football_score_bot.worldcup_futures import (
    WORLD_CUP_CHAMPION_LEGACY_KEY,
    WORLD_CUP_CHAMPION_MARKET_KEY,
    WORLD_CUP_CHAMPION_ODDS,
    WORLD_CUP_CHAMPION_TITLE,
    champion_option_label,
    champion_option_metadata,
)

logger = logging.getLogger(__name__)


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
        await self._ensure_role_schema()
        await self._ensure_futures_schema()
        await self.ensure_futures_seeded()
        await self._ensure_referral_reward_schema()
        await self._ensure_agent_rebate_schema()

    async def _ensure_role_schema(self) -> None:
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS user_roles (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL UNIQUE,
                role TEXT NOT NULL DEFAULT 'user',
                invited_by_user_id BIGINT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_applications (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                total_deposit NUMERIC(18, 6) NOT NULL DEFAULT 0,
                total_turnover NUMERIC(18, 6) NOT NULL DEFAULT 0,
                valid_referrals INTEGER NOT NULL DEFAULT 0,
                note TEXT,
                reviewed_by BIGINT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                reviewed_at TIMESTAMPTZ
            )
            """
        )

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
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS bet_restricted BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS withdraw_restricted BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS ban_reason TEXT",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS risk_note TEXT",
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
                error_message TEXT,
                manual_review_required BOOLEAN NOT NULL DEFAULT FALSE,
                manual_review_note TEXT,
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
            "ALTER TABLE deposit_orders ADD COLUMN IF NOT EXISTS error_message TEXT",
            "ALTER TABLE deposit_orders ADD COLUMN IF NOT EXISTS manual_review_required BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE deposit_orders ADD COLUMN IF NOT EXISTS manual_review_note TEXT",
            "ALTER TABLE deposit_orders ADD COLUMN IF NOT EXISTS original_payment_url TEXT",
            "ALTER TABLE deposit_orders ADD COLUMN IF NOT EXISTS final_payment_url TEXT",
            "ALTER TABLE deposit_orders ADD COLUMN IF NOT EXISTS payment_url_check_status TEXT",
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
                frozen_before NUMERIC(18, 6) NOT NULL DEFAULT 0,
                frozen_after NUMERIC(18, 6) NOT NULL DEFAULT 0,
                ref_type TEXT,
                ref_id TEXT,
                description TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        for statement in (
            "ALTER TABLE wallet_ledger ADD COLUMN IF NOT EXISTS frozen_before NUMERIC(18, 6) NOT NULL DEFAULT 0",
            "ALTER TABLE wallet_ledger ADD COLUMN IF NOT EXISTS frozen_after NUMERIC(18, 6) NOT NULL DEFAULT 0",
        ):
            await self._pool.execute(statement)
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
                fee_amount NUMERIC(18, 6) NOT NULL DEFAULT 0,
                net_amount NUMERIC(18, 6) NOT NULL DEFAULT 0,
                address TEXT,
                network TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                admin_id BIGINT,
                admin_note TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                reviewed_at TIMESTAMPTZ,
                paid_at TIMESTAMPTZ
            )
            """
        )
        for statement in (
            "ALTER TABLE withdraw_requests ADD COLUMN IF NOT EXISTS admin_id BIGINT",
            "ALTER TABLE withdraw_requests ADD COLUMN IF NOT EXISTS admin_note TEXT",
            "ALTER TABLE withdraw_requests ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ",
            "ALTER TABLE withdraw_requests ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ",
            "ALTER TABLE withdraw_requests ADD COLUMN IF NOT EXISTS fee_amount NUMERIC(18, 6) NOT NULL DEFAULT 0",
            "ALTER TABLE withdraw_requests ADD COLUMN IF NOT EXISTS net_amount NUMERIC(18, 6) NOT NULL DEFAULT 0",
        ):
            await self._pool.execute(statement)
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS payout_freezes (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                bet_id BIGINT,
                amount NUMERIC(18, 6) NOT NULL,
                status TEXT NOT NULL DEFAULT 'frozen',
                unlock_at TIMESTAMPTZ NOT NULL,
                unlocked_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                note TEXT
            )
            """
        )
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS wallet_freezes (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount NUMERIC(18, 6) NOT NULL,
                freeze_type TEXT NOT NULL DEFAULT 'admin',
                status TEXT NOT NULL DEFAULT 'frozen',
                reason TEXT,
                created_by_admin_id BIGINT,
                unlock_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                unlocked_at TIMESTAMPTZ
            )
            """
        )
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS rebate_rules (
                id BIGSERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                mode TEXT NOT NULL,
                min_active_referrals INTEGER NOT NULL DEFAULT 0,
                min_turnover NUMERIC(18, 6) NOT NULL DEFAULT 0,
                rebate_rate NUMERIC(10, 6) NOT NULL DEFAULT 0,
                threshold NUMERIC(18, 6) NOT NULL DEFAULT 0,
                rate NUMERIC(10, 6) NOT NULL DEFAULT 0,
                fixed_amount NUMERIC(18, 6) NOT NULL DEFAULT 0,
                role_scope TEXT NOT NULL DEFAULT 'user',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        for statement in (
            "ALTER TABLE rebate_rules ADD COLUMN IF NOT EXISTS threshold NUMERIC(18, 6) NOT NULL DEFAULT 0",
            "ALTER TABLE rebate_rules ADD COLUMN IF NOT EXISTS rate NUMERIC(10, 6) NOT NULL DEFAULT 0",
            "ALTER TABLE rebate_rules ADD COLUMN IF NOT EXISTS fixed_amount NUMERIC(18, 6) NOT NULL DEFAULT 0",
            "ALTER TABLE rebate_rules ADD COLUMN IF NOT EXISTS role_scope TEXT NOT NULL DEFAULT 'user'",
        ):
            await self._pool.execute(statement)
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS rebate_records (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                period_start TIMESTAMPTZ NOT NULL,
                period_end TIMESTAMPTZ NOT NULL,
                turnover NUMERIC(18, 6) NOT NULL DEFAULT 0,
                active_referrals INTEGER NOT NULL DEFAULT 0,
                rebate_amount NUMERIC(18, 6) NOT NULL DEFAULT 0,
                rule_id BIGINT REFERENCES rebate_rules(id),
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                settled_at TIMESTAMPTZ
            )
            """
        )
        await self._pool.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_rebate_records_period ON rebate_records (user_id, period_start, period_end, rule_id)"
        )
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS rebate_requests (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                requested_to_user_id BIGINT,
                period_start TIMESTAMPTZ,
                period_end TIMESTAMPTZ,
                turnover NUMERIC(18, 6) NOT NULL DEFAULT 0,
                active_referrals INTEGER NOT NULL DEFAULT 0,
                requested_amount NUMERIC(18, 6) NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                note TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                reviewed_at TIMESTAMPTZ
            )
            """
        )
        for statement in (
            "ALTER TABLE rebate_requests ADD COLUMN IF NOT EXISTS approved_amount NUMERIC(18, 6)",
            "ALTER TABLE rebate_requests ADD COLUMN IF NOT EXISTS review_reason TEXT",
            "ALTER TABLE rebate_requests ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ",
        ):
            await self._pool.execute(statement)

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
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS balance_frozen BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS bet_no TEXT",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS league_name TEXT",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS home_team TEXT",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS away_team TEXT",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS fixture_start_time TIMESTAMPTZ",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS payout NUMERIC(12, 2) NOT NULL DEFAULT 0",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS is_simulated BOOLEAN NOT NULL DEFAULT TRUE",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS result_score TEXT",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS settlement_source TEXT",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS settlement_note TEXT",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS settled_by_admin_id BIGINT",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS settled_at TIMESTAMPTZ",
            "ALTER TABLE bets ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
        ):
            await self._pool.execute(statement)
        await self._pool.execute(
            """
            UPDATE bets
            SET bet_no = 'B' || upper(to_hex(id::BIGINT))
            WHERE bet_no IS NULL
            """
        )
        await self._pool.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_bets_bet_no ON bets (bet_no)")
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS settlement_logs (
                id BIGSERIAL PRIMARY KEY,
                bet_id BIGINT NOT NULL,
                fixture_id BIGINT,
                previous_status TEXT,
                new_status TEXT NOT NULL,
                result_score TEXT,
                payout NUMERIC(12, 2) NOT NULL DEFAULT 0,
                source TEXT NOT NULL,
                raw_fixture_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS cancel_requests (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                bet_id BIGINT NOT NULL REFERENCES bets(id),
                status TEXT NOT NULL DEFAULT 'pending',
                reason TEXT,
                admin_id BIGINT,
                admin_reason TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                reviewed_at TIMESTAMPTZ
            )
            """
        )
        await self._pool.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_cancel_requests_pending_bet
            ON cancel_requests (bet_id)
            WHERE status = 'pending'
            """
        )
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

    async def _ensure_referral_reward_schema(self) -> None:
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS referral_rewards (
                id BIGSERIAL PRIMARY KEY,
                referrer_user_id BIGINT NOT NULL,
                referee_user_id BIGINT NOT NULL,
                threshold_amount NUMERIC(18, 6) NOT NULL DEFAULT 50,
                reward_amount NUMERIC(18, 6) NOT NULL DEFAULT 8,
                referee_valid_stake NUMERIC(18, 6) NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                rewarded_ledger_id BIGINT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                rewarded_at TIMESTAMPTZ,
                UNIQUE(referrer_user_id, referee_user_id)
            )
            """
        )
        await self._pool.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_referral_rewards_referrer_referee ON referral_rewards(referrer_user_id, referee_user_id)"
        )

    async def _ensure_agent_rebate_schema(self) -> None:
        await self._pool.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_profiles (
                user_id BIGINT PRIMARY KEY,
                role TEXT NOT NULL DEFAULT 'agent',
                rebate_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                rebate_rate NUMERIC(8, 4) NOT NULL DEFAULT 0.20,
                settled_rebate_stake NUMERIC(18, 6) NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        for statement in (
            "ALTER TABLE rebate_requests ADD COLUMN IF NOT EXISTS stake_amount NUMERIC(18, 6) NOT NULL DEFAULT 0",
            "ALTER TABLE rebate_requests ADD COLUMN IF NOT EXISTS rebate_rate NUMERIC(8, 4) NOT NULL DEFAULT 0",
            "ALTER TABLE rebate_requests ADD COLUMN IF NOT EXISTS rebate_amount NUMERIC(18, 6) NOT NULL DEFAULT 0",
            "ALTER TABLE rebate_requests ADD COLUMN IF NOT EXISTS reviewed_by BIGINT",
            "ALTER TABLE rebate_requests ADD COLUMN IF NOT EXISTS ledger_id BIGINT",
        ):
            await self._pool.execute(statement)

    async def ensure_futures_seeded(self) -> None:
        await self._upsert_worldcup_champion_market()
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

    async def _upsert_worldcup_champion_market(self) -> None:
        legacy_id = await self._pool.fetchval(
            "SELECT id FROM futures_markets WHERE market_key = $1",
            WORLD_CUP_CHAMPION_LEGACY_KEY,
        )
        market_key = WORLD_CUP_CHAMPION_MARKET_KEY
        current_id = await self._pool.fetchval(
            "SELECT id FROM futures_markets WHERE market_key = $1",
            market_key,
        )
        if legacy_id and current_id and int(legacy_id) != int(current_id):
            await self._pool.execute("DELETE FROM futures_markets WHERE id = $1", legacy_id)
            legacy_id = None
        if legacy_id:
            await self._pool.execute(
                """
                UPDATE futures_markets
                SET market_key = $2,
                    title = $3,
                    description = '静态冠军赔率，管理员可后续手动更新。',
                    category = 'world_cup',
                    settlement_rule = '球队获得 2026 FIFA World Cup 冠军。',
                    source = 'manual',
                    display_order = 10,
                    status = 'open',
                    updated_at = NOW()
                WHERE id = $1
                """,
                legacy_id,
                market_key,
                WORLD_CUP_CHAMPION_TITLE,
            )
        else:
            await self._pool.execute(
                """
                INSERT INTO futures_markets (
                    market_key, title, description, category, settlement_rule, source, display_order, status, updated_at
                )
                VALUES ($1, $2, '静态冠军赔率，管理员可后续手动更新。', 'world_cup',
                        '球队获得 2026 FIFA World Cup 冠军。', 'manual', 10, 'open', NOW())
                ON CONFLICT (market_key) DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    category = EXCLUDED.category,
                    settlement_rule = EXCLUDED.settlement_rule,
                    source = EXCLUDED.source,
                    display_order = EXCLUDED.display_order,
                    status = EXCLUDED.status,
                    updated_at = NOW()
                """,
                market_key,
                WORLD_CUP_CHAMPION_TITLE,
            )
        market_id = await self._pool.fetchval("SELECT id FROM futures_markets WHERE market_key = $1", market_key)
        for index, item in enumerate(WORLD_CUP_CHAMPION_ODDS, start=1):
            team = str(item["team"])
            await self._pool.execute(
                """
                INSERT INTO futures_options (
                    market_id, option_key, label, odds, status, display_order, metadata_json, updated_at
                )
                VALUES ($1, $2, $3, $4, 'active', $5, $6::jsonb, NOW())
                ON CONFLICT (market_id, option_key) DO UPDATE SET
                    label = EXCLUDED.label,
                    odds = EXCLUDED.odds,
                    status = 'active',
                    display_order = EXCLUDED.display_order,
                    metadata_json = EXCLUDED.metadata_json,
                    updated_at = NOW()
                """,
                market_id,
                team.lower().replace(" ", "_").replace("-", "_"),
                champion_option_label(team),
                item["odds"],
                index,
                json.dumps(champion_option_metadata(item), ensure_ascii=False),
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
            ON CONFLICT (market_key) DO UPDATE SET
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                category = EXCLUDED.category,
                settlement_rule = EXCLUDED.settlement_rule,
                display_order = EXCLUDED.display_order,
                updated_at = NOW()
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
                ON CONFLICT (market_id, option_key) DO UPDATE SET
                    label = EXCLUDED.label,
                    odds = EXCLUDED.odds,
                    status = 'active',
                    display_order = EXCLUDED.display_order,
                    updated_at = NOW()
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
                o.display_order,
                o.metadata_json
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
                o.odds::TEXT AS odds,
                o.metadata_json
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

    async def list_user_bets(
        self,
        telegram_user_id: int,
        status_group: str = "pending",
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        if status_group == "settled":
            statuses = ("won", "lost", "cancelled", "void")
        else:
            statuses = ("pending", "manual_required")
        rows = await self._pool.fetch(
            """
            SELECT
                id, bet_no, fixture_id, fixture_label, league_name, home_team, away_team,
                fixture_start_time, market_key, market_title, selection,
                odds::TEXT AS odds, stake::TEXT AS stake, potential_payout::TEXT AS potential_payout,
                payout::TEXT AS payout, status, result_score, settlement_source, settlement_note,
                settled_at, bettable_status_at_submit, balance_frozen, is_simulated, created_at
            FROM bets
            WHERE COALESCE(user_id, telegram_user_id) = $1 AND status = ANY($2::TEXT[])
            ORDER BY created_at DESC
            LIMIT $3 OFFSET $4
            """,
            telegram_user_id,
            list(statuses),
            limit,
            offset,
        )
        return [dict(row) for row in rows]

    async def count_user_bets_by_group(self, telegram_user_id: int, status_group: str) -> int:
        statuses = ("won", "lost", "cancelled", "void") if status_group == "settled" else ("pending", "manual_required")
        return int(
            await self._pool.fetchval(
                """
                SELECT COUNT(*) FROM bets
                WHERE COALESCE(user_id, telegram_user_id) = $1 AND status = ANY($2::TEXT[])
                """,
                telegram_user_id,
                list(statuses),
            )
            or 0
        )

    async def get_user_bet_stats(self, telegram_user_id: int) -> dict:
        row = await self._pool.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'pending') AS pending_count,
                COUNT(*) FILTER (WHERE status = 'manual_required') AS manual_required_count,
                COUNT(*) FILTER (WHERE status IN ('won', 'lost', 'void', 'cancelled')) AS settled_count,
                COUNT(*) FILTER (WHERE COALESCE(is_simulated, TRUE) = FALSE) AS real_bet_count,
                COUNT(*) FILTER (WHERE COALESCE(is_simulated, TRUE) = TRUE) AS simulated_bet_count,
                COUNT(*) FILTER (WHERE status = 'pending' AND COALESCE(is_simulated, TRUE) = TRUE) AS simulated_pending_count
            FROM bets
            WHERE COALESCE(user_id, telegram_user_id) = $1
            """,
            telegram_user_id,
        )
        return dict(row) if row else {
            "pending_count": 0,
            "manual_required_count": 0,
            "settled_count": 0,
            "real_bet_count": 0,
            "simulated_bet_count": 0,
            "simulated_pending_count": 0,
        }

    async def count_user_pending_bets(self, telegram_user_id: int) -> int:
        return int(
            await self._pool.fetchval(
                "SELECT COUNT(*) FROM bets WHERE COALESCE(user_id, telegram_user_id) = $1 AND status IN ('pending', 'manual_required')",
                telegram_user_id,
            )
            or 0
        )

    async def get_bet(self, bet_id: int | str) -> dict | None:
        if isinstance(bet_id, str):
            bet_id = _clean_lookup_token(bet_id)
        if isinstance(bet_id, str) and not bet_id.isdigit():
            return await self.get_bet_by_no(bet_id)
        row = await self._pool.fetchrow(
            """
            SELECT b.*, b.odds::TEXT AS odds, b.stake::TEXT AS stake,
                   b.potential_payout::TEXT AS potential_payout, b.payout::TEXT AS payout,
                   pf.id AS payout_freeze_id,
                   pf.amount::TEXT AS payout_freeze_amount,
                   pf.status AS payout_freeze_status,
                   pf.unlock_at AS payout_freeze_unlock_at,
                   pf.unlocked_at AS payout_freeze_unlocked_at,
                   pf.note AS payout_freeze_note
            FROM bets b
            LEFT JOIN LATERAL (
                SELECT *
                FROM payout_freezes
                WHERE bet_id = b.id
                ORDER BY CASE WHEN status = 'frozen' THEN 0 ELSE 1 END, id DESC
                LIMIT 1
            ) pf ON TRUE
            WHERE b.id = $1
            """,
            int(bet_id),
        )
        if not row and isinstance(bet_id, str):
            return await self.get_bet_by_no(bet_id)
        return dict(row) if row else None

    async def get_bet_by_no(self, bet_no: str) -> dict | None:
        bet_no = _clean_lookup_token(bet_no)
        row = await self._pool.fetchrow(
            """
            SELECT b.*, b.odds::TEXT AS odds, b.stake::TEXT AS stake,
                   b.potential_payout::TEXT AS potential_payout, b.payout::TEXT AS payout,
                   pf.id AS payout_freeze_id,
                   pf.amount::TEXT AS payout_freeze_amount,
                   pf.status AS payout_freeze_status,
                   pf.unlock_at AS payout_freeze_unlock_at,
                   pf.unlocked_at AS payout_freeze_unlocked_at,
                   pf.note AS payout_freeze_note
            FROM bets b
            LEFT JOIN LATERAL (
                SELECT *
                FROM payout_freezes
                WHERE bet_id = b.id
                ORDER BY CASE WHEN status = 'frozen' THEN 0 ELSE 1 END, id DESC
                LIMIT 1
            ) pf ON TRUE
            WHERE upper(b.bet_no) = upper($1)
            """,
            bet_no,
        )
        return dict(row) if row else None

    async def get_user_bet(self, telegram_user_id: int, bet_id_or_no: str) -> dict | None:
        bet_id_or_no = _clean_lookup_token(bet_id_or_no)
        if bet_id_or_no.isdigit():
            where = "id = $2"
            value: int | str = int(bet_id_or_no)
        else:
            where = "upper(bet_no) = upper($2)"
            value = bet_id_or_no
        row = await self._pool.fetchrow(
            f"""
            SELECT *, odds::TEXT AS odds, stake::TEXT AS stake, potential_payout::TEXT AS potential_payout,
                   payout::TEXT AS payout
            FROM bets
            WHERE COALESCE(user_id, telegram_user_id) = $1 AND {where}
            """,
            telegram_user_id,
            value,
        )
        return dict(row) if row else None

    async def clear_user_test_bets(self, telegram_user_id: int) -> int:
        result = await self._pool.execute(
            """
            UPDATE bets
            SET status = 'cancelled',
                settlement_source = 'admin',
                settlement_note = 'cleared simulated test bet',
                settled_at = COALESCE(settled_at, NOW()),
                updated_at = NOW()
            WHERE COALESCE(user_id, telegram_user_id) = $1
              AND COALESCE(is_simulated, TRUE) = TRUE
              AND status <> 'cancelled'
            """,
            telegram_user_id,
        )
        return _command_count(result)

    async def list_admin_bets(self, status: str = "pending", limit: int = 20) -> list[dict]:
        statuses = ("pending", "manual_required") if status == "pending" else (status,)
        rows = await self._pool.fetch(
            """
            SELECT id, bet_no, user_id, telegram_user_id, fixture_label, selection, status,
                   odds::TEXT AS odds, stake::TEXT AS stake, potential_payout::TEXT AS potential_payout
            FROM bets
            WHERE status = ANY($1::TEXT[])
            ORDER BY created_at DESC
            LIMIT $2
            """,
            list(statuses),
            limit,
        )
        return [dict(row) for row in rows]

    async def create_cancel_request(self, user_id: int, bet_id: int, reason: str) -> dict | None:
        row = await self._pool.fetchrow(
            """
            INSERT INTO cancel_requests (user_id, bet_id, status, reason)
            VALUES ($1, $2, 'pending', $3)
            ON CONFLICT (bet_id) WHERE status = 'pending'
            DO UPDATE SET reason = EXCLUDED.reason
            RETURNING *
            """,
            user_id,
            bet_id,
            reason,
        )
        return dict(row) if row else None

    async def list_cancel_requests(self, status: str = "pending", limit: int = 50) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT cr.*, b.bet_no, b.fixture_label, b.stake::TEXT AS stake, b.status AS bet_status
            FROM cancel_requests cr
            JOIN bets b ON b.id = cr.bet_id
            WHERE cr.status = $1
            ORDER BY cr.created_at DESC
            LIMIT $2
            """,
            status,
            limit,
        )
        return [dict(row) for row in rows]

    async def get_cancel_request(self, request_id: int) -> dict | None:
        row = await self._pool.fetchrow(
            """
            SELECT cr.*, b.bet_no, b.status AS bet_status
            FROM cancel_requests cr
            JOIN bets b ON b.id = cr.bet_id
            WHERE cr.id = $1
            """,
            request_id,
        )
        return dict(row) if row else None

    async def review_cancel_request(
        self,
        request_id: int,
        status: str,
        admin_user_id: int,
        reason: str,
    ) -> dict | None:
        row = await self._pool.fetchrow(
            """
            UPDATE cancel_requests
            SET status = $2,
                admin_id = $3,
                admin_reason = $4,
                reviewed_at = NOW()
            WHERE id = $1 AND status = 'pending'
            RETURNING *
            """,
            request_id,
            status,
            admin_user_id,
            reason,
        )
        return dict(row) if row else None

    async def list_pending_bets_for_settlement(self, limit: int = 200) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT *, odds::TEXT AS odds, stake::TEXT AS stake, potential_payout::TEXT AS potential_payout
            FROM bets
            WHERE status = 'pending'
            ORDER BY fixture_start_time NULLS FIRST, created_at
            LIMIT $1
            """,
            limit,
        )
        return [dict(row) for row in rows]

    async def list_withdraw_requests(self, status: str | None = None, limit: int = 20) -> list[dict]:
        if status:
            rows = await self._pool.fetch(
                "SELECT * FROM withdraw_requests WHERE status = $1 ORDER BY created_at DESC LIMIT $2",
                status,
                limit,
            )
        else:
            rows = await self._pool.fetch("SELECT * FROM withdraw_requests ORDER BY created_at DESC LIMIT $1", limit)
        return [dict(row) for row in rows]

    async def get_withdraw_request(self, withdraw_id: int) -> dict | None:
        row = await self._pool.fetchrow("SELECT * FROM withdraw_requests WHERE id = $1", withdraw_id)
        return dict(row) if row else None

    async def list_pending_withdrawals(self, limit: int = 10) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT id, user_id, amount, network, address, status, created_at
            FROM withdraw_requests
            WHERE status = 'pending'
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
        return [dict(row) for row in rows]

    async def get_withdraw_review_context(self, withdraw_id: int) -> dict | None:
        withdraw = await self._pool.fetchrow(
            """
            SELECT id, user_id, amount, network, address, status, admin_id, admin_note,
                   created_at, reviewed_at, paid_at
            FROM withdraw_requests
            WHERE id = $1
            """,
            withdraw_id,
        )
        if not withdraw:
            return None
        user_id = int(withdraw["user_id"])
        user = await self._pool.fetchrow(
            """
            SELECT telegram_user_id, username, first_name, last_name, created_at, status,
                   bet_restricted, withdraw_restricted, risk_note
            FROM users
            WHERE telegram_user_id = $1
            """,
            user_id,
        )
        wallet = await self._pool.fetchrow(
            """
            SELECT user_id, telegram_user_id, currency, balance, frozen_balance,
                   total_deposit, total_withdraw, created_at, updated_at
            FROM wallets
            WHERE user_id = $1
            ORDER BY id DESC
            LIMIT 1
            """,
            user_id,
        )
        ledger_summary = await self._pool.fetchrow(
            """
            SELECT
                COALESCE(SUM(amount) FILTER (WHERE type IN ('deposit', 'deposit_manual')), 0) AS total_deposit,
                COALESCE((SELECT SUM(amount) FROM withdraw_requests WHERE user_id = $1), 0) AS total_withdraw_request,
                COALESCE(SUM(amount) FILTER (WHERE type = 'manual_adjust'), 0) AS total_manual_adjust,
                COUNT(*) AS ledger_count
            FROM wallet_ledger
            WHERE user_id = $1
            """,
            user_id,
        )
        bet_summary = await self._pool.fetchrow(
            """
            SELECT
                COALESCE(SUM(stake), 0) AS total_stake,
                COUNT(*) AS bet_count,
                COUNT(*) FILTER (WHERE status = 'won') AS won_count,
                COUNT(*) FILTER (WHERE status = 'lost') AS lost_count,
                COUNT(*) FILTER (WHERE status IN ('void', 'cancelled')) AS void_count,
                COALESCE(SUM(payout), 0) AS total_payout
            FROM bets
            WHERE COALESCE(user_id, telegram_user_id) = $1
            """,
            user_id,
        )
        recent_ledgers = await self._pool.fetch(
            """
            SELECT type, amount, balance_before, balance_after, frozen_before, frozen_after,
                   ref_type, ref_id, created_at
            FROM wallet_ledger
            WHERE user_id = $1
            ORDER BY created_at DESC, id DESC
            LIMIT 5
            """,
            user_id,
        )
        recent_bets = await self._pool.fetch(
            """
            SELECT id, bet_no, status, stake, potential_payout, payout, created_at
            FROM bets
            WHERE COALESCE(user_id, telegram_user_id) = $1
            ORDER BY created_at DESC, id DESC
            LIMIT 5
            """,
            user_id,
        )
        return {
            "withdraw": dict(withdraw),
            "user": dict(user) if user else {},
            "wallet": dict(wallet) if wallet else {},
            "ledger_summary": dict(ledger_summary) if ledger_summary else {},
            "bet_summary": dict(bet_summary) if bet_summary else {},
            "recent_ledgers": [dict(row) for row in recent_ledgers],
            "recent_bets": [dict(row) for row in recent_bets],
        }

    async def list_rebate_rules(self) -> list[dict]:
        rows = await self._pool.fetch("SELECT * FROM rebate_rules ORDER BY mode, min_turnover, min_active_referrals, id")
        return [dict(row) for row in rows]

    async def list_rebate_records(self, user_id: int | None = None, limit: int = 20) -> list[dict]:
        if user_id is None:
            rows = await self._pool.fetch("SELECT * FROM rebate_records ORDER BY created_at DESC LIMIT $1", limit)
        else:
            rows = await self._pool.fetch(
                "SELECT * FROM rebate_records WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
                user_id,
                limit,
            )
        return [dict(row) for row in rows]

    async def admin_dashboard(self) -> dict:
        row = await self._pool.fetchrow(
            """
            SELECT
                COALESCE((SELECT SUM(actual_amount) FROM deposit_orders WHERE status = 'paid' AND paid_at >= CURRENT_DATE), 0) AS today_deposit,
                COALESCE((SELECT SUM(amount) FROM withdraw_requests WHERE created_at >= CURRENT_DATE), 0) AS today_withdraw_request,
                (SELECT COUNT(*) FROM bets WHERE status = 'pending') AS pending_bets,
                (SELECT COUNT(*) FROM withdraw_requests WHERE status = 'pending') AS pending_withdrawals,
                (SELECT COUNT(*) FROM commission_records WHERE status = 'pending') AS pending_commissions,
                (SELECT COUNT(*) FROM rebate_records WHERE status = 'pending') AS pending_rebates,
                (SELECT COUNT(*) FROM users) AS total_users,
                (SELECT COUNT(DISTINCT parent_user_id) FROM referral_relations) AS active_agents
            """
        )
        return dict(row)

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

    async def create_deposit_order(
        self,
        user_id: int,
        order_id: str,
        amount: Decimal,
        currency: str = "USDT",
        network: str | None = None,
    ) -> dict:
        row = await self._pool.fetchrow(
            """
            INSERT INTO deposit_orders (order_id, user_id, amount_requested, actual_amount, currency, network, status, updated_at)
            VALUES ($1, $2, $3, $3, $4, $5, 'pending', NOW())
            RETURNING *
            """,
            order_id,
            user_id,
            amount,
            currency,
            network,
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
        original_payment_url: str | None = None,
        final_payment_url: str | None = None,
        payment_url_check_status: str | None = None,
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
                original_payment_url = $9,
                final_payment_url = $10,
                payment_url_check_status = $11,
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
            original_payment_url or payment_url,
            final_payment_url or payment_url,
            payment_url_check_status,
        )
        return dict(row) if row else None

    async def fail_deposit_order(
        self,
        order_id: str,
        raw_response: dict[str, Any],
        *,
        error_message: str | None = None,
        payment_url_check_status: str | None = None,
    ) -> dict | None:
        row = await self._pool.fetchrow(
            """
            UPDATE deposit_orders
            SET status = 'failed',
                error_message = COALESCE($3, error_message),
                payment_url_check_status = COALESCE($4, payment_url_check_status),
                raw_response_json = $2::jsonb,
                updated_at = NOW()
            WHERE order_id = $1 AND status = 'pending'
            RETURNING *
            """,
            order_id,
            json.dumps(raw_response),
            error_message,
            payment_url_check_status,
        )
        return dict(row) if row else None

    async def mark_deposit_manual_review(
        self,
        order_id: str,
        *,
        note: str,
        callback_payload: dict[str, Any] | None = None,
        actual_amount: Decimal | None = None,
        trade_id: str | None = None,
        chain_tx_id: str | None = None,
        error_message: str | None = None,
    ) -> dict | None:
        row = await self._pool.fetchrow(
            """
            UPDATE deposit_orders
            SET status = 'manual_review',
                manual_review_required = TRUE,
                manual_review_note = $2,
                error_message = COALESCE($7, error_message),
                actual_amount = COALESCE($3, actual_amount),
                trade_id = COALESCE($4, trade_id),
                chain_tx_id = COALESCE($5, chain_tx_id),
                block_transaction_id = COALESCE($5, block_transaction_id),
                raw_callback_json = COALESCE($6::jsonb, raw_callback_json),
                updated_at = NOW()
            WHERE order_id = $1 AND status <> 'paid'
            RETURNING *
            """,
            order_id,
            note,
            actual_amount,
            trade_id,
            chain_tx_id,
            json.dumps(callback_payload) if callback_payload is not None else None,
            error_message,
        )
        return dict(row) if row else None

    async def reject_deposit_order(self, order_id: str, *, reason: str, admin_user_id: int) -> dict | None:
        row = await self._pool.fetchrow(
            """
            UPDATE deposit_orders
            SET status = 'failed',
                manual_review_required = FALSE,
                manual_review_note = $2,
                error_message = $2,
                updated_at = NOW()
            WHERE order_id = $1 AND status <> 'paid'
            RETURNING *
            """,
            order_id,
            reason,
        )
        if row:
            await self.add_admin_audit_log(
                admin_user_id,
                "admin_reject_deposit",
                "deposit_order",
                order_id,
                {"reason": reason, "status": "failed"},
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
                    SELECT COUNT(*)
                    FROM referral_relations r
                    WHERE r.parent_user_id = $1
                    AND (
                        EXISTS (
                            SELECT 1 FROM deposit_orders d
                            WHERE d.user_id = r.user_id AND d.status = 'paid'
                        )
                        OR EXISTS (
                            SELECT 1 FROM bets b
                            WHERE COALESCE(b.user_id, b.telegram_user_id) = r.user_id
                              AND b.status IN ('won', 'lost')
                        )
                    )
                ), 0) AS active_count,
                COALESCE((
                    SELECT SUM(d.actual_amount)
                    FROM deposit_orders d
                    JOIN referral_relations r ON r.user_id = d.user_id
                    WHERE r.parent_user_id = $1 AND d.status = 'paid'
                ), 0) AS total_deposit,
                COALESCE((
                    SELECT SUM(b.stake)
                    FROM bets b
                    JOIN referral_relations r ON r.user_id = COALESCE(b.user_id, b.telegram_user_id)
                    WHERE r.parent_user_id = $1 AND b.status IN ('won', 'lost')
                ), 0) AS total_turnover,
                COALESCE((SELECT SUM(amount) FROM commission_records WHERE user_id = $1 AND status = 'pending'), 0) AS pending_commission,
                COALESCE((SELECT SUM(amount) FROM commission_records WHERE user_id = $1 AND status = 'settled'), 0) AS settled_commission,
                COALESCE((SELECT SUM(rebate_amount) FROM rebate_records WHERE user_id = $1 AND status = 'pending'), 0) AS pending_rebate
            """,
            user_id,
        )
        return dict(row)

    async def check_referral_reward_after_bet(
        self,
        referee_user_id: int,
        threshold_amount: Decimal = Decimal("50"),
        reward_amount: Decimal = Decimal("8"),
    ) -> dict | None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                referrer_user_id = await conn.fetchval(
                    "SELECT parent_user_id FROM referral_relations WHERE user_id = $1",
                    referee_user_id,
                )
                if not referrer_user_id:
                    logger.info(
                        "referral_reward_check referrer_user_id=%s referee_user_id=%s valid_stake=%s threshold=%s result=no_referrer",
                        None,
                        referee_user_id,
                        0,
                        threshold_amount,
                    )
                    return None
                referrer_user_id = int(referrer_user_id)
                reward = await conn.fetchrow(
                    """
                    INSERT INTO referral_rewards (
                        referrer_user_id, referee_user_id, threshold_amount, reward_amount
                    )
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (referrer_user_id, referee_user_id) DO UPDATE SET
                        referrer_user_id = EXCLUDED.referrer_user_id
                    RETURNING *
                    """,
                    referrer_user_id,
                    referee_user_id,
                    threshold_amount,
                    reward_amount,
                )
                if not reward or str(reward["status"]) == "rewarded":
                    logger.info(
                        "referral_reward_check referrer_user_id=%s referee_user_id=%s valid_stake=%s threshold=%s result=already_rewarded",
                        referrer_user_id,
                        referee_user_id,
                        reward["referee_valid_stake"] if reward else 0,
                        threshold_amount,
                    )
                    return None
                valid_stake = Decimal(
                    str(
                        await conn.fetchval(
                            """
                            SELECT COALESCE(SUM(stake), 0)
                            FROM bets
                            WHERE COALESCE(user_id, telegram_user_id) = $1
                              AND COALESCE(is_simulated, TRUE) = FALSE
                              AND status NOT IN ('void', 'cancelled', 'refunded')
                            """,
                            referee_user_id,
                        )
                        or 0
                    )
                )
                await conn.execute(
                    """
                    UPDATE referral_rewards
                    SET referee_valid_stake = $3
                    WHERE referrer_user_id = $1 AND referee_user_id = $2
                    """,
                    referrer_user_id,
                    referee_user_id,
                    valid_stake,
                )
                if valid_stake < Decimal(str(reward["threshold_amount"])):
                    logger.info(
                        "referral_reward_check referrer_user_id=%s referee_user_id=%s valid_stake=%s threshold=%s result=pending",
                        referrer_user_id,
                        referee_user_id,
                        valid_stake,
                        reward["threshold_amount"],
                    )
                    return None
                wallet = await conn.fetchrow(
                    """
                    INSERT INTO wallets (user_id, telegram_user_id, currency, balance, frozen_balance, updated_at)
                    VALUES ($1, $1, 'USDT', 0, 0, NOW())
                    ON CONFLICT (user_id, currency) DO UPDATE SET updated_at = NOW()
                    RETURNING *
                    """,
                    referrer_user_id,
                )
                balance_before = Decimal(str(wallet["balance"]))
                frozen_before = Decimal(str(wallet["frozen_balance"]))
                amount = Decimal(str(reward["reward_amount"]))
                balance_after = balance_before + amount
                ref_id = f"{referrer_user_id}:{referee_user_id}:{Decimal(str(reward['threshold_amount'])).normalize()}"
                ledger = await conn.fetchrow(
                    """
                    INSERT INTO wallet_ledger (
                        user_id, currency, type, amount, balance_before, balance_after,
                        frozen_before, frozen_after, ref_type, ref_id, description
                    )
                    VALUES ($1, 'USDT', 'referral_reward', $2, $3, $4, $5, $5,
                            'referral_threshold', $6, 'Referral threshold reward')
                    ON CONFLICT (ref_type, ref_id, type)
                    WHERE ref_type IS NOT NULL AND ref_id IS NOT NULL
                    DO NOTHING
                    RETURNING *
                    """,
                    referrer_user_id,
                    amount,
                    balance_before,
                    balance_after,
                    frozen_before,
                    ref_id,
                )
                if not ledger:
                    logger.info(
                        "referral_reward_check referrer_user_id=%s referee_user_id=%s valid_stake=%s threshold=%s result=duplicate_ledger",
                        referrer_user_id,
                        referee_user_id,
                        valid_stake,
                        reward["threshold_amount"],
                    )
                    return None
                await conn.execute(
                    """
                    UPDATE wallets
                    SET balance = $3, updated_at = NOW()
                    WHERE user_id = $1 AND currency = $2
                    """,
                    referrer_user_id,
                    "USDT",
                    balance_after,
                )
                row = await conn.fetchrow(
                    """
                    UPDATE referral_rewards
                    SET status = 'rewarded',
                        rewarded_ledger_id = $3,
                        rewarded_at = NOW(),
                        referee_valid_stake = $4
                    WHERE referrer_user_id = $1
                      AND referee_user_id = $2
                      AND status <> 'rewarded'
                    RETURNING *
                    """,
                    referrer_user_id,
                    referee_user_id,
                    int(ledger["id"]),
                    valid_stake,
                )
                logger.info(
                    "referral_reward_paid referrer_user_id=%s referee_user_id=%s reward_amount=%s ledger_id=%s",
                    referrer_user_id,
                    referee_user_id,
                    amount,
                    ledger["id"],
                )
                return dict(row) if row else None

    async def get_referral_reward_summary(self, user_id: int) -> dict:
        row = await self._pool.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'rewarded') AS rewarded_count,
                COALESCE(SUM(reward_amount) FILTER (WHERE status = 'rewarded'), 0) AS rewarded_amount
            FROM referral_rewards
            WHERE referrer_user_id = $1
            """,
            user_id,
        )
        return dict(row) if row else {"rewarded_count": 0, "rewarded_amount": 0}

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
            SELECT
                r.user_id,
                u.username,
                u.first_name,
                r.created_at,
                COALESCE(d.total_deposit, 0) AS total_deposit,
                COALESCE(b.total_turnover, 0) AS total_turnover,
                (COALESCE(d.total_deposit, 0) > 0 OR COALESCE(b.total_turnover, 0) > 0) AS is_active
            FROM referral_relations r
            LEFT JOIN users u ON u.telegram_user_id = r.user_id
            LEFT JOIN (
                SELECT user_id, SUM(actual_amount) AS total_deposit
                FROM deposit_orders
                WHERE status = 'paid'
                GROUP BY user_id
            ) d ON d.user_id = r.user_id
            LEFT JOIN (
                SELECT COALESCE(user_id, telegram_user_id) AS user_id, SUM(stake) AS total_turnover
                FROM bets
                WHERE status IN ('won', 'lost')
                GROUP BY COALESCE(user_id, telegram_user_id)
            ) b ON b.user_id = r.user_id
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

    async def get_user_role_row(self, user_id: int) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM user_roles WHERE user_id = $1 AND status = 'active'",
            user_id,
        )
        return dict(row) if row else None

    async def set_user_role(self, user_id: int, role: str, invited_by_user_id: int | None) -> dict:
        row = await self._pool.fetchrow(
            """
            INSERT INTO user_roles (user_id, role, invited_by_user_id, status, updated_at)
            VALUES ($1, $2, $3, 'active', NOW())
            ON CONFLICT (user_id)
            DO UPDATE SET role = EXCLUDED.role,
                          invited_by_user_id = EXCLUDED.invited_by_user_id,
                          status = 'active',
                          updated_at = NOW()
            RETURNING *
            """,
            user_id,
            role,
            invited_by_user_id,
        )
        return dict(row)

    async def remove_user_role(self, user_id: int) -> dict | None:
        row = await self._pool.fetchrow(
            """
            UPDATE user_roles
            SET role = 'user', status = 'suspended', updated_at = NOW()
            WHERE user_id = $1
            RETURNING *
            """,
            user_id,
        )
        return dict(row) if row else None

    async def list_users(self, limit: int = 50) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT u.telegram_user_id, u.username, u.first_name, u.created_at,
                   COALESCE(r.role, 'user') AS role,
                   COALESCE(w.balance, 0)::TEXT AS balance,
                   COALESCE(w.frozen_balance, 0)::TEXT AS frozen_balance
            FROM users u
            LEFT JOIN user_roles r ON r.user_id = u.telegram_user_id AND r.status = 'active'
            LEFT JOIN wallets w ON w.user_id = u.telegram_user_id AND w.currency = 'USDT'
            ORDER BY u.created_at DESC
            LIMIT $1
            """,
            limit,
        )
        return [dict(row) for row in rows]

    async def get_user_admin_view(self, user_id: int) -> dict | None:
        row = await self._pool.fetchrow(
            """
            SELECT u.telegram_user_id, u.username, u.first_name, u.created_at,
                   COALESCE(r.role, 'user') AS role,
                   COALESCE(w.balance, 0)::TEXT AS balance,
                   COALESCE(w.frozen_balance, 0)::TEXT AS frozen_balance,
                   (SELECT COUNT(*) FROM referral_relations WHERE parent_user_id = $1) AS direct_referrals,
                   (SELECT COUNT(*) FROM bets WHERE COALESCE(user_id, telegram_user_id) = $1) AS bets_count
            FROM users u
            LEFT JOIN user_roles r ON r.user_id = u.telegram_user_id AND r.status = 'active'
            LEFT JOIN wallets w ON w.user_id = u.telegram_user_id AND w.currency = 'USDT'
            WHERE u.telegram_user_id = $1
            """,
            user_id,
        )
        return dict(row) if row else None

    async def create_agent_application(
        self,
        user_id: int,
        total_deposit: Decimal,
        total_turnover: Decimal,
        valid_referrals: int,
        note: str | None = None,
    ) -> dict:
        row = await self._pool.fetchrow(
            """
            INSERT INTO agent_applications (
                user_id, status, total_deposit, total_turnover, valid_referrals, note
            )
            VALUES ($1, 'pending', $2, $3, $4, $5)
            RETURNING *
            """,
            user_id,
            total_deposit,
            total_turnover,
            valid_referrals,
            note,
        )
        return dict(row)

    async def get_agent_application_metrics(self, user_id: int) -> dict:
        row = await self._pool.fetchrow(
            """
            SELECT
                COALESCE((SELECT total_deposit FROM wallets WHERE user_id = $1 AND currency = 'USDT'), 0) AS total_deposit,
                COALESCE((
                    SELECT SUM(stake)
                    FROM bets
                    WHERE COALESCE(user_id, telegram_user_id) = $1
                      AND status IN ('pending', 'manual_required', 'won', 'lost')
                ), 0) AS total_turnover,
                COALESCE((
                    SELECT COUNT(*)
                    FROM referral_relations r
                    WHERE r.parent_user_id = $1
                      AND (
                        EXISTS (SELECT 1 FROM deposit_orders d WHERE d.user_id = r.user_id AND d.status = 'paid')
                        OR EXISTS (
                            SELECT 1 FROM bets b
                            WHERE COALESCE(b.user_id, b.telegram_user_id) = r.user_id
                              AND b.status IN ('pending', 'manual_required', 'won', 'lost')
                        )
                      )
                ), 0) AS valid_referrals
            """,
            user_id,
        )
        return dict(row)

    async def list_agent_applications(self, status: str = "pending", limit: int = 50) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT *
            FROM agent_applications
            WHERE status = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            status,
            limit,
        )
        return [dict(row) for row in rows]

    async def get_latest_agent_application(self, user_id: int) -> dict | None:
        row = await self._pool.fetchrow(
            """
            SELECT *
            FROM agent_applications
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            user_id,
        )
        return dict(row) if row else None

    async def review_agent_application(
        self,
        application_id: int,
        status: str,
        reviewed_by: int,
        note: str | None = None,
    ) -> dict | None:
        row = await self._pool.fetchrow(
            """
            UPDATE agent_applications
            SET status = $2, reviewed_by = $3, note = COALESCE($4, note), reviewed_at = NOW()
            WHERE id = $1 AND status = 'pending'
            RETURNING *
            """,
            application_id,
            status,
            reviewed_by,
            note,
        )
        return dict(row) if row else None

    async def create_rebate_request(
        self,
        user_id: int,
        requested_to_user_id: int | None,
        turnover: Decimal,
        active_referrals: int,
        requested_amount: Decimal = Decimal("0"),
        note: str | None = None,
    ) -> dict:
        row = await self._pool.fetchrow(
            """
            INSERT INTO rebate_requests (
                user_id, requested_to_user_id, period_start, period_end,
                turnover, active_referrals, requested_amount, status, note
            )
            VALUES ($1, $2, NOW() - INTERVAL '7 days', NOW(), $3, $4, $5, 'pending', $6)
            RETURNING *
            """,
            user_id,
            requested_to_user_id,
            turnover,
            active_referrals,
            requested_amount,
            note,
        )
        return dict(row)

    async def list_rebate_requests(self, user_id: int | None = None, limit: int = 50, status: str | None = None) -> list[dict]:
        if user_id is None and status is None:
            rows = await self._pool.fetch(
                "SELECT * FROM rebate_requests ORDER BY created_at DESC LIMIT $1",
                limit,
            )
        elif user_id is None:
            rows = await self._pool.fetch(
                "SELECT * FROM rebate_requests WHERE status = $1 ORDER BY created_at DESC LIMIT $2",
                status,
                limit,
            )
        elif status is None:
            rows = await self._pool.fetch(
                "SELECT * FROM rebate_requests WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
                user_id,
                limit,
            )
        else:
            rows = await self._pool.fetch(
                "SELECT * FROM rebate_requests WHERE user_id = $1 AND status = $2 ORDER BY created_at DESC LIMIT $3",
                user_id,
                status,
                limit,
            )
        return [dict(row) for row in rows]

    async def get_rebate_request(self, request_id: int) -> dict | None:
        row = await self._pool.fetchrow("SELECT * FROM rebate_requests WHERE id = $1", request_id)
        return dict(row) if row else None

    async def update_rebate_request_status(
        self,
        request_id: int,
        status: str,
        *,
        approved_amount: Decimal | None = None,
        reason: str | None = None,
    ) -> dict | None:
        row = await self._pool.fetchrow(
            """
            UPDATE rebate_requests
            SET status = $2,
                approved_amount = COALESCE($3, approved_amount),
                review_reason = COALESCE($4, review_reason),
                reviewed_at = NOW()
            WHERE id = $1
              AND status = ANY($5::TEXT[])
            RETURNING *
            """,
            request_id,
            status,
            approved_amount,
            reason,
            ["pending"] if status in {"approved", "rejected"} else ["approved"],
        )
        return dict(row) if row else None

    async def mark_rebate_request_paid(self, request_id: int) -> dict | None:
        row = await self._pool.fetchrow(
            """
            UPDATE rebate_requests
            SET status = 'paid', paid_at = NOW()
            WHERE id = $1 AND status = 'approved'
            RETURNING *
            """,
            request_id,
        )
        return dict(row) if row else None

    async def get_or_create_admin_profile(self, user_id: int, role: str = "agent") -> dict:
        row = await self._pool.fetchrow(
            """
            INSERT INTO admin_profiles (user_id, role)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET updated_at = NOW()
            RETURNING *
            """,
            user_id,
            role,
        )
        return dict(row)

    async def set_admin_rebate_rate(self, user_id: int, rate: Decimal, operator_id: int | None = None) -> dict:
        old = await self.get_or_create_admin_profile(user_id)
        row = await self._pool.fetchrow(
            """
            INSERT INTO admin_profiles (user_id, role, rebate_rate, updated_at)
            VALUES ($1, 'agent', $2, NOW())
            ON CONFLICT (user_id) DO UPDATE SET rebate_rate = EXCLUDED.rebate_rate, updated_at = NOW()
            RETURNING *
            """,
            user_id,
            rate,
        )
        logger.info(
            "admin_set_rebate_rate operator_id=%s target_user_id=%s old_rate=%s new_rate=%s",
            operator_id,
            user_id,
            old.get("rebate_rate"),
            rate,
        )
        return dict(row)

    async def toggle_admin_rebate(self, user_id: int) -> dict:
        await self.get_or_create_admin_profile(user_id)
        row = await self._pool.fetchrow(
            """
            UPDATE admin_profiles
            SET rebate_enabled = NOT rebate_enabled,
                updated_at = NOW()
            WHERE user_id = $1
            RETURNING *
            """,
            user_id,
        )
        return dict(row)

    async def list_admin_agent_profiles(self, limit: int = 50) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT
                p.user_id,
                p.role,
                p.rebate_enabled,
                p.rebate_rate::TEXT AS rebate_rate,
                p.settled_rebate_stake::TEXT AS settled_rebate_stake,
                COALESCE(w.balance, 0)::TEXT AS balance,
                COALESCE(w.total_deposit, 0)::TEXT AS total_deposit,
                COALESCE(b.total_stake, 0)::TEXT AS total_stake,
                u.username,
                u.first_name
            FROM admin_profiles p
            LEFT JOIN wallets w ON w.user_id = p.user_id AND w.currency = 'USDT'
            LEFT JOIN users u ON u.telegram_user_id = p.user_id
            LEFT JOIN (
                SELECT COALESCE(user_id, telegram_user_id) AS user_id, SUM(stake) AS total_stake
                FROM bets
                WHERE COALESCE(is_simulated, TRUE) = FALSE
                  AND status IN ('won', 'lost', 'settled', 'settled_win', 'settled_loss')
                GROUP BY COALESCE(user_id, telegram_user_id)
            ) b ON b.user_id = p.user_id
            WHERE p.role IN ('admin', 'agent')
            ORDER BY p.updated_at DESC, p.user_id
            LIMIT $1
            """,
            limit,
        )
        return [dict(row) for row in rows]

    async def get_agent_rebate_snapshot(self, user_id: int) -> dict:
        profile = await self.get_or_create_admin_profile(user_id)
        row = await self._pool.fetchrow(
            """
            SELECT COALESCE(SUM(stake), 0) AS valid_stake
            FROM bets
            WHERE COALESCE(user_id, telegram_user_id) = $1
              AND COALESCE(is_simulated, TRUE) = FALSE
              AND status IN ('won', 'lost', 'settled', 'settled_win', 'settled_loss')
            """,
            user_id,
        )
        data = dict(profile)
        data["valid_stake"] = Decimal(str((row or {}).get("valid_stake") or 0))
        settled_stake = Decimal(str(profile.get("settled_rebate_stake") or 0))
        rebate_rate = Decimal(str(profile.get("rebate_rate") or 0))
        claimable_stake = max(data["valid_stake"] - settled_stake, Decimal("0"))
        data["claimable_stake"] = claimable_stake
        data["claimable_rebate"] = (claimable_stake * rebate_rate).quantize(Decimal("0.000001"))
        data["total_valid_stake"] = data["valid_stake"]
        data["settled_rebate_stake"] = settled_stake
        data["available_rebate_stake"] = claimable_stake
        data["estimated_rebate_amount"] = data["claimable_rebate"]
        return data

    async def get_agent_rebate_summary(self, user_id: int) -> dict:
        return await self.get_agent_rebate_snapshot(user_id)

    async def create_agent_rebate_request(self, user_id: int, note: str = "agent rebate request") -> dict | None:
        snapshot = await self.get_agent_rebate_snapshot(user_id)
        if not bool(snapshot.get("rebate_enabled")):
            return None
        stake_amount = Decimal(str(snapshot.get("claimable_stake") or 0))
        rebate_amount = Decimal(str(snapshot.get("claimable_rebate") or 0))
        if stake_amount <= 0 or rebate_amount <= 0:
            return None
        existing = await self._pool.fetchrow(
            """
            SELECT *
            FROM rebate_requests
            WHERE user_id = $1 AND status = 'pending'
            ORDER BY id DESC
            LIMIT 1
            """,
            user_id,
        )
        if existing:
            return dict(existing)
        row = await self._pool.fetchrow(
            """
            INSERT INTO rebate_requests (
                user_id, turnover, requested_amount, stake_amount, rebate_rate, rebate_amount, status, note
            )
            VALUES ($1, $2, $3, $2, $4, $3, 'pending', $5)
            RETURNING *
            """,
            user_id,
            stake_amount,
            rebate_amount,
            Decimal(str(snapshot.get("rebate_rate") or 0)),
            note,
        )
        if row:
            logger.info(
                "rebate_request_created request_id=%s user_id=%s stake_amount=%s rebate_rate=%s rebate_amount=%s",
                row["id"],
                user_id,
                stake_amount,
                snapshot.get("rebate_rate"),
                rebate_amount,
            )
        return dict(row) if row else None

    async def approve_agent_rebate_request(self, request_id: int, reviewer_id: int) -> dict | None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                request = await conn.fetchrow("SELECT * FROM rebate_requests WHERE id = $1 FOR UPDATE", request_id)
                if not request or str(request["status"]) != "pending":
                    return None
                user_id = int(request["user_id"])
                amount = Decimal(str(request["rebate_amount"] or request["requested_amount"] or 0))
                stake_amount = Decimal(str(request["stake_amount"] or request["turnover"] or 0))
                profile = await conn.fetchrow(
                    """
                    INSERT INTO admin_profiles (user_id)
                    VALUES ($1)
                    ON CONFLICT (user_id) DO UPDATE SET updated_at = NOW()
                    RETURNING settled_rebate_stake
                    """,
                    user_id,
                )
                total_valid_stake = Decimal(
                    str(
                        await conn.fetchval(
                            """
                            SELECT COALESCE(SUM(stake), 0)
                            FROM bets
                            WHERE COALESCE(user_id, telegram_user_id) = $1
                              AND COALESCE(is_simulated, TRUE) = FALSE
                              AND status IN ('won', 'lost', 'settled', 'settled_win', 'settled_loss')
                            """,
                            user_id,
                        )
                        or 0
                    )
                )
                settled_stake = Decimal(str(profile["settled_rebate_stake"] or 0)) if profile else Decimal("0")
                if stake_amount <= 0 or total_valid_stake - settled_stake < stake_amount:
                    return None
                wallet = await conn.fetchrow(
                    """
                    INSERT INTO wallets (user_id, telegram_user_id, currency, balance, frozen_balance, updated_at)
                    VALUES ($1, $1, 'USDT', 0, 0, NOW())
                    ON CONFLICT (user_id, currency) DO UPDATE SET updated_at = NOW()
                    RETURNING *
                    """,
                    user_id,
                )
                balance_before = Decimal(str(wallet["balance"]))
                frozen_before = Decimal(str(wallet["frozen_balance"]))
                balance_after = balance_before + amount
                ledger = await conn.fetchrow(
                    """
                    INSERT INTO wallet_ledger (
                        user_id, currency, type, amount, balance_before, balance_after,
                        frozen_before, frozen_after, ref_type, ref_id, description
                    )
                    VALUES ($1, 'USDT', 'agent_rebate', $2, $3, $4, $5, $5,
                            'rebate_request', $6, 'Agent rebate request payout')
                    ON CONFLICT (ref_type, ref_id, type)
                    WHERE ref_type IS NOT NULL AND ref_id IS NOT NULL
                    DO NOTHING
                    RETURNING *
                    """,
                    user_id,
                    amount,
                    balance_before,
                    balance_after,
                    frozen_before,
                    str(request_id),
                )
                if not ledger:
                    return None
                await conn.execute(
                    "UPDATE wallets SET balance = $3, updated_at = NOW() WHERE user_id = $1 AND currency = $2",
                    user_id,
                    "USDT",
                    balance_after,
                )
                await conn.execute(
                    """
                    INSERT INTO admin_profiles (user_id, settled_rebate_stake)
                    VALUES ($1, $2)
                    ON CONFLICT (user_id) DO UPDATE SET
                        settled_rebate_stake = admin_profiles.settled_rebate_stake + EXCLUDED.settled_rebate_stake,
                        updated_at = NOW()
                    """,
                    user_id,
                    stake_amount,
                )
                row = await conn.fetchrow(
                    """
                    UPDATE rebate_requests
                    SET status = 'approved',
                        reviewed_by = $2,
                        reviewed_at = NOW(),
                        approved_amount = $3,
                        ledger_id = $4,
                        paid_at = NOW()
                    WHERE id = $1 AND status = 'pending'
                    RETURNING *
                    """,
                    request_id,
                    reviewer_id,
                    amount,
                    int(ledger["id"]),
                )
                logger.info(
                    "admin_approve_rebate operator_id=%s request_id=%s user_id=%s amount=%s ledger_id=%s result=approved",
                    reviewer_id,
                    request_id,
                    user_id,
                    amount,
                    ledger["id"],
                )
                return dict(row) if row else None

    async def reject_agent_rebate_request(self, request_id: int, reviewer_id: int, reason: str = "") -> dict | None:
        row = await self._pool.fetchrow(
            """
            UPDATE rebate_requests
            SET status = 'rejected',
                reviewed_by = $2,
                reviewed_at = NOW(),
                review_reason = $3,
                note = COALESCE(NULLIF($3, ''), note)
            WHERE id = $1 AND status = 'pending'
            RETURNING *
            """,
            request_id,
            reviewer_id,
            reason,
        )
        if row:
            logger.info(
                "admin_reject_rebate operator_id=%s request_id=%s user_id=%s reason=%s result=rejected",
                reviewer_id,
                request_id,
                row["user_id"],
                reason,
            )
        return dict(row) if row else None

    async def update_user_risk_status(
        self,
        user_id: int,
        *,
        status: str | None = None,
        bet_restricted: bool | None = None,
        withdraw_restricted: bool | None = None,
        ban_reason: str | None = None,
        risk_note: str | None = None,
    ) -> dict | None:
        row = await self._pool.fetchrow(
            """
            UPDATE users
            SET status = COALESCE($2, status),
                bet_restricted = COALESCE($3, bet_restricted),
                withdraw_restricted = COALESCE($4, withdraw_restricted),
                ban_reason = COALESCE($5, ban_reason),
                risk_note = COALESCE($6, risk_note),
                updated_at = NOW()
            WHERE telegram_user_id = $1
            RETURNING *
            """,
            user_id,
            status,
            bet_restricted,
            withdraw_restricted,
            ban_reason,
            risk_note,
        )
        return dict(row) if row else None

    async def get_user_risk_status(self, user_id: int) -> dict | None:
        row = await self._pool.fetchrow(
            """
            SELECT telegram_user_id, status, bet_restricted, withdraw_restricted, ban_reason, risk_note
            FROM users
            WHERE telegram_user_id = $1
            """,
            user_id,
        )
        return dict(row) if row else None

    async def list_payout_freezes(self, status: str = "frozen", limit: int = 50) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT * FROM payout_freezes WHERE status = $1 ORDER BY unlock_at, id LIMIT $2",
            status,
            limit,
        )
        return [dict(row) for row in rows]

    async def list_wallet_freezes(self, user_id: int, limit: int = 50) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT * FROM wallet_freezes WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
            user_id,
            limit,
        )
        return [dict(row) for row in rows]

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


def _clean_lookup_token(value: str) -> str:
    token = " ".join(str(value or "").strip().split())
    if token.startswith("<") and token.endswith(">") and len(token) >= 2:
        token = token[1:-1].strip()
    return token


def _command_count(result: str) -> int:
    try:
        return int(result.rsplit(" ", 1)[1])
    except (IndexError, ValueError):
        return 0
