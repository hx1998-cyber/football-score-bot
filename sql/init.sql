CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL UNIQUE,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    language_code TEXT,
    language TEXT,
    referral_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS telegram_groups (
    id BIGSERIAL PRIMARY KEY,
    telegram_chat_id BIGINT NOT NULL UNIQUE,
    title TEXT,
    chat_type TEXT NOT NULL,
    is_subscribed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fixtures_cache (
    id BIGSERIAL PRIMARY KEY,
    cache_key TEXT NOT NULL UNIQUE,
    payload JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id BIGSERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL,
    subscription_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    target_name TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (telegram_user_id, subscription_type, target_id)
);

CREATE TABLE IF NOT EXISTS notifications_log (
    id BIGSERIAL PRIMARY KEY,
    telegram_user_id BIGINT,
    telegram_chat_id BIGINT,
    notification_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wallets (
    id BIGSERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL UNIQUE,
    user_id BIGINT,
    balance_cents BIGINT NOT NULL DEFAULT 0,
    balance NUMERIC(18, 6) NOT NULL DEFAULT 0,
    frozen_balance NUMERIC(18, 6) NOT NULL DEFAULT 0,
    total_deposit NUMERIC(18, 6) NOT NULL DEFAULT 0,
    total_withdraw NUMERIC(18, 6) NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'USDT',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bets (
    id BIGSERIAL PRIMARY KEY,
    telegram_user_id BIGINT,
    user_id BIGINT,
    fixture_id BIGINT,
    fixture_label TEXT,
    market_key TEXT,
    market_title TEXT,
    selection TEXT,
    odds NUMERIC(10, 2),
    stake NUMERIC(12, 2),
    potential_payout NUMERIC(12, 2),
    payout NUMERIC(12, 2) NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    bettable_status_at_submit TEXT,
    balance_frozen BOOLEAN NOT NULL DEFAULT FALSE,
    bet_no TEXT,
    league_name TEXT,
    home_team TEXT,
    away_team TEXT,
    fixture_start_time TIMESTAMPTZ,
    is_simulated BOOLEAN NOT NULL DEFAULT TRUE,
    result_score TEXT,
    settlement_source TEXT,
    settlement_note TEXT,
    settled_by_admin_id BIGINT,
    settled_at TIMESTAMPTZ,
    amount_cents BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS admin_market_overrides (
    id BIGSERIAL PRIMARY KEY,
    fixture_id BIGINT NOT NULL UNIQUE,
    is_suspended BOOLEAN NOT NULL DEFAULT FALSE,
    reason TEXT,
    updated_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS referrals (
    id BIGSERIAL PRIMARY KEY,
    referrer_telegram_user_id BIGINT NOT NULL,
    referred_telegram_user_id BIGINT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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
);

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
);

CREATE TABLE IF NOT EXISTS user_predictions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    market_id BIGINT NOT NULL REFERENCES futures_markets(id),
    option_id BIGINT NOT NULL REFERENCES futures_options(id),
    stake_simulated NUMERIC(12, 2) NOT NULL DEFAULT 0,
    odds NUMERIC(10, 2) NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fixtures_cache_expires_at ON fixtures_cache (expires_at);
CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions (telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications_log (telegram_user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_wallets_user_currency ON wallets (user_id, currency);
CREATE INDEX IF NOT EXISTS idx_bets_user ON bets (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bets_fixture ON bets (fixture_id);
CREATE INDEX IF NOT EXISTS idx_user_predictions_user ON user_predictions (user_id, created_at DESC);

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
);

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
);

CREATE TABLE IF NOT EXISTS referral_relations (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL UNIQUE,
    parent_user_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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
);

CREATE TABLE IF NOT EXISTS admin_audit_logs (
    id BIGSERIAL PRIMARY KEY,
    admin_user_id BIGINT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS withdraw_requests (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    amount NUMERIC(18, 6) NOT NULL,
    address TEXT,
    network TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    admin_id BIGINT,
    admin_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ,
    paid_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS rebate_rules (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    mode TEXT NOT NULL,
    min_active_referrals INTEGER NOT NULL DEFAULT 0,
    min_turnover NUMERIC(18, 6) NOT NULL DEFAULT 0,
    rebate_rate NUMERIC(10, 6) NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_deposit_orders_trade_id ON deposit_orders (trade_id) WHERE trade_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_deposit_orders_block_tx ON deposit_orders (block_transaction_id) WHERE block_transaction_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_deposit_orders_chain_tx ON deposit_orders (chain_tx_id) WHERE chain_tx_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_wallet_ledger_ref ON wallet_ledger (ref_type, ref_id, type) WHERE ref_type IS NOT NULL AND ref_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_commission_source ON commission_records (user_id, source_type, source_ref_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_rebate_records_period ON rebate_records (user_id, period_start, period_end, rule_id);
