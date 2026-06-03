from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    api_football_key: str
    api_football_base_url: str
    database_url: str
    redis_url: str
    featured_league_ids: set[int]
    featured_countries: list[str]
    featured_keywords: list[str]
    max_featured_matches: int
    live_refresh_seconds: int
    today_refresh_seconds: int
    odds_refresh_seconds: int
    bet_cutoff_minutes: int
    enable_live_betting: bool
    show_only_bettable_matches: bool
    show_tomorrow_matches: bool
    bettable_days_ahead: int
    max_bettable_matches: int
    super_admin_user_ids: set[int]
    admin_user_ids: set[int]
    agent_user_ids: set[int]
    default_language: str
    payment_provider: str
    gmpay_pid: str
    gmpay_base_url: str
    gmpay_create_order_path: str
    gmpay_secret: str
    gmpay_sign_type: str
    gmpay_notify_url: str
    gmpay_redirect_url: str | None
    gmpay_public_cashier_base_url: str
    gmpay_default_currency: str
    gmpay_default_token: str
    gmpay_default_network: str
    gmpay_default_payment_type: str | None
    gmpay_min_recharge_usdt: Decimal
    gmpay_order_expire_minutes: int
    payment_amount_tolerance_usdt: Decimal
    epusdt_base_url: str
    epusdt_api_secret: str
    epusdt_notify_url: str
    epusdt_redirect_url: str | None
    epusdt_min_recharge_usdt: Decimal
    epusdt_order_expire_minutes: int
    app_public_base_url: str
    referral_deposit_commission_rate: Decimal
    referral_agent_enabled: bool
    max_referral_level: int
    wallet_currency: str
    withdraw_enabled: bool
    real_betting_enabled: bool
    bet_require_balance_for_simulation: bool
    user_cancel_after_confirm_enabled: bool
    admin_cancel_before_start_minutes: int
    payout_freeze_hours: int
    payout_freeze_enabled: bool
    bet_settlement_admin_only: bool
    bet_auto_settlement_enabled: bool
    bet_settlement_interval_seconds: int
    settlement_require_final_status: bool
    settlement_notify_group_enabled: bool
    settlement_group_chat_id: int | None
    settlement_public_win_min_payout: Decimal
    min_bet_amount: Decimal
    max_bet_amount: Decimal
    default_bet_amount: Decimal
    min_recharge_amount: Decimal
    max_recharge_amount: Decimal
    bet_cancel_before_start_minutes: int
    min_withdraw_amount: Decimal
    rebate_enabled: bool
    rebate_request_enabled: bool
    rebate_mode: str
    rebate_by_active_referrals_enabled: bool
    rebate_by_turnover_enabled: bool
    rebate_settlement_admin_only: bool
    referral_turnover_commission_rate: Decimal
    agent_application_enabled: bool
    agent_min_total_deposit: Decimal
    agent_min_total_turnover: Decimal
    agent_min_valid_referrals: int
    worldcup_demo_markets_enabled: bool
    announcement_channel_id: int | None
    announcement_channel_username: str
    announcement_channel_invite_url: str
    community_group_cn_id: int | None
    community_group_en_id: int | None
    bot_username: str
    require_announcement_subscription: bool
    agent_key_redeem_enabled: bool
    agent_key_prefix: str
    agent_key_default_rebate_rate: Decimal
    log_level: str = "INFO"


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        telegram_bot_token=_required_env("TELEGRAM_BOT_TOKEN"),
        api_football_key=_required_env("API_FOOTBALL_KEY"),
        api_football_base_url=os.getenv(
            "API_FOOTBALL_BASE_URL", "https://v3.football.api-sports.io"
        ),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql://football:football_password@postgres:5432/football_score_bot",
        ),
        redis_url=os.getenv("REDIS_URL", "redis://redis:6379/0"),
        featured_league_ids=_parse_int_set(os.getenv("FEATURED_LEAGUE_IDS", "")),
        featured_countries=_parse_csv(
            os.getenv(
                "FEATURED_COUNTRIES",
                "World,Europe,England,Spain,Italy,Germany,France,Portugal,Netherlands,"
                "Saudi-Arabia,USA,Japan,Korea-Republic,China",
            )
        ),
        featured_keywords=_parse_csv(
            os.getenv(
                "FEATURED_KEYWORDS",
                "World Cup,UEFA Champions League,Europa League,Premier League,La Liga,"
                "Serie A,Bundesliga,Ligue 1,AFC Champions League,Copa America,"
                "European Championship",
            )
        ),
        max_featured_matches=int(os.getenv("MAX_FEATURED_MATCHES", "20")),
        live_refresh_seconds=int(os.getenv("LIVE_REFRESH_SECONDS", "60")),
        today_refresh_seconds=int(os.getenv("TODAY_REFRESH_SECONDS", "300")),
        odds_refresh_seconds=int(os.getenv("ODDS_REFRESH_SECONDS", "120")),
        bet_cutoff_minutes=int(os.getenv("BET_CUTOFF_MINUTES", "5")),
        enable_live_betting=_parse_bool(os.getenv("ENABLE_LIVE_BETTING", "false")),
        show_only_bettable_matches=_parse_bool(os.getenv("SHOW_ONLY_BETTABLE_MATCHES", "true")),
        show_tomorrow_matches=_parse_bool(os.getenv("SHOW_TOMORROW_MATCHES", "true")),
        bettable_days_ahead=max(1, int(os.getenv("BETTABLE_DAYS_AHEAD", "2"))),
        max_bettable_matches=int(os.getenv("MAX_BETTABLE_MATCHES", "30")),
        super_admin_user_ids=_parse_int_set(os.getenv("SUPER_ADMIN_USER_IDS", "")),
        admin_user_ids=_parse_int_set(os.getenv("ADMIN_USER_IDS", "")),
        agent_user_ids=_parse_int_set(os.getenv("AGENT_USER_IDS", "")),
        default_language=os.getenv("DEFAULT_LANGUAGE", "zh-CN"),
        payment_provider=os.getenv("PAYMENT_PROVIDER", "gmpay"),
        gmpay_pid=os.getenv("GMPAY_PID", ""),
        gmpay_base_url=os.getenv("GMPAY_BASE_URL", "https://hosea.cc.cd").rstrip("/"),
        gmpay_create_order_path=os.getenv(
            "GMPAY_CREATE_ORDER_PATH",
            "/payments/gmpay/v1/order/create-transaction",
        ),
        gmpay_secret=os.getenv("GMPAY_SECRET", ""),
        gmpay_sign_type=os.getenv("GMPAY_SIGN_TYPE", "md5").lower(),
        gmpay_notify_url=os.getenv("GMPAY_NOTIFY_URL", ""),
        gmpay_redirect_url=os.getenv("GMPAY_REDIRECT_URL") or None,
        gmpay_public_cashier_base_url=os.getenv(
            "GMPAY_PUBLIC_CASHIER_BASE_URL",
            "https://pay.hosea.cc.cd",
        ).rstrip("/"),
        gmpay_default_currency=os.getenv("GMPAY_DEFAULT_CURRENCY", "cny"),
        gmpay_default_token=os.getenv("GMPAY_DEFAULT_TOKEN", "usdt"),
        gmpay_default_network=os.getenv("GMPAY_DEFAULT_NETWORK", "tron"),
        gmpay_default_payment_type=os.getenv("GMPAY_DEFAULT_PAYMENT_TYPE") or None,
        gmpay_min_recharge_usdt=Decimal(os.getenv("GMPAY_MIN_RECHARGE_USDT", "2")),
        gmpay_order_expire_minutes=int(os.getenv("GMPAY_ORDER_EXPIRE_MINUTES", "30")),
        payment_amount_tolerance_usdt=Decimal(os.getenv("PAYMENT_AMOUNT_TOLERANCE_USDT", "0.01")),
        epusdt_base_url=os.getenv("EPUSDT_BASE_URL", "").rstrip("/"),
        epusdt_api_secret=os.getenv("EPUSDT_API_SECRET", ""),
        epusdt_notify_url=os.getenv("EPUSDT_NOTIFY_URL", ""),
        epusdt_redirect_url=os.getenv("EPUSDT_REDIRECT_URL") or None,
        epusdt_min_recharge_usdt=Decimal(os.getenv("EPUSDT_MIN_RECHARGE_USDT", "10")),
        epusdt_order_expire_minutes=int(os.getenv("EPUSDT_ORDER_EXPIRE_MINUTES", "30")),
        app_public_base_url=os.getenv("APP_PUBLIC_BASE_URL", ""),
        referral_deposit_commission_rate=Decimal(os.getenv("REFERRAL_DEPOSIT_COMMISSION_RATE", "0.00")),
        referral_agent_enabled=_parse_bool(os.getenv("REFERRAL_AGENT_ENABLED", "true")),
        max_referral_level=max(1, int(os.getenv("MAX_REFERRAL_LEVEL", "1"))),
        wallet_currency=os.getenv("WALLET_CURRENCY", "USDT"),
        withdraw_enabled=_parse_bool(os.getenv("WITHDRAW_ENABLED", "false")),
        real_betting_enabled=_parse_bool(os.getenv("REAL_BETTING_ENABLED", "false")),
        bet_require_balance_for_simulation=_parse_bool(os.getenv("BET_REQUIRE_BALANCE_FOR_SIMULATION", "true")),
        user_cancel_after_confirm_enabled=_parse_bool(os.getenv("USER_CANCEL_AFTER_CONFIRM_ENABLED", "false")),
        admin_cancel_before_start_minutes=int(os.getenv("ADMIN_CANCEL_BEFORE_START_MINUTES", "5")),
        payout_freeze_hours=max(0, int(os.getenv("PAYOUT_FREEZE_HOURS", "24"))),
        payout_freeze_enabled=_parse_bool(os.getenv("PAYOUT_FREEZE_ENABLED", "true")),
        bet_settlement_admin_only=_parse_bool(os.getenv("BET_SETTLEMENT_ADMIN_ONLY", "false")),
        bet_auto_settlement_enabled=_parse_bool(os.getenv("BET_AUTO_SETTLEMENT_ENABLED", "true")),
        bet_settlement_interval_seconds=max(10, int(os.getenv("BET_SETTLEMENT_INTERVAL_SECONDS", "60"))),
        settlement_require_final_status=_parse_bool(os.getenv("SETTLEMENT_REQUIRE_FINAL_STATUS", "true")),
        settlement_notify_group_enabled=_parse_bool(os.getenv("SETTLEMENT_NOTIFY_GROUP_ENABLED", "false")),
        settlement_group_chat_id=_parse_optional_int(os.getenv("SETTLEMENT_GROUP_CHAT_ID", "")),
        settlement_public_win_min_payout=Decimal(os.getenv("SETTLEMENT_PUBLIC_WIN_MIN_PAYOUT", "0")),
        min_bet_amount=Decimal(os.getenv("MIN_BET_AMOUNT", "2")),
        max_bet_amount=Decimal(os.getenv("MAX_BET_AMOUNT", "100")),
        default_bet_amount=Decimal(os.getenv("DEFAULT_BET_AMOUNT", "2")),
        min_recharge_amount=Decimal(os.getenv("MIN_RECHARGE_AMOUNT", "2")),
        max_recharge_amount=Decimal(os.getenv("MAX_RECHARGE_AMOUNT", "1000")),
        bet_cancel_before_start_minutes=int(os.getenv("BET_CANCEL_BEFORE_START_MINUTES", "5")),
        min_withdraw_amount=Decimal(os.getenv("MIN_WITHDRAW_AMOUNT", "10")),
        rebate_enabled=_parse_bool(os.getenv("REBATE_ENABLED", "true")),
        rebate_request_enabled=_parse_bool(os.getenv("REBATE_REQUEST_ENABLED", "true")),
        rebate_mode=os.getenv("REBATE_MODE", "none"),
        rebate_by_active_referrals_enabled=_parse_bool(os.getenv("REBATE_BY_ACTIVE_REFERRALS_ENABLED", "false")),
        rebate_by_turnover_enabled=_parse_bool(os.getenv("REBATE_BY_TURNOVER_ENABLED", "false")),
        rebate_settlement_admin_only=_parse_bool(os.getenv("REBATE_SETTLEMENT_ADMIN_ONLY", "true")),
        referral_turnover_commission_rate=Decimal(os.getenv("REFERRAL_TURNOVER_COMMISSION_RATE", "0.00")),
        agent_application_enabled=_parse_bool(os.getenv("AGENT_APPLICATION_ENABLED", "true")),
        agent_min_total_deposit=Decimal(os.getenv("AGENT_MIN_TOTAL_DEPOSIT", "100")),
        agent_min_total_turnover=Decimal(os.getenv("AGENT_MIN_TOTAL_TURNOVER", "500")),
        agent_min_valid_referrals=int(os.getenv("AGENT_MIN_VALID_REFERRALS", "5")),
        worldcup_demo_markets_enabled=_parse_bool(os.getenv("WORLDCUP_DEMO_MARKETS_ENABLED", "true")),
        announcement_channel_id=_parse_optional_int(os.getenv("ANNOUNCEMENT_CHANNEL_ID", "")),
        announcement_channel_username=os.getenv("ANNOUNCEMENT_CHANNEL_USERNAME", "").strip(),
        announcement_channel_invite_url=os.getenv("ANNOUNCEMENT_CHANNEL_INVITE_URL", "").strip(),
        community_group_cn_id=_parse_optional_int(os.getenv("COMMUNITY_GROUP_CN_ID", "")),
        community_group_en_id=_parse_optional_int(os.getenv("COMMUNITY_GROUP_EN_ID", "")),
        bot_username=os.getenv("BOT_USERNAME", "worldcuptopBot").strip(),
        require_announcement_subscription=_parse_bool(os.getenv("REQUIRE_ANNOUNCEMENT_SUBSCRIPTION", "true")),
        agent_key_redeem_enabled=_parse_bool(os.getenv("AGENT_KEY_REDEEM_ENABLED", "true")),
        agent_key_prefix=os.getenv("AGENT_KEY_PREFIX", "AGENT-").strip() or "AGENT-",
        agent_key_default_rebate_rate=Decimal(os.getenv("AGENT_KEY_DEFAULT_REBATE_RATE", "0.20")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_int_set(value: str) -> set[int]:
    result: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            result.add(int(item))
        except ValueError:
            continue
    return result


def _parse_optional_int(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
