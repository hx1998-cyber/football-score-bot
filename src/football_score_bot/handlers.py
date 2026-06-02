from __future__ import annotations

import logging
import json
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from datetime import date, datetime, timedelta
from typing import Any
from time import time
from urllib.parse import parse_qs, urlparse

import asyncpg
from aiogram import BaseMiddleware, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from football_score_bot.api_football import ApiFootballClient
from football_score_bot.betting import BettableStatus, is_bettable_fixture, reason_label
from football_score_bot.cache import RedisCache
from football_score_bot.config import Settings
from football_score_bot.command_routing import (
    clean_command_token,
    parse_admin_adjust_args,
    parse_command_name,
    resolve_bet_by_id_or_no,
)
from football_score_bot.database import Database
from football_score_bot.featured import filter_featured_fixtures
from football_score_bot.futures import (
    format_futures_market,
    format_futures_placeholder,
    format_my_predictions,
    format_prediction_confirm,
    format_prediction_saved,
    format_worldcup_zone,
)
from football_score_bot.formatters import (
    format_all_schedule,
    format_bet_confirm,
    format_bet_saved,
    format_bettable_matches,
    format_all_fixtures,
    format_featured_matches,
    format_live_matches,
    format_match_detail,
    format_my_bets,
    format_odds_market_page,
    format_odds_match_detail,
    format_match_search,
)
from football_score_bot.i18n import LANGUAGE_LABELS, SUPPORTED_LANGUAGES, normalize_language, t
from football_score_bot.localization.sports_names import translate_league_name, translate_team_name
from football_score_bot.payments.gmpay import GMPayClient, GMPayCreateOrderError
from football_score_bot.payments.order_ids import generate_gmpay_order_id
from football_score_bot.services.wallet_service import WalletService
from football_score_bot.services.permission_service import PermissionService
from football_score_bot.services.settlement_service import SettlementService
from football_score_bot.states import (
    AdminAdjustStates,
    AgentApplicationStates,
    BetStates,
    RebateStates,
    RechargeStates,
    WithdrawStates,
)
from football_score_bot.keyboards import (
    bet_amount_keyboard,
    bet_created_keyboard,
    bet_confirm_keyboard,
    bet_detail_keyboard,
    featured_matches_keyboard,
    bet_placeholder_keyboard,
    futures_back_keyboard,
    futures_confirm_keyboard,
    futures_market_keyboard,
    fixture_list_keyboard,
    language_keyboard,
    live_matches_keyboard,
    main_menu_keyboard,
    match_detail_keyboard,
    my_bets_keyboard,
    odds_market_keyboard,
    worldcup_schedule_keyboard,
    worldcup_betting_keyboard,
    worldcup_zone_keyboard,
)
from football_score_bot.i18n_football import (
    fixture_beijing_datetime,
    worldcup_match_line,
    worldcup_stage_label,
    zh_league_name,
    zh_team_name,
)
from football_score_bot.worldcup_futures import WORLD_CUP_CHAMPION_MARKET_KEY
from football_score_bot.odds import build_odds_first_matches
from football_score_bot.odds_normalizer import normalized_from_dict, normalize_fixture_odds as normalize_fixture_odds_full
from football_score_bot.time_utils import now_hhmm


logger = logging.getLogger(__name__)
_api_failure_log_times: dict[str, datetime] = {}


class SlashCommandStateMiddleware(BaseMiddleware):
    async def __call__(self, handler: Any, event: Message, data: dict[str, Any]) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)
        command_name = parse_command_name(event.text)
        if not command_name:
            return await handler(event, data)
        state = data.get("state")
        if state is None:
            return await handler(event, data)
        current_state = await state.get_state()
        if not current_state:
            return await handler(event, data)
        await state.clear()
        logger.info(
            "slash_command_cleared_fsm command_name=%s telegram_user_id=%s previous_state=%s",
            command_name,
            event.from_user.id if event.from_user else None,
            current_state,
        )
        if command_name == "cancel":
            await event.answer("已取消当前操作。")
            return None
        return await handler(event, data)

MENU_BETTABLE_TEXTS = {"🎯 可投注赛事", "可投注赛事", "🎯 Bettable Matches", "Bettable Matches", "🔥 今日热门", "今日热门", "🔥 Featured Matches", "Featured Matches"}
MENU_ALL_FIXTURES_TEXTS = {"📋 全部赛程", "📅 全部赛程", "全部赛程", "📅 All Fixtures", "All Fixtures"}
MENU_BETS_TEXTS = {"📊 我的注单", "🎫 我的注单", "我的注单", "📊 My Bets", "🎫 My Bets", "My Bets"}
MENU_WALLET_TEXTS = {"💰 钱包", "钱包", "充值 USDT", "充值与钱包", "💰 Wallet", "Wallet", "Deposit USDT"}
MENU_REFERRALS_TEXTS = {"👥 推广", "推广", "推广邀请", "邀请返佣", "👥 Referral", "Referral"}
MENU_WORLDCUP_TEXTS = {"🏆 世界杯", "世界杯", "🏆 世界杯 2026", "世界杯 2026", "🏆 World Cup", "World Cup", "🏆 World Cup 2026", "World Cup 2026"}
MENU_LANGUAGE_TEXTS = {"🌐 语言", "语言", "🌐 Language", "Language"}
MENU_SETTINGS_TEXTS = {"设置", "⚙️ 设置", "Settings"}
MENU_HELP_TEXTS = {"帮助", "❓ 帮助", "Help"}


def format_bet_confirm(
    fixture: dict[str, Any],
    market_title: str,
    selection: str,
    odds: str,
    stake: str = "10",
    lang: str = "zh",
) -> str:
    teams = fixture.get("teams", {})
    home = teams.get("home", {}).get("name", "Home" if lang == "en" else "主队")
    away = teams.get("away", {}).get("name", "Away" if lang == "en" else "客队")
    if lang == "en":
        return "\n".join(
            [
                "🎯 Confirm Bet",
                f"Match: {home} vs {away}",
                f"Market: {market_title}",
                f"Selection: {selection}",
                f"Amount: {stake} USDT",
                f"Odds: {odds}",
                f"Estimated Payout: {_potential_payout_text(stake, odds)} USDT",
            ]
        )
    return "\n".join(
        [
            "🎯 确认下注",
            f"比赛：{home} vs {away}",
            f"玩法：{market_title}",
            f"选择：{selection}",
            f"赔率：{odds}",
            f"金额：{stake} USDT",
            f"预计派彩：{_potential_payout_text(stake, odds)} USDT",
        ]
    )


def build_router(
    api_client: ApiFootballClient,
    cache: RedisCache,
    database: Database,
    settings: Settings,
) -> Router:
    router = Router()
    router.message.outer_middleware(SlashCommandStateMiddleware())
    wallet_service = WalletService(
        database,
        currency=settings.wallet_currency,
        referral_deposit_commission_rate=settings.referral_deposit_commission_rate,
        referral_agent_enabled=settings.referral_agent_enabled,
        payout_freeze_enabled=settings.payout_freeze_enabled,
        payout_freeze_hours=settings.payout_freeze_hours,
    )
    permission_service = PermissionService(database, settings)
    settlement_service = SettlementService(
        database,
        wallet_service,
        real_betting_enabled=settings.real_betting_enabled,
    )
    gmpay_client = GMPayClient(
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

    async def _require_private_role(message: Message, allowed_roles: set[str]) -> bool:
        if message.chat.type != "private" or not message.from_user:
            await message.answer("当前权限不足，请联系超级管理员。")
            return False
        role = await permission_service.get_user_role(message.from_user.id)
        if role not in allowed_roles:
            await message.answer("当前权限不足，请联系超级管理员。")
            return False
        return True

    async def _require_super_admin(message: Message) -> bool:
        return await _require_private_role(message, {"super_admin"})

    @router.callback_query(F.data.startswith("fsm_cancel:"))
    async def fsm_cancel(callback: CallbackQuery, state: FSMContext) -> None:
        await _safe_callback_answer(callback)
        target = callback.data.split(":", 1)[1]
        await state.clear()
        if target == "wallet":
            await callback.message.answer("已取消。", reply_markup=_wallet_keyboard())
        elif target == "referrals":
            await callback.message.answer("已取消。", reply_markup=_referral_keyboard())
        elif target == "admin":
            await callback.message.answer("已取消管理员操作。")
        else:
            await callback.message.answer("已取消。")

    @router.message(Command("start"))
    async def start(message: Message, command: CommandObject) -> None:
        lang = await _remember_user_and_lang(message, database, settings)
        await _maybe_bind_referral(message, command, database)
        await message.answer(
            await _start_text(cache, api_client, database, settings, message.from_user.id if message.from_user else None, lang),
            reply_markup=main_menu_keyboard(lang),
        )

    @router.callback_query(F.data == "home")
    async def home_callback(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        lang = await _callback_lang(callback, database, settings)
        await callback.message.answer(
            await _start_text(cache, api_client, database, settings, callback.from_user.id if callback.from_user else None, lang),
            reply_markup=main_menu_keyboard(lang),
        )

    @router.message(Command("help"))
    @router.message(F.text.in_(MENU_HELP_TEXTS))
    @router.callback_query(F.data == "menu:help")
    async def help_command(event: Message | CallbackQuery) -> None:
        await _answer_callback(event)
        message = _message(event)
        lang = await _event_lang(event, database, settings)
        await message.answer(
            "/live - " + t(lang, "live_scores") + "\n"
            "/today - " + t(lang, "today_matches") + "\n"
            "/match <keyword> - " + t(lang, "search") + "\n"
            "/language - " + t(lang, "language_settings") + "\n"
            "/subscribe - group featured live broadcasts"
        )

    @router.message(Command("live"))
    @router.message(F.text.in_(_translated_texts("live_scores")))
    @router.callback_query(F.data == "live_featured")
    async def live(event: Message | CallbackQuery) -> None:
        await _answer_callback(event, "加载中...")
        message = _message(event)
        lang = await _event_lang(event, database, settings)
        await _remember_chat(message, database)
        fixtures = await _get_featured_live(cache, api_client, settings)
        odds = await _get_today_odds(cache)
        last_update = await cache.get_text("football:last_update:live") or _now_hhmm()
        localized = _localized_fixtures(fixtures, lang)
        text = format_live_matches(
            localized,
            odds,
            last_update,
            t(lang, "live_scores"),
            t(lang, "no_live_matches"),
        )
        await message.answer(
            text,
            reply_markup=fixture_list_keyboard(localized, lang, mode="live")
            if fixtures
            else live_matches_keyboard(lang, include_all=True),
        )

    @router.callback_query(F.data == "live_all")
    async def live_all(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        lang = await _callback_lang(callback, database, settings)
        fixtures = await _get_live(cache, api_client)
        odds = await _get_today_odds(cache)
        last_update = await cache.get_text("football:last_update:live") or _now_hhmm()
        localized = _localized_fixtures(fixtures, lang)
        await callback.message.answer(
            format_live_matches(localized, odds, last_update, t(lang, "live_scores"), t(lang, "no_live_matches")),
            reply_markup=fixture_list_keyboard(localized, lang, mode="live"),
        )

    @router.message(Command("today"))
    @router.message(F.text.in_({"📅 " + text for text in _translated_texts("today_matches")}))
    @router.message(F.text.in_(MENU_BETTABLE_TEXTS))
    @router.callback_query(F.data == "menu:bettable")
    @router.callback_query(F.data == "today_featured")
    async def today(event: Message | CallbackQuery) -> None:
        await _answer_callback(event, "加载中...")
        message = _message(event)
        lang = await _event_lang(event, database, settings)
        await _remember_chat(message, database)
        effective_settings = await _effective_settings(cache, settings)
        fixtures, odds = await get_bettable_matches_range(cache, api_client, database, effective_settings)
        last_update = await cache.get_text("football:bettable_matches:last_update") or _now_hhmm()
        localized = _localized_fixtures(fixtures, lang)
        await message.answer(
            format_bettable_matches(
                localized,
                odds,
                last_update,
                effective_settings.bet_cutoff_minutes,
                effective_settings.max_bettable_matches,
            ),
            reply_markup=fixture_list_keyboard(localized, lang, mode="today")
            if fixtures
            else featured_matches_keyboard(lang),
        )

    @router.message(Command("worldcup"))
    @router.message(F.text.in_(_translated_texts("worldcup") | MENU_WORLDCUP_TEXTS))
    @router.callback_query(F.data.in_({"worldcup", "worldcup:home", "menu:worldcup"}))
    async def worldcup(event: Message | CallbackQuery) -> None:
        await _answer_callback(event, "加载中...")
        message = _message(event)
        lang = await _event_lang(event, database, settings)
        await _remember_chat(message, database)
        await message.answer(t(lang, "worldcup_home_title"), reply_markup=_worldcup_home_keyboard(lang))

    @router.callback_query(F.data == "worldcup_schedule")
    @router.callback_query(F.data.in_({"worldcup:schedule", "worldcup:schedule:0"}))
    @router.callback_query(F.data.startswith("worldcup:schedule:"))
    async def worldcup_schedule(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        lang = await _callback_lang(callback, database, settings)
        page = 0
        if callback.data and callback.data.startswith("worldcup:schedule:"):
            try:
                page = int(callback.data.rsplit(":", 1)[1])
            except ValueError:
                page = 0
        fixtures = _fallback_worldcup_fixtures()
        text, total_pages = _format_worldcup_schedule_page(fixtures, lang=lang)
        await callback.message.answer(text, reply_markup=worldcup_schedule_keyboard(page, total_pages, lang))

    @router.callback_query(F.data.in_({"worldcup:futures", "worldcup:futures:0"}))
    @router.callback_query(F.data.startswith("worldcup:futures:"))
    async def worldcup_futures(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        lang = await _callback_lang(callback, database, settings)
        page = 0
        if callback.data and callback.data.startswith("worldcup:futures:"):
            try:
                page = int(callback.data.rsplit(":", 1)[1])
            except ValueError:
                page = 0
        options = await database.list_futures_options(WORLD_CUP_CHAMPION_MARKET_KEY)
        per_page = 8
        total_pages = max((len(options) - 1) // per_page + 1, 1)
        page = max(0, min(page, total_pages - 1))
        page_options = options[page * per_page : (page + 1) * per_page]
        await callback.message.answer(
            _format_worldcup_futures(options, page=page, per_page=per_page, lang=lang),
            reply_markup=futures_market_keyboard(WORLD_CUP_CHAMPION_MARKET_KEY, page_options, page, total_pages, lang)
            if options
            else futures_back_keyboard(lang),
        )

    @router.callback_query(F.data.in_({"worldcup:betting", "worldcup:betting:0"}))
    @router.callback_query(F.data.startswith("worldcup:betting:"))
    async def worldcup_betting(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        lang = await _callback_lang(callback, database, settings)
        page = 0
        if callback.data and callback.data.startswith("worldcup:betting:"):
            try:
                page = int(callback.data.rsplit(":", 1)[1])
            except ValueError:
                page = 0
        fixtures = _fallback_worldcup_fixtures()
        per_page = 8
        total_pages = max((len(fixtures) - 1) // per_page + 1, 1)
        page = max(0, min(page, total_pages - 1))
        visible = _localized_fixtures(fixtures[page * per_page : (page + 1) * per_page], lang)
        await callback.message.answer(
            t(lang, "worldcup_betting_title"),
            reply_markup=worldcup_betting_keyboard(visible, page, total_pages, lang),
        )

    @router.callback_query(F.data == "worldcup_standings")
    async def worldcup_standings(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        lang = await _callback_lang(callback, database, settings)
        await callback.message.answer("📊 小组积分即将开放\n后续将根据 FIFA 官方分组和赛程开放。", reply_markup=futures_back_keyboard(lang))

    @router.callback_query(F.data == "worldcup_poster")
    async def worldcup_poster(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        await callback.message.answer(
            "🏆 世界杯海报功能即将开放。",
            reply_markup=futures_back_keyboard(await _callback_lang(callback, database, settings)),
        )

    @router.callback_query(F.data.startswith("futures:placeholder:"))
    async def futures_placeholder(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        lang = await _callback_lang(callback, database, settings)
        key = callback.data.rsplit(":", 1)[1]
        title = {
            "group_qualification": "🚀 小组晋级预测",
            "group_winner": "🥇 小组第一预测",
            "knockout_futures": "进入四强 / 进入决赛预测",
            "mvp": "MVP / Golden Ball 预测",
        }.get(key, "预测市场")
        await callback.message.answer(format_futures_placeholder(title), reply_markup=futures_back_keyboard(lang))

    @router.callback_query(F.data.startswith("futures:market:"))
    async def futures_market(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        lang = await _callback_lang(callback, database, settings)
        risk = await database.get_user_risk_status(callback.from_user.id)
        if _risk_blocks(risk, "bet"):
            await callback.message.answer("账户当前被限制下注，请联系管理员。")
            return
        parts = callback.data.split(":")
        market_key = parts[2]
        page = int(parts[4]) if len(parts) >= 5 and parts[3] == "page" else 0
        options = await database.list_futures_options(market_key)
        per_page = 5
        total_pages = max((len(options) - 1) // per_page + 1, 1)
        page = max(0, min(page, total_pages - 1))
        page_options = options[page * per_page : (page + 1) * per_page]
        await callback.message.answer(
            format_futures_market(market_key, options, page=page, per_page=per_page),
            reply_markup=futures_market_keyboard(market_key, page_options, page, total_pages, lang)
            if options
            else futures_back_keyboard(lang),
        )

    @router.callback_query(F.data.startswith("futures:option:"))
    async def futures_option(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        option_id = int(callback.data.rsplit(":", 1)[1])
        option = await database.get_futures_option(option_id)
        if not option:
            await callback.message.answer("该预测选项暂不可用。")
            return
        await callback.message.answer(
            format_prediction_confirm(option),
            reply_markup=futures_confirm_keyboard(option_id, option["market_key"]),
        )

    @router.callback_query(F.data.startswith("futures:confirm:"))
    async def futures_confirm(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        if not callback.from_user:
            await callback.message.answer("请先打开机器人后再提交预测。")
            return
        option_id = int(callback.data.rsplit(":", 1)[1])
        option = await database.get_futures_option(option_id)
        if not option:
            await callback.message.answer("该预测选项暂不可用。")
            return
        prediction_id = await database.create_user_prediction(
            telegram_user_id=callback.from_user.id,
            market_id=int(option["market_id"]),
            option_id=int(option["option_id"]),
            odds=str(option["odds"]),
            stake_simulated="10",
        )
        await callback.message.answer(
            format_prediction_saved(option, prediction_id),
            reply_markup=futures_back_keyboard(await _callback_lang(callback, database, settings)),
        )

    @router.callback_query(F.data.startswith("futures:bet:"))
    async def futures_bet(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        if not callback.from_user:
            return
        lang = await _callback_lang(callback, database, settings)
        parts = callback.data.split(":")
        if len(parts) < 4:
            await callback.message.answer(t(lang, "cancel"))
            return
        option = await database.get_futures_option(int(parts[2]))
        if not option or option.get("market_key") != WORLD_CUP_CHAMPION_MARKET_KEY:
            await callback.message.answer("该预测选项暂不可用。" if lang != "en" else "This futures option is unavailable.")
            return
        stake_decimal = _validated_amount(parts[3], settings.min_bet_amount, settings.max_bet_amount)
        risk = await database.get_user_risk_status(callback.from_user.id)
        if _risk_blocks(risk, "bet"):
            await callback.message.answer("账户当前被限制下注，请联系管理员。" if lang != "en" else "Betting is restricted on this account.")
            return
        if settings.real_betting_enabled or settings.bet_require_balance_for_simulation:
            wallet_row = await wallet_service.get_balance(callback.from_user.id)
            balance = Decimal(str(wallet_row.get("balance") or 0))
            if balance < stake_decimal:
                await callback.message.answer(
                    _format_insufficient_balance(stake_decimal, balance, settings.wallet_currency, lang),
                    reply_markup=_insufficient_balance_keyboard(None, lang),
                )
                return
        odds = str(option["odds"])
        payout = (stake_decimal * Decimal(odds)).quantize(Decimal("0.01"))
        bet_id = await wallet_service.submit_bet(
            user_id=callback.from_user.id,
            fixture_id=None,
            fixture_label=t(lang, "worldcup_futures_title"),
            market_key=WORLD_CUP_CHAMPION_MARKET_KEY,
            market_title=t(lang, "worldcup_futures_title"),
            selection=_worldcup_option_label(option, lang),
            odds=odds,
            stake=stake_decimal,
            potential_payout=payout,
            bettable_status_at_submit="futures",
            real_betting_enabled=settings.real_betting_enabled,
            league_name="World Cup",
            home_team=str(option.get("label") or "-"),
            away_team="Champion",
            fixture_start_time=None,
        )
        if bet_id is None:
            wallet_row = await wallet_service.get_balance(callback.from_user.id)
            await callback.message.answer(
                _format_insufficient_balance(stake_decimal, Decimal(str(wallet_row.get("balance") or 0)), settings.wallet_currency, lang),
                reply_markup=_insufficient_balance_keyboard(None, lang),
            )
            return
        bet = await database.get_bet(bet_id)
        await callback.message.answer(
            _format_bet_created(bet or {"id": bet_id}, settings.wallet_currency, lang),
            reply_markup=bet_created_keyboard(str((bet or {}).get("bet_no") or bet_id), lang=lang),
        )

    @router.callback_query(F.data == "futures:my")
    async def futures_my(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        lang = await _callback_lang(callback, database, settings)
        if not callback.from_user:
            await callback.message.answer("请先打开机器人后再查看预测。", reply_markup=futures_back_keyboard(lang))
            return
        predictions = await database.list_user_predictions(callback.from_user.id)
        await callback.message.answer(format_my_predictions(predictions), reply_markup=futures_back_keyboard(lang))

    @router.callback_query(F.data == "today_all")
    @router.message(F.text == "📋 全部赛程")
    @router.message(F.text.in_(MENU_ALL_FIXTURES_TEXTS))
    async def today_all(callback: CallbackQuery) -> None:
        await _answer_callback(callback, "加载中...")
        message = _message(callback)
        lang = await _event_lang(callback, database, settings)
        fixtures, statuses = await get_all_schedule_range(cache, api_client, database, settings)
        last_update = await cache.get_text("football:all_schedule:last_update") or _now_hhmm()
        localized = _localized_fixtures(fixtures, lang)
        await message.answer(
            format_all_schedule(localized, statuses, last_update, limit=40),
            reply_markup=fixture_list_keyboard(localized[:20], lang, mode="today"),
        )

    @router.callback_query(F.data == "refresh_odds")
    async def refresh_odds(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        effective_settings = await _effective_settings(cache, settings)
        matches, odds = await get_bettable_matches_range(cache, api_client, database, effective_settings, force_refresh=True)
        lang = await _callback_lang(callback, database, settings)
        localized = _localized_fixtures(matches, lang)
        await callback.message.answer(
            format_bettable_matches(
                localized,
                odds,
                await cache.get_text("football:bettable_matches:last_update") or _now_hhmm(),
                effective_settings.bet_cutoff_minutes,
                effective_settings.max_bettable_matches,
            ),
            reply_markup=fixture_list_keyboard(localized, lang, mode="today")
            if matches
            else featured_matches_keyboard(lang),
        )

    @router.callback_query(F.data.startswith("fixture:"))
    async def fixture_detail(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        lang = await _callback_lang(callback, database, settings)
        fixture_id = int(callback.data.split(":", 1)[1])
        fixture = await _find_cached_fixture(cache, api_client, settings, fixture_id)
        if not fixture:
            await callback.message.answer("正在加载赔率，请稍候...")
            fixture = await _find_cached_fixture(cache, api_client, settings, fixture_id)
        if not fixture:
            await callback.message.answer("Match not found.")
            return
        normalized_odds = await _get_fixture_odds(cache, api_client, fixture_id)
        override = await database.get_market_override(fixture_id)
        effective_settings = await _effective_settings(cache, settings)
        bet_status = is_bettable_fixture(
            fixture,
            normalized_odds,
            effective_settings,
            is_suspended_by_admin=bool(override and override.get("is_suspended")),
        )
        events, events_unavailable = await _get_fixture_events_cached(cache, api_client, fixture_id)
        last_update = await cache.get_text(f"football:odds:last_update:{fixture_id}") or _now_hhmm()
        localized_fixture = _localized_fixture(fixture, lang)
        await callback.message.answer(
            format_odds_match_detail(
                localized_fixture,
                normalized_odds,
                last_update,
                bet_status,
                effective_settings.bet_cutoff_minutes,
                events,
                events_unavailable,
            ),
            reply_markup=match_detail_keyboard(lang, fixture_id=fixture_id),
        )

    @router.callback_query(F.data.startswith("odds:fixture:"))
    async def odds_market(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        parts = callback.data.split(":")
        fixture_id = int(parts[2])
        market_key = parts[4]
        page = int(parts[6]) if len(parts) >= 7 and parts[5] == "page" else 0
        fixture = await _find_cached_fixture(cache, api_client, settings, fixture_id)
        if not fixture:
            await callback.message.answer("Match not found.")
            return
        normalized_odds = await _get_fixture_odds(cache, api_client, fixture_id)
        market = _market_for(normalized_odds, market_key)
        per_page = 20
        total_outcomes = len(market.outcomes) if market else 0
        total_pages = max((total_outcomes - 1) // per_page + 1, 1)
        page = max(0, min(page, total_pages - 1))
        page_outcomes = market.outcomes[page * per_page : (page + 1) * per_page] if market else []
        await callback.message.answer(
            format_odds_market_page(_localized_fixture(fixture, await _callback_lang(callback, database, settings)), market, market_key, page, per_page=per_page),
            reply_markup=odds_market_keyboard(fixture_id, market_key, page_outcomes, page, total_pages),
        )

    @router.callback_query(F.data.startswith("bet:"))
    async def bet_selection(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        parts = callback.data.split(":")
        fixture_id = int(parts[1])
        market_key = parts[2]
        page = int(parts[3])
        outcome_index = int(parts[4])
        fixture = await _find_cached_fixture(cache, api_client, settings, fixture_id)
        normalized_odds = await _get_fixture_odds(cache, api_client, fixture_id)
        market = _market_for(normalized_odds, market_key)
        outcomes = market.outcomes[page * 20 : (page + 1) * 20] if market else []
        outcome = outcomes[outcome_index] if outcome_index < len(outcomes) else None
        if not fixture or not outcome:
            return
        override = await database.get_market_override(fixture_id)
        effective_settings = await _effective_settings(cache, settings)
        bet_status = is_bettable_fixture(
            fixture,
            normalized_odds,
            effective_settings,
            is_suspended_by_admin=bool(override and override.get("is_suspended")),
        )
        if not bet_status.is_bettable:
            await callback.message.answer(f"当前不可投注：{reason_label(bet_status.reason)}")
            return
        lang = await _callback_lang(callback, database, settings)
        await callback.message.answer(
            format_bet_confirm(
                fixture,
                getattr(market, "title", market_key),
                _outcome_button_label(outcome),
                outcome.odds,
                stake=str(settings.default_bet_amount),
                lang=lang,
            )
            + "\n\n"
            + _bet_mode_notice(settings),
            reply_markup=bet_confirm_keyboard(fixture_id, market_key, page, outcome_index),
        )

    @router.callback_query(F.data.startswith("bet_confirm:"))
    async def bet_confirm(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        if not callback.from_user:
            await callback.message.answer("请先打开机器人后再提交投注。")
            return
        risk = await database.get_user_risk_status(callback.from_user.id)
        if _risk_blocks(risk, "bet"):
            await callback.message.answer("账户当前被限制下注，请联系管理员。")
            return
        parts = callback.data.split(":")
        fixture_id = int(parts[1])
        market_key = parts[2]
        page = int(parts[3])
        outcome_index = int(parts[4])
        fixture = await _find_cached_fixture(cache, api_client, settings, fixture_id)
        normalized_odds = await _get_fixture_odds(cache, api_client, fixture_id)
        market = _market_for(normalized_odds, market_key)
        outcomes = market.outcomes[page * 20 : (page + 1) * 20] if market else []
        outcome = outcomes[outcome_index] if outcome_index < len(outcomes) else None
        if not fixture or not outcome:
            await callback.message.answer("该赔率当前不可用。")
            return
        override = await database.get_market_override(fixture_id)
        effective_settings = await _effective_settings(cache, settings)
        bet_status = is_bettable_fixture(
            fixture,
            normalized_odds,
            effective_settings,
            is_suspended_by_admin=bool(override and override.get("is_suspended")),
        )
        if not bet_status.is_bettable:
            await callback.message.answer(_bet_unavailable_message(bet_status.reason))
            return
        raw_stake = parts[5] if len(parts) > 5 else str(settings.default_bet_amount)
        try:
            stake_decimal = _validated_amount(raw_stake, settings.min_bet_amount, settings.max_bet_amount)
        except ValueError as exc:
            await callback.message.answer(str(exc))
            return
        if stake_decimal < settings.min_bet_amount or stake_decimal > settings.max_bet_amount:
            await callback.message.answer(
                f"下注金额超出限制：{_money(settings.min_bet_amount)}-{_money(settings.max_bet_amount)} {settings.wallet_currency}"
            )
            return
        if settings.real_betting_enabled or settings.bet_require_balance_for_simulation:
            wallet_row = await wallet_service.get_balance(callback.from_user.id)
            balance = Decimal(str(wallet_row.get("balance") or 0))
            if balance < stake_decimal:
                lang = await _callback_lang(callback, database, settings)
                await callback.message.answer(
                    _format_insufficient_balance(stake_decimal, balance, settings.wallet_currency, lang),
                    reply_markup=_insufficient_balance_keyboard(fixture_id, lang),
                )
                return
        stake = str(stake_decimal)
        odds = str(outcome.odds)
        try:
            potential_payout_decimal = (stake_decimal * Decimal(odds)).quantize(Decimal("0.01"))
        except Exception:
            potential_payout_decimal = Decimal("0.00")
        teams = fixture.get("teams", {})
        fixture_label = f"{teams.get('home', {}).get('name', '主队')} vs {teams.get('away', {}).get('name', '客队')}"
        bet_id = await wallet_service.submit_bet(
            user_id=callback.from_user.id,
            fixture_id=fixture_id,
            fixture_label=fixture_label,
            market_key=market_key,
            market_title=getattr(market, "title", market_key),
            selection=_outcome_button_label(outcome),
            odds=odds,
            stake=stake_decimal,
            potential_payout=potential_payout_decimal,
            bettable_status_at_submit=bet_status.reason,
            real_betting_enabled=settings.real_betting_enabled,
            league_name=(fixture.get("league") or {}).get("name"),
            home_team=(fixture.get("teams") or {}).get("home", {}).get("name"),
            away_team=(fixture.get("teams") or {}).get("away", {}).get("name"),
            fixture_start_time=_fixture_start_time(fixture),
        )
        if bet_id is None:
            wallet_row = await wallet_service.get_balance(callback.from_user.id)
            lang = await _callback_lang(callback, database, settings)
            await callback.message.answer(
                _format_insufficient_balance(stake_decimal, Decimal(str(wallet_row.get("balance") or 0)), settings.wallet_currency, lang),
                reply_markup=_insufficient_balance_keyboard(fixture_id, lang),
            )
            return
        bet = await database.get_bet(bet_id)
        lang = await _callback_lang(callback, database, settings)
        await callback.message.answer(
            _format_bet_created(bet or {"id": bet_id}, settings.wallet_currency, lang),
            reply_markup=_bet_action_keyboard(
                str((bet or {}).get("bet_no") or bet_id),
                str((bet or {}).get("status") or "pending"),
                "pending",
                0,
                fixture_id=fixture_id,
                lang=lang,
            ),
        )
        return
        if settings.real_betting_enabled:
            await callback.message.answer(f"下注成功，等待管理员结算。\n注单号：{bet_id}", reply_markup=my_bets_keyboard())
        else:
            await callback.message.answer(format_bet_saved(bet_id), reply_markup=my_bets_keyboard())

    @router.callback_query(F.data == "bet_amount_placeholder")
    async def bet_amount_placeholder(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        await callback.message.answer("第一版固定模拟金额为 $10，暂不修改金额。")

    @router.callback_query(F.data.startswith("bet_amount:"))
    async def bet_amount(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        parts = callback.data.split(":")
        await callback.message.answer(
            "请选择投注金额：",
            reply_markup=bet_amount_keyboard(int(parts[1]), parts[2], int(parts[3]), int(parts[4])),
        )

    @router.callback_query(F.data.startswith("bet_amount_set:"))
    async def bet_amount_set(callback: CallbackQuery, state: FSMContext) -> None:
        await _safe_callback_answer(callback)
        parts = callback.data.split(":")
        fixture_id = int(parts[1])
        market_key = parts[2]
        page = int(parts[3])
        outcome_index = int(parts[4])
        amount = parts[5]
        if amount == "custom":
            await state.clear()
            await state.update_data(fixture_id=fixture_id, market_key=market_key, page=page, outcome_index=outcome_index)
            await state.set_state(BetStates.waiting_custom_stake)
            await callback.message.answer(
                f"请输入投注金额，最低 {_money(settings.min_bet_amount)} USDT。",
                reply_markup=_cancel_keyboard("bets"),
            )
            return
        await _send_bet_confirm_for_amount(
            callback.message,
            fixture_id,
            market_key,
            page,
            outcome_index,
            amount,
            cache,
            api_client,
            settings,
            await _callback_lang(callback, database, settings),
        )

    @router.message(BetStates.waiting_custom_stake, ~F.text.startswith("/"))
    async def bet_custom_stake_input(message: Message, state: FSMContext) -> None:
        if parse_command_name(message.text):
            await state.clear()
            return
        data = await state.get_data()
        try:
            amount = _validated_amount(message.text or "", settings.min_bet_amount, settings.max_bet_amount)
        except ValueError as exc:
            await message.answer(f"{exc}\n请重新输入投注金额，或点击取消。", reply_markup=_cancel_keyboard("bets"))
            return
        await state.clear()
        await _send_bet_confirm_for_amount(
            message,
            int(data["fixture_id"]),
            str(data["market_key"]),
            int(data["page"]),
            int(data["outcome_index"]),
            str(amount),
            cache,
            api_client,
            settings,
            await _event_lang(message, database, settings),
        )

    @router.callback_query(F.data == "bet_placeholder")
    async def bet_placeholder(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        await callback.message.answer("🎯 投注功能即将开放\n当前仅展示赔率，不扣余额，不生成真实注单。")

    @router.message(Command("language"))
    @router.message(F.text.in_({"🌐 " + text for text in _translated_texts("language_settings")}))
    @router.message(F.text.in_(MENU_LANGUAGE_TEXTS))
    @router.callback_query(F.data == "menu:language")
    async def language_settings(event: Message | CallbackQuery) -> None:
        await _answer_callback(event)
        message = _message(event)
        await _remember_chat(message, database)
        lang = await _event_lang(event, database, settings)
        await message.answer(t(lang, "language_prompt"), reply_markup=language_keyboard(lang))

    @router.callback_query(F.data.startswith("lang:"))
    async def set_language(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        lang = callback.data.split(":", 1)[1]
        if lang not in SUPPORTED_LANGUAGES or not callback.from_user:
            return
        await database.set_user_language(callback.from_user.id, lang)
        await callback.message.answer(t(lang, "language_set_en" if lang == "en" else "language_set_zh"))
        await callback.message.answer(t(lang, "start_title"), reply_markup=main_menu_keyboard(lang))

    @router.message(Command("match"))
    async def match(message: Message, command: CommandObject) -> None:
        await _remember_chat(message, database)
        keyword = (command.args or "").strip()
        if not keyword:
            await message.answer("请发送：/match <球队或赛事关键词>")
            return
        leagues = await cache.get_or_set(
            f"search:leagues:{keyword.lower()}",
            300,
            lambda: api_client.search_leagues(keyword),
        )
        teams = await cache.get_or_set(
            f"search:teams:{keyword.lower()}",
            300,
            lambda: api_client.search_teams(keyword),
        )
        await message.answer(format_match_search(teams, leagues, keyword))

    @router.message(Command("search"))
    @router.message(F.text.in_(_translated_texts("search")))
    async def search_hint(message: Message) -> None:
        await message.answer("请发送：/match <球队或赛事关键词>")

    @router.message(Command("subscribe"))
    async def subscribe(message: Message) -> None:
        if message.chat.type not in {"group", "supergroup"}:
            await message.answer("请在群组内使用 /subscribe。")
            return
        await database.set_group_subscription(message.chat, True)
        await message.answer("已订阅重点实时比分播报。")

    @router.message(Command("unsubscribe"))
    async def unsubscribe(message: Message) -> None:
        if message.chat.type not in {"group", "supergroup"}:
            return
        await database.set_group_subscription(message.chat, False)
        await message.answer("已取消重点实时比分播报。")

    @router.message(F.text.in_(_translated_texts("wallet") | MENU_WALLET_TEXTS))
    @router.message(Command("wallet"))
    @router.callback_query(F.data.in_({"wallet", "menu:wallet", "nav:wallet"}))
    async def wallet(event: Message | CallbackQuery) -> None:
        await _answer_callback(event)
        message = _message(event)
        await _remember_user_and_lang(message, database, settings)
        user = event.from_user if isinstance(event, CallbackQuery) else message.from_user
        if not user:
            return
        wallet_row = await wallet_service.get_balance(user.id)
        lang = await _event_lang(event, database, settings)
        await message.answer(_format_wallet(wallet_row, settings.wallet_currency, lang), reply_markup=_wallet_keyboard(lang))

    @router.callback_query(F.data == "wallet:recharge")
    async def wallet_recharge(callback: CallbackQuery, state: FSMContext) -> None:
        await _safe_callback_answer(callback)
        await state.clear()
        await state.set_state(RechargeStates.choosing_amount)
        lang = await _callback_lang(callback, database, settings)
        await callback.message.answer("Please enter deposit amount" if lang == "en" else "请输入充值金额", reply_markup=_recharge_amount_keyboard(lang))

    @router.callback_query(F.data.startswith("wallet:amount:"))
    async def wallet_recharge_amount(callback: CallbackQuery, state: FSMContext) -> None:
        await _safe_callback_answer(callback)
        if not callback.from_user:
            return
        raw_amount = callback.data.rsplit(":", 1)[1]
        if raw_amount == "custom":
            lang = await _callback_lang(callback, database, settings)
            await state.set_state(RechargeStates.waiting_custom_amount)
            await callback.message.answer(
                f"Please enter deposit amount. Min {_money(settings.min_recharge_amount)} USDT, max {_money(settings.max_recharge_amount)} USDT."
                if lang == "en"
                else f"请输入充值金额，最低 {_money(settings.min_recharge_amount)} USDT，最高 {_money(settings.max_recharge_amount)} USDT。",
                reply_markup=_cancel_keyboard("wallet", lang),
            )
            return
        await state.update_data(amount=str(_validated_amount(raw_amount, settings.min_recharge_amount, settings.max_recharge_amount)))
        await state.set_state(RechargeStates.confirming_recharge)
        await callback.message.answer(
            _format_recharge_confirm(await state.get_data(), settings, await _callback_lang(callback, database, settings)),
            reply_markup=_recharge_confirm_keyboard(await _callback_lang(callback, database, settings)),
        )

    @router.message(RechargeStates.waiting_custom_amount, ~F.text.startswith("/"))
    async def recharge_custom_amount_input(message: Message, state: FSMContext) -> None:
        if parse_command_name(message.text):
            await state.clear()
            return
        try:
            amount = _validated_amount(message.text or "", settings.min_recharge_amount, settings.max_recharge_amount)
        except ValueError as exc:
            await message.answer(f"{exc}\n请重新输入充值金额，或点击取消。", reply_markup=_cancel_keyboard("wallet", await _event_lang(message, database, settings)))
            return
        await state.update_data(amount=str(amount))
        await state.set_state(RechargeStates.confirming_recharge)
        await message.answer(
            _format_recharge_confirm(await state.get_data(), settings, await _event_lang(message, database, settings)),
            reply_markup=_recharge_confirm_keyboard(await _event_lang(message, database, settings)),
        )

    @router.callback_query(F.data == "recharge:confirm")
    async def recharge_confirm(callback: CallbackQuery, state: FSMContext) -> None:
        await _safe_callback_answer(callback)
        if not callback.from_user:
            return
        data = await state.get_data()
        try:
            amount = _validated_amount(str(data.get("amount") or ""), settings.min_recharge_amount, settings.max_recharge_amount)
        except ValueError:
            await state.clear()
            await callback.message.answer("充值金额已失效，请重新选择。", reply_markup=_wallet_keyboard(await _callback_lang(callback, database, settings)))
            return
        await _create_recharge_order(
            callback.message,
            callback.from_user.id,
            amount,
            database,
            settings,
            gmpay_client,
            lang=await _callback_lang(callback, database, settings),
        )
        await state.clear()

    @router.callback_query(F.data == "recharge:amounts")
    async def recharge_reselect_amount(callback: CallbackQuery, state: FSMContext) -> None:
        await _safe_callback_answer(callback)
        await state.set_state(RechargeStates.choosing_amount)
        await callback.message.answer("Please enter deposit amount" if await _callback_lang(callback, database, settings) == "en" else "请选择充值金额：", reply_markup=_recharge_amount_keyboard(await _callback_lang(callback, database, settings)))

    @router.message(Command("recharge"))
    async def recharge_custom(message: Message, command: CommandObject) -> None:
        await _remember_user_and_lang(message, database, settings)
        if not message.from_user:
            return
        try:
            amount = Decimal((command.args or "").strip())
        except Exception:
            await message.answer("用法：/recharge <金额>")
            return
        await _create_recharge_order(message, message.from_user.id, amount, database, settings, gmpay_client, lang=await _event_lang(message, database, settings))

    @router.callback_query(F.data == "wallet:records")
    async def wallet_records(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        rows = await database.list_user_deposit_orders(callback.from_user.id, 10)
        await callback.message.answer(_format_deposit_records(rows), reply_markup=_wallet_keyboard(await _callback_lang(callback, database, settings)))

    @router.callback_query(F.data == "wallet:ledger")
    async def wallet_ledger(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        rows = await database.list_user_ledger(callback.from_user.id, 10)
        await callback.message.answer(_format_ledger(rows), reply_markup=_wallet_keyboard(await _callback_lang(callback, database, settings)))

    @router.callback_query(F.data == "wallet:withdraw_prompt")
    async def wallet_withdraw_prompt(callback: CallbackQuery, state: FSMContext) -> None:
        await _safe_callback_answer(callback)
        lang = await _callback_lang(callback, database, settings)
        if not settings.withdraw_enabled:
            await callback.message.answer("Withdrawals are currently unavailable." if lang == "en" else "提现申请功能暂未开放。")
            return
        await state.clear()
        await state.set_state(WithdrawStates.waiting_amount)
        await callback.message.answer(
            f"Please enter withdrawal amount. Min {_money(settings.min_withdraw_amount)} {settings.wallet_currency}."
            if lang == "en"
            else f"请输入提现金额，最低 {_money(settings.min_withdraw_amount)} {settings.wallet_currency}。",
            reply_markup=_cancel_keyboard("wallet", lang),
        )

    @router.message(WithdrawStates.waiting_amount, ~F.text.startswith("/"))
    async def withdraw_amount_input(message: Message, state: FSMContext) -> None:
        if parse_command_name(message.text):
            await state.clear()
            return
        try:
            amount = _validated_amount(message.text or "", settings.min_withdraw_amount, Decimal("999999999"))
        except ValueError as exc:
            await message.answer(f"{exc}\n请重新输入提现金额，或点击取消。", reply_markup=_cancel_keyboard("wallet", await _event_lang(message, database, settings)))
            return
        await state.update_data(amount=str(amount))
        await state.set_state(WithdrawStates.waiting_network)
        lang = await _event_lang(message, database, settings)
        await message.answer("Please select withdrawal network" if lang == "en" else "请选择提现网络：", reply_markup=_network_keyboard("withdraw_network", lang))

    @router.callback_query(F.data.startswith("withdraw_network:"))
    async def withdraw_network(callback: CallbackQuery, state: FSMContext) -> None:
        await _safe_callback_answer(callback)
        network = callback.data.split(":", 1)[1]
        if network == "cancel":
            await state.clear()
            await callback.message.answer("已取消提现申请。", reply_markup=_wallet_keyboard(await _callback_lang(callback, database, settings)))
            return
        await state.update_data(network=network)
        await state.set_state(WithdrawStates.waiting_address)
        lang = await _callback_lang(callback, database, settings)
        await callback.message.answer("Please enter withdrawal address" if lang == "en" else "请输入提现地址", reply_markup=_cancel_keyboard("wallet", lang))

    @router.message(WithdrawStates.waiting_address, ~F.text.startswith("/"))
    async def withdraw_address_input(message: Message, state: FSMContext) -> None:
        if parse_command_name(message.text):
            await state.clear()
            return
        address = (message.text or "").strip()
        if len(address) < 10:
            await message.answer("地址格式看起来不完整，请重新输入。", reply_markup=_cancel_keyboard("wallet", await _event_lang(message, database, settings)))
            return
        await state.update_data(address=address)
        await state.set_state(WithdrawStates.confirming_withdraw)
        await message.answer(
            _format_withdraw_confirm(await state.get_data(), settings.wallet_currency, await _event_lang(message, database, settings)),
            reply_markup=_withdraw_confirm_keyboard(await _event_lang(message, database, settings)),
        )

    @router.callback_query(F.data == "withdraw:confirm")
    async def withdraw_confirm(callback: CallbackQuery, state: FSMContext) -> None:
        await _safe_callback_answer(callback)
        if not callback.from_user:
            return
        data = await state.get_data()
        request = await wallet_service.create_withdraw_request(
            callback.from_user.id,
            Decimal(str(data.get("amount"))),
            str(data.get("address") or ""),
            str(data.get("network") or ""),
        )
        await state.clear()
        if not request:
            lang = await _callback_lang(callback, database, settings)
            await callback.message.answer(t(lang, "insufficient_balance"), reply_markup=_wallet_keyboard(lang))
            return
        await _notify_admins(callback.bot, settings, f"新的提现申请 #{request['id']}，请进入后台审核。")
        lang = await _callback_lang(callback, database, settings)
        await callback.message.answer(
            f"Withdrawal request submitted, waiting for admin review\nRequest ID: {request['id']}"
            if lang == "en"
            else f"提现申请已提交，等待管理员审核。\n申请号：{request['id']}",
            reply_markup=_wallet_keyboard(lang),
        )

    @router.callback_query(F.data == "wallet:withdraw")
    async def wallet_withdraw(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        await callback.message.answer("提现功能暂未自动开放，请等待管理员审核系统上线。")

    @router.message(Command("withdraw"))
    async def withdraw_request(message: Message, command: CommandObject) -> None:
        await _remember_user_and_lang(message, database, settings)
        if not message.from_user:
            return
        if not settings.withdraw_enabled:
            await message.answer("提现申请功能暂未开放。")
            return
        parts = (command.args or "").strip().split(maxsplit=1)
        if len(parts) != 2:
            await message.answer("用法：/withdraw <金额> <USDT-TRC20地址>")
            return
        try:
            amount = Decimal(parts[0])
        except Exception:
            await message.answer("提现金额格式不正确。")
            return
        if amount < settings.min_withdraw_amount:
            await message.answer(f"最低提现金额：{_money(settings.min_withdraw_amount)} {settings.wallet_currency}")
            return
        request = await wallet_service.create_withdraw_request(message.from_user.id, amount, parts[1].strip(), "TRC20")
        if not request:
            await message.answer("余额不足，无法提交提现申请。")
            return
        await message.answer(f"提现申请已提交，等待管理员审核。\n申请号：{request['id']}")

    @router.callback_query(F.data.startswith("deposit:refresh:"))
    async def deposit_refresh(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        order_id = callback.data.rsplit(":", 1)[1]
        order = await database.get_deposit_order(order_id)
        if not order:
            await callback.message.answer("订单不存在。")
            return
        await callback.message.answer(
            _format_deposit_order(order, settings.wallet_currency, await _callback_lang(callback, database, settings)),
            reply_markup=_deposit_order_keyboard(order),
        )

    @router.callback_query(F.data == "menu:bets")
    async def menu_bets(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        if not callback.from_user:
            return
        await _send_bets_page(callback.message, callback.from_user.id, "pending", 0, database, settings)

    @router.callback_query(F.data.startswith("bets:"))
    async def bets_callback(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        if not callback.from_user:
            await callback.message.answer("请先打开机器人后再查看注单。", reply_markup=my_bets_keyboard())
            return
        parts = callback.data.split(":")
        status_group = parts[1] if len(parts) > 1 else "pending"
        page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        await _send_bets_page(callback.message, callback.from_user.id, status_group, page, database, settings)

    @router.message(F.text.in_(_translated_texts("betting_center") | _translated_texts("my_bets") | MENU_BETS_TEXTS))
    @router.message(Command("bets"))
    async def bets(message: Message) -> None:
        await _remember_user_and_lang(message, database, settings)
        if not message.from_user:
            await message.answer("请先打开机器人后再查看注单。", reply_markup=my_bets_keyboard())
            return
        await _send_bets_page(message, message.from_user.id, "pending", 0, database, settings)

    @router.callback_query(F.data.startswith("bet_detail:"))
    async def bet_detail(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        if not callback.from_user:
            return
        parts = callback.data.split(":")
        bet_key = parts[1]
        status_group = parts[2] if len(parts) > 2 else "pending"
        page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        bet = await database.get_user_bet(callback.from_user.id, bet_key)
        if not bet:
            await callback.message.answer("注单不存在。")
            return
        lang = await _callback_lang(callback, database, settings)
        await callback.message.answer(
            _format_bet_detail(bet, settings.wallet_currency, lang),
            reply_markup=_bet_action_keyboard(
                str(bet.get("bet_no") or bet.get("id")),
                str(bet.get("status")),
                status_group,
                page,
                fixture_id=int(bet["fixture_id"]) if bet.get("fixture_id") else None,
                lang=lang,
            ),
        )

    @router.callback_query(F.data.startswith("bet_cancel:"))
    async def bet_cancel(callback: CallbackQuery) -> None:
        if not callback.from_user:
            return
        lang = await _callback_lang(callback, database, settings)
        await callback.answer(
            "Bets are final after confirmation. Cancellation is not supported."
            if lang == "en"
            else "下注确认后买定离手，暂不支持退单。",
            show_alert=True,
        )
        return
        bet_key = _clean_command_token(callback.data.split(":", 1)[1])
        bet = await database.get_user_bet(callback.from_user.id, bet_key)
        if not bet:
            await callback.message.answer("注单不存在。")
            return
        if bet.get("status") != "pending":
            await callback.message.answer("下注确认后买定离手，暂不支持取消。")
            return
        start_time = bet.get("fixture_start_time")
        if isinstance(start_time, datetime) and datetime.now(start_time.tzinfo) >= start_time - timedelta(minutes=settings.bet_cancel_before_start_minutes):
            await callback.message.answer("下注确认后买定离手，暂不支持取消。")
            return
        request = await database.create_cancel_request(callback.from_user.id, int(bet["id"]), "user_request")
        await database.add_admin_audit_log(
            callback.from_user.id,
            "user_cancel_request",
            "bet",
            str(bet.get("bet_no") or bet.get("id")),
            {"cancel_request_id": (request or {}).get("id"), "reason": "user_request"},
        )
        await callback.message.answer("已提交退单申请，需超级管理员审核。审核前注单仍然有效。")
        return
        await _safe_callback_answer(callback)
        if not callback.from_user:
            return
        if not settings.user_cancel_after_confirm_enabled:
            await callback.message.answer("注单已确认，无法自行取消。如需处理，请联系管理员。")
            return
        bet_key = callback.data.split(":", 1)[1]
        bet = await database.get_user_bet(callback.from_user.id, bet_key)
        if not bet or bet.get("status") != "pending":
            await callback.message.answer("本单已进入结算阶段，无法删除。")
            return
        start_time = bet.get("fixture_start_time")
        if isinstance(start_time, datetime) and datetime.now(start_time.tzinfo) >= start_time - timedelta(minutes=settings.bet_cancel_before_start_minutes):
            await callback.message.answer("本单已进入结算阶段，无法删除。")
            return
        row = await wallet_service.cancel_bet(int(bet["id"]), callback.from_user.id, real_betting_enabled=settings.real_betting_enabled)
        await callback.message.answer(
            f"注单已取消\n\n注单号：{bet.get('bet_no') or bet.get('id')}\n状态：已取消" if row else "本单已进入结算阶段，无法删除。"
        )

    @router.callback_query(F.data.startswith("bet_settle:"))
    async def bet_settle(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        if not callback.from_user:
            return
        bet_key = callback.data.split(":", 1)[1]
        bet = await database.get_user_bet(callback.from_user.id, bet_key)
        if not bet or bet.get("status") != "pending":
            await callback.message.answer("该注单无需结算或不存在。")
            return
        try:
            fixture = await api_client.get_fixture_detail(int(bet["fixture_id"]))
        except Exception:
            await callback.message.answer("赛果暂未确认，请稍后再试。")
            return
        result = await settlement_service.settle_bet_from_fixture(bet, fixture, source="auto")
        if result.get("settled"):
            fresh = await database.get_user_bet(callback.from_user.id, bet_key)
            detail = fresh or bet
            lang = await _callback_lang(callback, database, settings)
            await callback.message.answer(
                _format_bet_detail(detail, settings.wallet_currency, lang),
                reply_markup=_bet_action_keyboard(
                    str(detail.get("bet_no") or detail.get("id")),
                    str(detail.get("status")),
                    fixture_id=int(detail["fixture_id"]) if detail.get("fixture_id") else None,
                    lang=lang,
                ),
            )
        elif result.get("reason") == "not_final":
            await callback.message.answer("比赛尚未结束，系统将在赛果确认后自动结算。")
        elif result.get("reason") == "unsupported_market":
            await callback.message.answer("该玩法需要人工结算，系统会尽快处理。")
        else:
            await callback.message.answer("赛果暂未确认，请稍后再试。")

    @router.message(F.text.in_(_translated_texts("referrals") | MENU_REFERRALS_TEXTS))
    @router.message(Command("referrals"))
    @router.callback_query(F.data.in_({"referral", "referrals", "menu:referrals", "nav:referrals"}))
    async def referrals(event: Message | CallbackQuery) -> None:
        await _answer_callback(event)
        message = _message(event)
        await _remember_user_and_lang(message, database, settings)
        user = event.from_user if isinstance(event, CallbackQuery) else message.from_user
        if not user:
            return
        code = await database.get_referral_code(user.id)
        bot_info = await message.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start=ref_{code}"
        summary = await database.get_referral_summary(user.id)
        role = await permission_service.get_user_role(user.id)
        application = await database.get_latest_agent_application(user.id)
        lang = await _event_lang(event, database, settings)
        await message.answer(
            _format_referrals(link, summary, settings.wallet_currency, role, application, lang),
            reply_markup=_referral_keyboard(role, application, lang),
        )

    @router.callback_query(F.data == "referrals:children")
    async def referral_children(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        rows = await database.list_referrals(callback.from_user.id, 20)
        await callback.message.answer(_format_referral_children(rows), reply_markup=_referral_keyboard())

    @router.callback_query(F.data == "referrals:commissions")
    async def referral_commissions(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        rows = await database.list_commissions(callback.from_user.id, 20)
        await callback.message.answer(_format_commissions(rows), reply_markup=_referral_keyboard())

    @router.callback_query(F.data == "referrals:rebates")
    async def referral_rebates(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        rows = await database.list_rebate_records(callback.from_user.id, 20)
        await callback.message.answer(_format_rebates(rows), reply_markup=_referral_keyboard())

    @router.callback_query(F.data == "referrals:rebate_apply")
    async def rebate_apply(callback: CallbackQuery, state: FSMContext) -> None:
        await _safe_callback_answer(callback)
        if not callback.from_user:
            return
        if not settings.rebate_request_enabled:
            await callback.message.answer("返水申请暂未开放。", reply_markup=_referral_keyboard())
            return
        await state.clear()
        await state.set_state(RebateStates.waiting_note)
        await callback.message.answer(
            "请输入你的返水申请说明，例如：\n本周投注较多，希望申请返水。",
            reply_markup=_cancel_keyboard("referrals"),
        )

    @router.message(RebateStates.waiting_note, ~F.text.startswith("/"))
    async def rebate_note_input(message: Message, state: FSMContext) -> None:
        if not message.from_user:
            return
        if parse_command_name(message.text):
            await state.clear()
            return
        role = await permission_service.get_user_role(message.from_user.id)
        if role == "super_admin":
            await state.clear()
            return
        note = (message.text or "").strip()
        if len(note) < 2:
            await message.answer("申请说明太短，请重新输入。", reply_markup=_cancel_keyboard("referrals"))
            return
        snapshot = await database.get_agent_rebate_snapshot(message.from_user.id)
        await state.update_data(
            note=note,
            turnover=str(snapshot.get("claimable_stake") or "0"),
            active_referrals=0,
            rebate_rate=str(snapshot.get("rebate_rate") or "0"),
            rebate_amount=str(snapshot.get("claimable_rebate") or "0"),
        )
        await state.set_state(RebateStates.confirming_request)
        await message.answer(_format_rebate_confirm(await state.get_data()), reply_markup=_rebate_confirm_keyboard())

    @router.callback_query(F.data == "rebate:confirm")
    async def rebate_confirm(callback: CallbackQuery, state: FSMContext) -> None:
        await _safe_callback_answer(callback)
        if not callback.from_user:
            return
        data = await state.get_data()
        row = await database.create_agent_rebate_request(callback.from_user.id, str(data.get("note") or "agent rebate request"))
        await state.clear()
        lang = await _callback_lang(callback, database, settings)
        if not row:
            await callback.message.answer(t(lang, "rebate_no_claimable"), reply_markup=_referral_keyboard())
            return
        await _notify_super_admins_rebate(callback.bot, database, settings, row)
        await callback.message.answer(t(lang, "rebate_submitted", id=row["id"]), reply_markup=_referral_keyboard())

    @router.callback_query(F.data == "referrals:agent_apply")
    async def agent_apply(callback: CallbackQuery, state: FSMContext) -> None:
        await _safe_callback_answer(callback)
        if not callback.from_user:
            return
        role = await permission_service.get_user_role(callback.from_user.id)
        if role in {"agent", "admin", "super_admin"}:
            await callback.message.answer(f"当前身份：{_role_label(role)}，无需重复申请代理。", reply_markup=_referral_keyboard(role))
            return
        application = await database.get_latest_agent_application(callback.from_user.id)
        if application and str(application.get("status")) == "pending":
            await callback.message.answer("代理申请审核中，请勿重复提交。", reply_markup=_referral_keyboard(role, application))
            return
        metrics = await database.get_agent_application_metrics(callback.from_user.id)
        ok = (
            Decimal(str(metrics.get("total_deposit") or 0)) >= settings.agent_min_total_deposit
            and Decimal(str(metrics.get("total_turnover") or 0)) >= settings.agent_min_total_turnover
            and int(metrics.get("valid_referrals") or 0) >= settings.agent_min_valid_referrals
        )
        if not ok:
            await callback.message.answer(_format_agent_progress(metrics, settings), reply_markup=_referral_keyboard())
            return
        await state.clear()
        await state.update_data(metrics=metrics)
        await state.set_state(AgentApplicationStates.waiting_note)
        await callback.message.answer("请输入代理申请说明。", reply_markup=_cancel_keyboard("referrals"))

    @router.callback_query(F.data == "referrals:agent_pending")
    async def agent_pending(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        await callback.message.answer("代理申请审核中，请等待管理员处理。")

    @router.message(AgentApplicationStates.waiting_note, ~F.text.startswith("/"))
    async def agent_note_input(message: Message, state: FSMContext) -> None:
        if not message.from_user:
            return
        if parse_command_name(message.text):
            await state.clear()
            return
        note = (message.text or "").strip()
        if len(note) < 2:
            await message.answer("申请说明太短，请重新输入。", reply_markup=_cancel_keyboard("referrals"))
            return
        metrics = await database.get_agent_application_metrics(message.from_user.id)
        row = await database.create_agent_application(
            message.from_user.id,
            Decimal(str(metrics.get("total_deposit") or "0")),
            Decimal(str(metrics.get("total_turnover") or "0")),
            int(metrics.get("valid_referrals") or 0),
            note,
        )
        await state.clear()
        await _notify_admins(message.bot, settings, f"新的代理申请 #{row['id']}，请超级管理员审核。")
        await message.answer(f"代理申请已提交，状态：pending。\n申请号：{row['id']}", reply_markup=_referral_keyboard())

    @router.callback_query(F.data == "referrals:copy")
    async def referral_copy(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        code = await database.get_referral_code(callback.from_user.id)
        bot_info = await callback.bot.get_me()
        await callback.message.answer(f"https://t.me/{bot_info.username}?start=ref_{code}")

    @router.callback_query(F.data.in_({"referrals:sub_deposits", "referrals:sub_bets", "referrals:sub_rebates"}))
    async def referral_agent_views(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        if not callback.from_user:
            return
        role = await permission_service.get_user_role(callback.from_user.id)
        if role not in {"agent", "admin", "super_admin"}:
            await callback.message.answer("无代理或管理员权限。", reply_markup=_referral_keyboard(role))
            return
        summary = await database.get_referral_summary(callback.from_user.id)
        title = {
            "referrals:sub_deposits": "下级充值",
            "referrals:sub_bets": "下级投注",
            "referrals:sub_rebates": "下级返水",
        }.get(callback.data, "下级数据")
        text = (
            f"{title}\n\n"
            f"直属下级：{summary.get('direct_count') or 0} 人\n"
            f"有效下级：{summary.get('active_count') or 0} 人\n"
            f"下级累计充值：{_money(summary.get('total_deposit'))} {settings.wallet_currency}\n"
            f"下级累计投注：{_money(summary.get('total_turnover'))} {settings.wallet_currency}\n"
            f"待结算返水：{_money(summary.get('pending_rebate'))} {settings.wallet_currency}"
        )
        await callback.message.answer(text, reply_markup=_referral_keyboard(role))

    @router.message(F.text.in_(_translated_texts("settings") | MENU_SETTINGS_TEXTS))
    @router.message(Command("settings"))
    @router.callback_query(F.data == "menu:settings")
    async def settings_command(event: Message | CallbackQuery) -> None:
        await language_settings(event)

    @router.message(Command("whoami"))
    async def whoami(message: Message) -> None:
        if not message.from_user:
            return
        role = await permission_service.get_user_role(message.from_user.id)
        await message.answer(f"Telegram ID: {message.from_user.id}\nrole: {role}")

    @router.message(Command("admin"))
    @router.callback_query(F.data == "menu:admin")
    async def admin_entry(event: Message | CallbackQuery) -> None:
        await _answer_callback(event)
        message = _message(event)
        user_id = event.from_user.id if isinstance(event, CallbackQuery) and event.from_user else (message.from_user.id if message.from_user else None)
        if not settings.super_admin_user_ids:
            await message.answer("未配置超级管理员，请在 .env 设置 SUPER_ADMIN_USER_IDS。")
            return
        role = await permission_service.get_user_role(user_id)
        if role not in {"super_admin", "admin", "agent"}:
            await message.answer("无管理员权限。")
            return
        lang = await _event_lang(event, database, settings)
        await message.answer(_admin_menu_text(role, lang), reply_markup=_admin_panel_keyboard(role, lang))

    @router.message(Command("admin"))
    async def admin(message: Message) -> None:
        if not _is_admin(message.from_user.id if message.from_user else None, settings):
            await message.answer("无管理员权限。")
            return
        await message.answer(
            "管理员命令：\n"
            "/admin_stats\n"
            "/admin_markets\n"
            "/admin_suspend <fixture_id>\n"
            "/admin_resume <fixture_id>\n"
            "/admin_set_cutoff <minutes>\n"
            "/admin_wallet <telegram_user_id>\n"
            "/admin_deposits\n"
            "/admin_deposit <order_id>\n"
            "/admin_mark_deposit_paid <order_id> <amount> <txid> <reason>\n"
            "/admin_reject_deposit <order_id> <reason>\n"
            "/admin_clear_my_test_bets\n"
            "/admin_clear_user_test_bets <telegram_user_id>\n"
            "/admin_adjust_balance <telegram_user_id> <amount> <reason>\n"
            "/admin_bets\n"
            "/admin_bet <bet_id>\n"
            "/admin_settle_win <bet_id>\n"
            "/admin_settle_loss <bet_id>\n"
            "/admin_settle_void <bet_id>\n"
            "/admin_cancel_bet <bet_id>\n"
            "/admin_withdrawals\n"
            "/admin_withdraw <withdraw_id>\n"
            "/admin_approve_withdraw <withdraw_id>\n"
            "/admin_reject_withdraw <withdraw_id> <reason>\n"
            "/admin_mark_withdraw_paid <withdraw_id> <txid>\n"
            "/admin_commissions\n"
            "/admin_settle_commission <commission_id>\n"
            "/admin_rebate_rules\n"
            "/admin_rebate_preview <user_id>\n"
            "/admin_generate_rebates\n"
            "/admin_settle_rebate <rebate_record_id>\n"
            "/admin_referrals <telegram_user_id>"
        )

    @router.message(Command("admin_stats"))
    async def admin_stats(message: Message) -> None:
        if not _is_admin(message.from_user.id if message.from_user else None, settings):
            await message.answer("无管理员权限。")
            return
        dashboard = await database.admin_dashboard()
        fixtures = [None] * int(dashboard.get("pending_bets") or 0)
        effective_settings = settings
        await message.answer(_format_admin_dashboard(dashboard, settings.wallet_currency))
        return
        await message.answer(f"当前可投注赛事：{len(fixtures)} 场\n封盘提前：{effective_settings.bet_cutoff_minutes} 分钟")

    @router.message(Command("admin_markets"))
    async def admin_markets(message: Message) -> None:
        if not await _require_super_admin(message):
            return
        if not _is_admin(message.from_user.id if message.from_user else None, settings):
            await message.answer("无管理员权限。")
            return
        effective_settings = await _effective_settings(cache, settings)
        fixtures, _ = await get_bettable_matches_range(cache, api_client, database, effective_settings)
        lines = ["当前可投注赛事："]
        for item in fixtures[:effective_settings.max_bettable_matches]:
            fixture_id = item.get("fixture", {}).get("id")
            teams = item.get("teams", {})
            lines.append(f"{fixture_id} {teams.get('home', {}).get('name', '主队')} vs {teams.get('away', {}).get('name', '客队')}")
        await message.answer("\n".join(lines) if len(lines) > 1 else "当前暂无可投注赛事。")

    @router.message(Command("admin_suspend"))
    async def admin_suspend(message: Message, command: CommandObject) -> None:
        if not await _require_super_admin(message):
            return
        if not _is_admin(message.from_user.id if message.from_user else None, settings):
            await message.answer("无管理员权限。")
            return
        fixture_id = _command_fixture_id(command)
        if fixture_id is None:
            await message.answer("用法：/admin_suspend <fixture_id>")
            return
        await database.set_market_suspended(fixture_id, True, message.from_user.id, "admin_suspend")
        await message.answer(f"已封盘 fixture_id={fixture_id}")

    @router.message(Command("admin_resume"))
    async def admin_resume(message: Message, command: CommandObject) -> None:
        if not await _require_super_admin(message):
            return
        if not _is_admin(message.from_user.id if message.from_user else None, settings):
            await message.answer("无管理员权限。")
            return
        fixture_id = _command_fixture_id(command)
        if fixture_id is None:
            await message.answer("用法：/admin_resume <fixture_id>")
            return
        await database.set_market_suspended(fixture_id, False, message.from_user.id, "admin_resume")
        await message.answer(f"已恢复 fixture_id={fixture_id}")

    @router.message(Command("admin_set_cutoff"))
    async def admin_set_cutoff(message: Message, command: CommandObject) -> None:
        if not await _require_super_admin(message):
            return
        if not _is_admin(message.from_user.id if message.from_user else None, settings):
            await message.answer("无管理员权限。")
            return
        try:
            minutes = int((command.args or "").strip())
        except ValueError:
            await message.answer("用法：/admin_set_cutoff <minutes>")
            return
        await cache.set_text("football:admin:bet_cutoff_minutes", str(max(minutes, 0)))
        await message.answer(f"已设置封盘提前 {max(minutes, 0)} 分钟（当前进程内生效）。")

    @router.message(Command("admin_wallet"))
    async def admin_wallet(message: Message, command: CommandObject) -> None:
        if not await _require_super_admin(message):
            return
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        user_id = _first_int_arg(command)
        if user_id is None:
            await message.answer("用法：/admin_wallet <telegram_user_id>")
            return
        wallet_row = await wallet_service.get_balance(user_id)
        summary = await database.get_referral_summary(user_id)
        await message.answer(_format_wallet(wallet_row, settings.wallet_currency) + "\n\n" + _format_admin_referral_summary(summary, settings.wallet_currency))

    @router.message(Command("admin_deposits"))
    async def admin_deposits(message: Message) -> None:
        if not await _require_super_admin(message):
            return
        if not _admin_private_allowed(message, settings) or not await permission_service.can_review_deposits(message.from_user.id):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        await message.answer(_format_deposit_records(await database.list_deposit_orders(20)))

    @router.message(Command("admin_deposit"))
    async def admin_deposit(message: Message, command: CommandObject) -> None:
        if not await _require_super_admin(message):
            return
        if not _admin_private_allowed(message, settings) or not await permission_service.can_review_deposits(message.from_user.id):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        order_id = (command.args or "").strip()
        if not order_id:
            await message.answer("用法：/admin_deposit <order_id>")
            return
        order = await database.get_deposit_order(order_id)
        await message.answer(_format_admin_deposit_order(order) if order else "订单不存在。")

    @router.message(Command("admin_mark_deposit_paid"))
    async def admin_mark_deposit_paid(message: Message, command: CommandObject) -> None:
        if not await _require_super_admin(message):
            return
        if not _admin_private_allowed(message, settings) or not await permission_service.can_review_deposits(message.from_user.id):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        parts = (command.args or "").strip().split(maxsplit=3)
        logger.info(
            "admin_command command_name=admin_mark_deposit_paid telegram_user_id=%s parsed_args=%s",
            message.from_user.id if message.from_user else None,
            {"argc": len(parts), "order_id": parts[0] if parts else None},
        )
        if len(parts) != 4:
            await message.answer("用法：/admin_mark_deposit_paid <order_id> <amount> <txid> <reason>")
            return
        order_id, amount_text, txid, reason = parts
        try:
            amount = Decimal(amount_text)
        except Exception:
            await message.answer("金额格式不正确。")
            return
        if amount <= 0 or not txid.strip() or not reason.strip():
            await message.answer("amount、txid 和 reason 都必须填写。")
            return
        order = await database.get_deposit_order(order_id)
        if not order:
            logger.info(
                "admin_command_result command_name=admin_mark_deposit_paid telegram_user_id=%s result=failure reason=order_not_found order_id=%s",
                message.from_user.id if message.from_user else None,
                order_id,
            )
            await message.answer("未找到充值订单。")
            return
        if not order:
            await message.answer("订单不存在。")
            return
        if str(order.get("status")) == "paid":
            await message.answer("订单已入账，不能重复入账。")
            return
        if str(order.get("status")) not in {"manual_review", "pending", "failed", "rejected"}:
            await message.answer("该订单状态不允许人工入账。")
            return
            await message.answer("该订单状态不允许人工标记到账。")
            return
        paid = await wallet_service.credit_deposit(
            int(order["user_id"]),
            order,
            {
                "actual_amount": amount,
                "trade_id": txid,
                "chain_tx_id": txid,
                "txid": txid,
                "manual_review_note": reason,
                "admin_user_id": message.from_user.id,
            },
            ledger_type="deposit_manual",
            description=f"Manual deposit: {reason}",
        )
        await database.add_admin_audit_log(
            message.from_user.id,
            "admin_mark_deposit_paid",
            "deposit_order",
            order_id,
            {"paid": paid, "amount": str(amount), "txid": txid, "reason": reason},
        )
        if paid:
            ledger_id = await database.pool.fetchval(
                """
                SELECT id FROM wallet_ledger
                WHERE ref_type = 'deposit_order' AND ref_id = $1 AND type = 'deposit_manual'
                ORDER BY id DESC
                LIMIT 1
                """,
                order_id,
            )
            try:
                await message.bot.send_message(
                    int(order["user_id"]),
                    f"充值人工核查已通过，已到账：{_money(amount)} {settings.wallet_currency}\n订单号：{order_id}",
                )
            except Exception:
                logger.info("failed to notify manual deposit paid user_id=%s order_id=%s", order["user_id"], order_id, exc_info=True)
            logger.info(
                "admin_command_result command_name=admin_mark_deposit_paid telegram_user_id=%s result=success order_id=%s target_user_id=%s ledger_id=%s",
                message.from_user.id if message.from_user else None,
                order_id,
                order["user_id"],
                ledger_id,
            )
            await message.answer(f"人工入账完成，ledger_id={ledger_id}")
            return
        logger.info(
            "admin_command_result command_name=admin_mark_deposit_paid telegram_user_id=%s result=failure reason=not_processed order_id=%s",
            message.from_user.id if message.from_user else None,
            order_id,
        )
        await message.answer("订单未处理，可能已入账或存在重复 txid。")
        return
        await message.answer("已人工标记充值到账。" if paid else "订单未处理，可能已到账或存在重复 txid。")

    @router.message(Command("admin_reject_deposit"))
    async def admin_reject_deposit(message: Message, command: CommandObject) -> None:
        if not await _require_super_admin(message):
            return
        if not _admin_private_allowed(message, settings) or not await permission_service.can_review_deposits(message.from_user.id):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        parts = (command.args or "").strip().split(maxsplit=1)
        if len(parts) != 2:
            await message.answer("用法：/admin_reject_deposit <order_id> <reason>")
            return
        order_id, reason = parts
        if not reason.strip():
            await message.answer("reason 必须填写。")
            return
        row = await database.reject_deposit_order(order_id, reason=reason, admin_user_id=message.from_user.id)
        if row:
            try:
                await message.bot.send_message(
                    int(row["user_id"]),
                    f"充值订单人工核查未通过。\n订单号：{order_id}\n原因：{reason}",
                )
            except Exception:
                logger.info("failed to notify deposit rejection user_id=%s order_id=%s", row["user_id"], order_id, exc_info=True)
        await message.answer("已拒绝充值订单。" if row else "订单不存在或已到账，无法拒绝。")

    @router.message(Command("admin_adjust_balance"))
    async def admin_adjust_balance(message: Message, command: CommandObject, state: FSMContext) -> None:
        await state.clear()
        if not await _require_super_admin(message):
            return
        try:
            target_user_id, amount, reason = parse_admin_adjust_args(command.args)
        except ValueError as exc:
            logger.info(
                "admin_command_result command_name=admin_adjust_balance telegram_user_id=%s result=failure reason=%s",
                message.from_user.id if message.from_user else None,
                str(exc),
            )
            await message.answer("用法：/admin_adjust_balance <telegram_user_id> <amount> <reason>")
            return
        logger.info(
            "admin_command command_name=admin_adjust_balance telegram_user_id=%s parsed_args=%s",
            message.from_user.id if message.from_user else None,
            {"target_user_id": target_user_id, "amount": str(amount)},
        )
        if amount == 0:
            await message.answer("调整金额不能为 0。")
            return
        try:
            ledger = await wallet_service.manual_adjust(target_user_id, amount, reason, message.from_user.id)
        except ValueError:
            logger.info(
                "admin_command_result command_name=admin_adjust_balance telegram_user_id=%s result=failure reason=insufficient_balance target_user_id=%s",
                message.from_user.id if message.from_user else None,
                target_user_id,
            )
            await message.answer("余额不足，不能扣成负数。")
            return
        except Exception:
            logger.info(
                "admin_command_result command_name=admin_adjust_balance telegram_user_id=%s result=failure reason=exception target_user_id=%s",
                message.from_user.id if message.from_user else None,
                target_user_id,
                exc_info=True,
            )
            await message.answer("调账失败，请查看后台日志。")
            return
        await database.add_admin_audit_log(
            message.from_user.id,
            "admin_adjust_balance",
            "wallet",
            str(target_user_id),
            {"amount": str(amount), "reason": reason, "ledger_id": ledger["id"]},
        )
        logger.info(
            "admin_command_result command_name=admin_adjust_balance telegram_user_id=%s result=success target_user_id=%s ledger_id=%s",
            message.from_user.id if message.from_user else None,
            target_user_id,
            ledger["id"],
        )
        await state.clear()
        await message.answer(f"调整完成，ledger_id={ledger['id']}")
        return
        parts = (command.args or "").strip().split(maxsplit=2)
        if len(parts) != 3:
            await message.answer("用法：/admin_adjust_balance <telegram_user_id> <amount> <reason>")
            return
        try:
            target_user_id = int(_clean_command_token(parts[0]))
            amount = Decimal(parts[1])
        except Exception:
            await message.answer("参数格式错误：telegram_user_id 必须是数字，amount 必须是数字。")
            return
        if amount == 0:
            await message.answer("调整金额不能为 0。")
            return
        try:
            ledger = await wallet_service.manual_adjust(target_user_id, amount, parts[2], message.from_user.id)
        except ValueError:
            await message.answer("余额不足，不能扣成负数。")
            return
        await database.add_admin_audit_log(
            message.from_user.id,
            "admin_adjust_balance",
            "wallet",
            str(target_user_id),
            {"amount": str(amount), "reason": parts[2], "ledger_id": ledger["id"]},
        )
        await state.clear()
        await message.answer(f"调整完成，ledger_id={ledger['id']}")
        return
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        if not await permission_service.is_super_admin(message.from_user.id):
            await message.answer("只有超级管理员可以调账。")
            return
        await state.clear()
        parts = (command.args or "").strip().split(maxsplit=2)
        if len(parts) < 3:
            await state.clear()
            await state.set_state(AdminAdjustStates.waiting_user)
            await message.answer("请输入要调账的用户 Telegram ID：", reply_markup=_cancel_keyboard("admin"))
            return
            await message.answer("用法：/admin_adjust_balance <telegram_user_id> <amount> <reason>")
            return
        try:
            target_user_id = int(parts[0])
            amount = Decimal(parts[1])
        except Exception:
            await message.answer("用法：/admin_adjust_balance <telegram_user_id> <amount> <reason>")
            return
        try:
            ledger = await wallet_service.manual_adjust(target_user_id, amount, parts[2], message.from_user.id)
        except ValueError:
            await state.clear()
            await message.answer("余额不足，不能扣成负数。")
            return
        await database.add_admin_audit_log(
            message.from_user.id,
            "admin_adjust_balance",
            "wallet",
            str(target_user_id),
            {"amount": str(amount), "reason": parts[2], "ledger_id": ledger["id"]},
        )
        await message.answer(f"调整完成，ledger_id={ledger['id']}")

    @router.message(AdminAdjustStates.waiting_user, ~F.text.startswith("/"))
    async def admin_adjust_user_input(message: Message, state: FSMContext) -> None:
        if parse_command_name(message.text):
            await state.clear()
            return
        if not message.from_user or not await permission_service.is_super_admin(message.from_user.id):
            return
        try:
            target_user_id = int((message.text or "").strip())
        except ValueError:
            await message.answer("请输入数字 Telegram ID。", reply_markup=_cancel_keyboard("admin"))
            return
        await state.update_data(target_user_id=target_user_id)
        await state.set_state(AdminAdjustStates.waiting_amount)
        await message.answer("请输入调整金额，正数加钱，负数扣钱：", reply_markup=_cancel_keyboard("admin"))

    @router.message(AdminAdjustStates.waiting_amount, ~F.text.startswith("/"))
    async def admin_adjust_amount_input(message: Message, state: FSMContext) -> None:
        if parse_command_name(message.text):
            await state.clear()
            return
        try:
            amount = Decimal((message.text or "").strip())
        except Exception:
            await message.answer("金额格式不正确，请重新输入。", reply_markup=_cancel_keyboard("admin"))
            return
        if amount == 0:
            await message.answer("调账金额不能为 0。", reply_markup=_cancel_keyboard("admin"))
            return
        await state.update_data(amount=str(amount))
        await state.set_state(AdminAdjustStates.waiting_reason)
        await message.answer("请输入调账原因：", reply_markup=_cancel_keyboard("admin"))

    @router.message(AdminAdjustStates.waiting_reason, ~F.text.startswith("/"))
    async def admin_adjust_reason_input(message: Message, state: FSMContext) -> None:
        if parse_command_name(message.text):
            await state.clear()
            return
        reason = (message.text or "").strip()
        if len(reason) < 3:
            await message.answer("必须填写明确调账原因。", reply_markup=_cancel_keyboard("admin"))
            return
        await state.update_data(reason=reason)
        await state.set_state(AdminAdjustStates.confirming_adjustment)
        await message.answer(_format_admin_adjust_confirm(await state.get_data()), reply_markup=_admin_adjust_confirm_keyboard())

    @router.callback_query(F.data == "admin_adjust:confirm")
    async def admin_adjust_confirm(callback: CallbackQuery, state: FSMContext) -> None:
        await _safe_callback_answer(callback)
        if not callback.from_user or not await permission_service.is_super_admin(callback.from_user.id):
            return
        data = await state.get_data()
        target_user_id = int(data["target_user_id"])
        amount = Decimal(str(data["amount"]))
        reason = str(data["reason"])
        ledger = await wallet_service.manual_adjust(target_user_id, amount, reason, callback.from_user.id)
        await database.add_admin_audit_log(
            callback.from_user.id,
            "admin_adjust_balance",
            "wallet",
            str(target_user_id),
            {"amount": str(amount), "reason": reason, "ledger_id": ledger["id"]},
        )
        await state.clear()
        await callback.message.answer(f"调账完成，ledger_id={ledger['id']}")

    @router.message(Command("admin_commissions"))
    async def admin_commissions(message: Message) -> None:
        if message.chat.type != "private" or not message.from_user:
            await message.answer("当前权限不足，请联系超级管理员。")
            return
        role = await permission_service.get_user_role(message.from_user.id)
        if role not in {"super_admin", "admin", "agent"}:
            await message.answer("当前权限不足，请联系超级管理员。")
            return
        user_scope = None if role in {"super_admin", "admin"} else message.from_user.id
        await message.answer(_format_commissions(await database.list_commissions(user_scope, 20)))
        return
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        await message.answer(_format_commissions(await database.list_commissions(None, 20)))

    @router.message(Command("admin_settle_commission"))
    async def admin_settle_commission(message: Message, command: CommandObject) -> None:
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        commission_id = _first_int_arg(command)
        if commission_id is None:
            await message.answer("用法：/admin_settle_commission <commission_id>")
            return
        record = await database.settle_commission(commission_id)
        await database.add_admin_audit_log(
            message.from_user.id,
            "admin_settle_commission",
            "commission",
            str(commission_id),
            {"settled": bool(record)},
        )
        await message.answer("返佣已标记结算。" if record else "返佣不存在或已处理。")

    @router.message(Command("admin_bets"))
    async def admin_bets(message: Message) -> None:
        if not await _require_super_admin(message):
            return
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        await message.answer(_format_admin_bets(await database.list_admin_bets("pending", 20)))

    @router.message(Command("admin_bet"))
    async def admin_bet(message: Message, command: CommandObject) -> None:
        if not await _require_private_role(message, {"super_admin", "admin"}):
            return
        bet_key = (command.args or "").strip().split(maxsplit=1)[0] if (command.args or "").strip() else ""
        if not bet_key:
            await message.answer("用法：/admin_bet <注单号或ID>")
            return
        try:
            bet = await resolve_bet_by_id_or_no(database, bet_key)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        logger.info(
            "admin_command command_name=admin_bet telegram_user_id=%s parsed_args=%s resolved_target_id=%s result=%s",
            message.from_user.id if message.from_user else None,
            {"bet_key": clean_command_token(bet_key)},
            (bet or {}).get("id"),
            "success" if bet else "failure",
        )
        if not bet:
            await message.answer(f"未找到该注单：{clean_command_token(bet_key)}\n请使用 /admin_bets 查看待开奖注单。")
            return
        await message.answer(_format_admin_bet(bet))
        return
        bet_key = _clean_command_token((command.args or "").strip().split(maxsplit=1)[0]) if (command.args or "").strip() else ""
        if not bet_key:
            await message.answer("用法：/admin_bet <注单号或ID>")
            return
        bet = await database.get_bet(bet_key)
        if not bet:
            await message.answer(f"未找到该注单：{bet_key}\n请使用 /admin_bets 查看待开奖注单。")
            return
        await message.answer(_format_admin_bet(bet))
        return
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        bet_key = (command.args or "").strip().split(maxsplit=1)[0] if (command.args or "").strip() else ""
        if not bet_key:
            await message.answer("用法：/admin_bet <bet_no_or_id>")
            return
        await message.answer(_format_admin_bet(await database.get_bet(bet_key)))
        return
        parts = (command.args or "").strip().split(maxsplit=1)
        bet_key = parts[0] if parts else ""
        note = parts[1] if len(parts) > 1 else None
        if not bet_key:
            await message.answer(f"用法：/{action} <bet_no_or_id>")
            return
        bet = await database.get_bet(bet_key)
        if not bet:
            await message.answer("未找到该注单，请检查注单号。")
            return
        bet_id = int(bet["id"])
        try:
            result = await wallet_service.settle_bet(bet_id, message.from_user.id, status, note=note)
        except ValueError as exc:
            await message.answer(f"结算失败：{exc}")
            return
        await database.add_admin_audit_log(
            message.from_user.id,
            action,
            "bet",
            str(bet.get("bet_no") or bet_id),
            {"status": status, "settled": bool(result), "note": note},
        )
        await message.answer(f"注单已开奖：{status}" if result else "注单不存在、已开奖或状态不允许。")
        return
        bet_id = _first_int_arg(command)
        if bet_id is None:
            await message.answer("用法：/admin_bet <bet_id>")
            return
        await message.answer(_format_admin_bet(await database.get_bet(bet_id)))

    async def _admin_settle_bet(message: Message, command: CommandObject, status: str, action: str) -> None:
        if not await _require_super_admin(message):
            return
        parts = (command.args or "").strip().split(maxsplit=1)
        bet_key = parts[0] if parts else ""
        note = parts[1].strip() if len(parts) > 1 else None
        if not bet_key:
            await message.answer(f"用法：/{action} <注单号或ID>")
            return
        try:
            bet = await resolve_bet_by_id_or_no(database, bet_key)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        logger.info(
            "admin_command command_name=%s telegram_user_id=%s parsed_args=%s resolved_target_id=%s",
            action,
            message.from_user.id if message.from_user else None,
            {"bet_key": clean_command_token(bet_key), "status": status, "has_note": bool(note)},
            (bet or {}).get("id"),
        )
        if not bet:
            logger.info(
                "admin_command_result command_name=%s telegram_user_id=%s result=failure reason=bet_not_found bet_key=%s",
                action,
                message.from_user.id if message.from_user else None,
                clean_command_token(bet_key),
            )
            await message.answer(f"未找到该注单：{clean_command_token(bet_key)}\n请使用 /admin_bets 查看待开奖注单。")
            return
        if str(bet.get("status")) not in {"pending", "manual_required"}:
            logger.info(
                "admin_command_result command_name=%s telegram_user_id=%s result=failure reason=already_processed resolved_target_id=%s current_status=%s",
                action,
                message.from_user.id if message.from_user else None,
                bet.get("id"),
                bet.get("status"),
            )
            await message.answer("该注单已开奖/已处理，不能重复开奖。")
            return
        try:
            result = await wallet_service.settle_bet(int(bet["id"]), message.from_user.id, status, note=note)
        except ValueError as exc:
            logger.info(
                "admin_command_result command_name=%s telegram_user_id=%s result=failure reason=%s resolved_target_id=%s",
                action,
                message.from_user.id if message.from_user else None,
                str(exc),
                bet.get("id"),
            )
            await message.answer(f"结算失败：{exc}")
            return
        await database.add_admin_audit_log(
            message.from_user.id,
            action,
            "bet",
            str(bet.get("bet_no") or bet.get("id")),
            {"status": status, "settled": bool(result), "note": note, "ledger_id": (result or {}).get("ledger_id")},
        )
        if not result:
            await message.answer("该注单已开奖/已处理，不能重复开奖。")
            return
        logger.info(
            "admin_command_result command_name=%s telegram_user_id=%s result=success resolved_target_id=%s ledger_id=%s",
            action,
            message.from_user.id if message.from_user else None,
            bet.get("id"),
            result.get("ledger_id"),
        )
        if status == "won" and settings.payout_freeze_enabled:
            try:
                await message.bot.send_message(int(result["user_id"]), "注单中奖，派彩已冻结，预计 4 小时后解冻。")
            except Exception:
                logger.info("failed to notify settled win user_id=%s", result.get("user_id"), exc_info=True)
        await message.answer(f"注单已开奖：{status}，ledger_id={result.get('ledger_id')}")
        return
        parts = (command.args or "").strip().split(maxsplit=1)
        bet_key = _clean_command_token(parts[0]) if parts else ""
        note = parts[1].strip() if len(parts) > 1 else None
        if not bet_key:
            await message.answer(f"用法：/{action} <注单号或ID>")
            return
        bet = await database.get_bet(bet_key)
        if not bet:
            await message.answer(f"未找到该注单：{bet_key}\n请使用 /admin_bets 查看待开奖注单。")
            return
        try:
            result = await wallet_service.settle_bet(int(bet["id"]), message.from_user.id, status, note=note)
        except ValueError as exc:
            await message.answer(f"结算失败：{exc}")
            return
        await database.add_admin_audit_log(
            message.from_user.id,
            action,
            "bet",
            str(bet.get("bet_no") or bet.get("id")),
            {"status": status, "settled": bool(result), "note": note, "ledger_id": (result or {}).get("ledger_id")},
        )
        if not result:
            await message.answer("注单不存在、已开奖或状态不允许。")
            return
        if status == "won" and settings.payout_freeze_enabled:
            try:
                await message.bot.send_message(int(result["user_id"]), "注单中奖，派彩已冻结，预计24小时后解冻。")
            except Exception:
                logger.info("failed to notify settled win user_id=%s", result.get("user_id"), exc_info=True)
        await message.answer(f"注单已开奖：{status}，ledger_id={result.get('ledger_id')}")
        return
        parts = (command.args or "").strip().split(maxsplit=1)
        bet_key = parts[0] if parts else ""
        note = parts[1] if len(parts) > 1 else None
        if not bet_key:
            await message.answer(f"用法：/{action} <bet_no_or_id>")
            return
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        bet = await database.get_bet(bet_key)
        if not bet:
            await message.answer("未找到该注单，请检查注单号。")
            return
        bet_id = int(bet["id"])
        try:
            result = await wallet_service.settle_bet(bet_id, message.from_user.id, status, note=note)
        except ValueError as exc:
            await message.answer(f"结算失败：{exc}")
            return
        await database.add_admin_audit_log(
            message.from_user.id,
            action,
            "bet",
            str(bet.get("bet_no") or bet_id),
            {"status": status, "settled": bool(result), "note": note},
        )
        await message.answer(f"注单已开奖：{status}" if result else "注单不存在、已开奖或状态不允许。")
        return
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        bet_id = _first_int_arg(command)
        if bet_id is None:
            await message.answer(f"用法：/{action} <bet_id>")
            return
        try:
            result = await wallet_service.settle_bet(bet_id, message.from_user.id, status)
        except ValueError as exc:
            await message.answer(f"结算失败：{exc}")
            return
        await database.add_admin_audit_log(
            message.from_user.id,
            action,
            "bet",
            str(bet_id),
            {"status": status, "settled": bool(result)},
        )
        await message.answer(f"注单已结算：{status}" if result else "注单不存在或已处理。")

    @router.message(Command("admin_settle_win"))
    async def admin_settle_win(message: Message, command: CommandObject) -> None:
        await _admin_settle_bet(message, command, "won", "admin_settle_win")

    @router.message(Command("admin_settle_loss"))
    async def admin_settle_loss(message: Message, command: CommandObject) -> None:
        await _admin_settle_bet(message, command, "lost", "admin_settle_loss")

    @router.message(Command("admin_settle_void"))
    async def admin_settle_void(message: Message, command: CommandObject) -> None:
        await _admin_settle_bet(message, command, "void", "admin_settle_void")

    @router.message(Command("admin_cancel_bet"))
    async def admin_cancel_bet(message: Message, command: CommandObject) -> None:
        await _admin_settle_bet(message, command, "cancelled", "admin_cancel_bet")

    @router.message(Command("admin_withdrawals"))
    async def admin_withdrawals(message: Message) -> None:
        if not await _require_super_admin(message):
            return
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        await message.answer(_format_withdrawals(await database.list_withdraw_requests("pending", 20)))

    @router.message(Command("admin_withdraw"))
    async def admin_withdraw(message: Message, command: CommandObject) -> None:
        if not await _require_super_admin(message):
            return
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        withdraw_id = _first_int_arg(command)
        if withdraw_id is None:
            await message.answer("用法：/admin_withdraw <withdraw_id>")
            return
        await message.answer(_format_withdraw(await database.get_withdraw_request(withdraw_id)))

    @router.message(Command("admin_approve_withdraw"))
    async def admin_approve_withdraw(message: Message, command: CommandObject) -> None:
        if not await _require_super_admin(message):
            return
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        withdraw_id = _first_int_arg(command)
        if withdraw_id is None:
            await message.answer("用法：/admin_approve_withdraw <withdraw_id>")
            return
        row = await wallet_service.approve_withdraw(withdraw_id, message.from_user.id)
        await database.add_admin_audit_log(message.from_user.id, "admin_approve_withdraw", "withdraw", str(withdraw_id), {"approved": bool(row)})
        await message.answer("提现已审核通过，请人工转账后 mark paid。" if row else "提现申请不存在或已处理。")

    @router.message(Command("admin_reject_withdraw"))
    async def admin_reject_withdraw(message: Message, command: CommandObject) -> None:
        if not await _require_super_admin(message):
            return
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        parts = (command.args or "").strip().split(maxsplit=1)
        if len(parts) != 2:
            await message.answer("用法：/admin_reject_withdraw <withdraw_id> <reason>")
            return
        row = await wallet_service.reject_withdraw(int(parts[0]), message.from_user.id, parts[1])
        await database.add_admin_audit_log(message.from_user.id, "admin_reject_withdraw", "withdraw", parts[0], {"rejected": bool(row), "reason": parts[1]})
        await message.answer("提现已拒绝并退回冻结金额。" if row else "提现申请不存在或已处理。")

    @router.message(Command("admin_mark_withdraw_paid"))
    async def admin_mark_withdraw_paid(message: Message, command: CommandObject) -> None:
        if not await _require_super_admin(message):
            return
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        parts = (command.args or "").strip().split(maxsplit=1)
        if len(parts) != 2:
            await message.answer("用法：/admin_mark_withdraw_paid <withdraw_id> <txid>")
            return
        row = await wallet_service.mark_withdraw_paid(int(parts[0]), message.from_user.id, parts[1])
        await database.add_admin_audit_log(message.from_user.id, "admin_mark_withdraw_paid", "withdraw", parts[0], {"paid": bool(row), "txid": parts[1]})
        await message.answer("提现已标记为已人工出款。" if row else "提现申请不存在或已处理。")

    @router.message(Command("admin_rebate_rules"))
    async def admin_rebate_rules(message: Message) -> None:
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        await message.answer(_format_rebate_rules(await database.list_rebate_rules()))

    @router.message(Command("admin_rebate_preview"))
    async def admin_rebate_preview(message: Message, command: CommandObject) -> None:
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        user_id = _first_int_arg(command)
        if user_id is None:
            await message.answer("用法：/admin_rebate_preview <user_id>")
            return
        summary = await database.get_referral_summary(user_id)
        records = await database.list_rebate_records(user_id, 10)
        await message.answer(_format_admin_referral_summary(summary, settings.wallet_currency) + "\n\n" + _format_rebates(records))

    @router.message(Command("admin_generate_rebates"))
    async def admin_generate_rebates(message: Message) -> None:
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        if not settings.rebate_enabled:
            await message.answer("返水功能未启用。")
            return
        period_end = datetime.now()
        period_start = period_end - timedelta(days=7)
        count = await wallet_service.generate_rebates(period_start, period_end)
        await database.add_admin_audit_log(
            message.from_user.id,
            "admin_generate_rebates",
            "rebate",
            None,
            {"period_start": period_start.isoformat(), "period_end": period_end.isoformat(), "count": count},
        )
        await message.answer(f"已生成 pending 返水记录：{count} 条。")

    @router.message(Command("admin_settle_rebate"))
    async def admin_settle_rebate(message: Message, command: CommandObject) -> None:
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        rebate_id = _first_int_arg(command)
        if rebate_id is None:
            await message.answer("用法：/admin_settle_rebate <rebate_record_id>")
            return
        row = await wallet_service.settle_rebate(rebate_id)
        await database.add_admin_audit_log(message.from_user.id, "admin_settle_rebate", "rebate", str(rebate_id), {"settled": bool(row)})
        await message.answer("返水已入账。" if row else "返水记录不存在或已处理。")

    @router.message(Command("admin_referrals"))
    async def admin_referrals(message: Message, command: CommandObject) -> None:
        if message.chat.type != "private" or not message.from_user:
            await message.answer("当前权限不足，请联系超级管理员。")
            return
        role = await permission_service.get_user_role(message.from_user.id)
        if role not in {"super_admin", "admin", "agent"}:
            await message.answer("当前权限不足，请联系超级管理员。")
            return
        requested_user_id = _first_int_arg(command)
        user_id = requested_user_id if role in {"super_admin", "admin"} and requested_user_id is not None else message.from_user.id
        summary = await database.get_referral_summary(user_id)
        rows = await database.list_referrals(user_id, 50)
        await message.answer(
            _format_referrals(f"user_id={user_id}", summary, settings.wallet_currency)
            + "\n\n"
            + _format_referral_children(rows)
        )
        return
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        user_id = _first_int_arg(command)
        if user_id is None:
            await message.answer("用法：/admin_referrals <telegram_user_id>")
            return
        summary = await database.get_referral_summary(user_id)
        rows = await database.list_referrals(user_id, 50)
        await message.answer(
            _format_referrals(f"user_id={user_id}", summary, settings.wallet_currency)
            + "\n\n"
            + _format_referral_children(rows)
        )

    @router.message(Command("admin_invite_admin"))
    async def admin_invite_admin(message: Message, command: CommandObject) -> None:
        await _admin_set_role_command(message, command, "admin")

    @router.message(Command("admin_invite_agent"))
    async def admin_invite_agent(message: Message, command: CommandObject) -> None:
        await _admin_set_role_command(message, command, "agent")

    @router.message(Command("admin_remove_role"))
    async def admin_remove_role(message: Message, command: CommandObject) -> None:
        if not _admin_private_allowed(message, settings) or not await permission_service.can_invite_admin(message.from_user.id):
            await message.answer("只有超级管理员可以移除角色。")
            return
        target_user_id = _first_int_arg(command)
        if target_user_id is None:
            await message.answer("用法：/admin_remove_role <telegram_user_id>")
            return
        row = await database.remove_user_role(target_user_id)
        await database.add_admin_audit_log(message.from_user.id, "admin_remove_role", "user_role", str(target_user_id), {"removed": bool(row)})
        await message.answer("角色已移除。" if row else "用户没有可移除角色。")

    @router.message(Command("admin_users"))
    async def admin_users(message: Message) -> None:
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        await message.answer(_format_admin_users(await database.list_users(50)))

    @router.message(Command("admin_user"))
    async def admin_user(message: Message, command: CommandObject) -> None:
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        user_id = _first_int_arg(command)
        if user_id is None:
            await message.answer("用法：/admin_user <telegram_user_id>")
            return
        if not await permission_service.can_manage_user(message.from_user.id, user_id):
            await message.answer("你只能查看自己的下级用户。")
            return
        await message.answer(_format_admin_user(await database.get_user_admin_view(user_id)))

    @router.message(Command("admin_clear_my_test_bets"))
    async def admin_clear_my_test_bets(message: Message) -> None:
        if not _admin_private_allowed(message, settings) or not await permission_service.is_super_admin(message.from_user.id):
            await message.answer("只有超级管理员可以清理测试注单。")
            return
        count = await database.clear_user_test_bets(message.from_user.id)
        await database.add_admin_audit_log(
            message.from_user.id,
            "admin_clear_my_test_bets",
            "bets",
            str(message.from_user.id),
            {"cleared": count, "is_simulated": True},
        )
        await message.answer(f"已清理模拟测试注单：{count} 张。")

    @router.message(Command("admin_clear_user_test_bets"))
    async def admin_clear_user_test_bets(message: Message, command: CommandObject) -> None:
        if not _admin_private_allowed(message, settings) or not await permission_service.is_super_admin(message.from_user.id):
            await message.answer("只有超级管理员可以清理测试注单。")
            return
        user_id = _first_int_arg(command)
        if user_id is None:
            await message.answer("用法：/admin_clear_user_test_bets <telegram_user_id>")
            return
        count = await database.clear_user_test_bets(user_id)
        await database.add_admin_audit_log(
            message.from_user.id,
            "admin_clear_user_test_bets",
            "bets",
            str(user_id),
            {"cleared": count, "is_simulated": True},
        )
        await message.answer(f"已清理用户 {user_id} 的模拟测试注单：{count} 张。")

    @router.message(Command("admin_agent_applications"))
    async def admin_agent_applications(message: Message) -> None:
        if not _admin_private_allowed(message, settings) or not await permission_service.is_super_admin(message.from_user.id):
            await message.answer("只有超级管理员可以审核代理申请。")
            return
        await message.answer(_format_agent_applications(await database.list_agent_applications()))

    @router.message(Command("admin_approve_agent"))
    async def admin_approve_agent(message: Message, command: CommandObject) -> None:
        await _review_agent_application_command(message, command, "approved")

    @router.message(Command("admin_reject_agent"))
    async def admin_reject_agent(message: Message, command: CommandObject) -> None:
        await _review_agent_application_command(message, command, "rejected")

    async def _admin_set_role_command(message: Message, command: CommandObject, role: str) -> None:
        if not _admin_private_allowed(message, settings) or not await permission_service.can_invite_admin(message.from_user.id):
            await message.answer("只有超级管理员可以邀请管理员/代理。")
            return
        target_user_id = _first_int_arg(command)
        if target_user_id is None:
            await message.answer(f"用法：/admin_invite_{role} <telegram_user_id>")
            return
        row = await database.set_user_role(target_user_id, role, message.from_user.id)
        await database.add_admin_audit_log(message.from_user.id, f"admin_invite_{role}", "user_role", str(target_user_id), {"role": role})
        await message.answer(f"已设置 {target_user_id} 为 {role}。id={row['id']}")

    async def _review_agent_application_command(message: Message, command: CommandObject, status: str) -> None:
        if not _admin_private_allowed(message, settings) or not await permission_service.is_super_admin(message.from_user.id):
            await message.answer("只有超级管理员可以审核代理申请。")
            return
        application_id = _first_int_arg(command)
        if application_id is None:
            await message.answer(f"用法：/admin_{status}_agent <application_id>")
            return
        row = await database.review_agent_application(application_id, status, message.from_user.id)
        if row and status == "approved":
            await database.set_user_role(int(row["user_id"]), "agent", message.from_user.id)
        await database.add_admin_audit_log(message.from_user.id, f"admin_{status}_agent", "agent_application", str(application_id), {"reviewed": bool(row)})
        await message.answer("代理申请已处理。" if row else "申请不存在或已处理。")

    @router.message(Command("admin_rebate_requests"))
    async def admin_rebate_requests(message: Message) -> None:
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        await message.answer(_format_rebate_requests(await database.list_rebate_requests(None, 50, "pending"), await _event_lang(message, database, settings)))

    @router.message(Command("admin_rebate_request"))
    async def admin_rebate_request(message: Message, command: CommandObject) -> None:
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        request_id = _first_int_arg(command)
        if request_id is None:
            await message.answer("用法：/admin_rebate_request <request_id>")
            return
        await message.answer(_format_rebate_requests([await database.get_rebate_request(request_id)]))

    @router.message(Command("admin_approve_rebate_request"))
    async def admin_approve_rebate_request(message: Message, command: CommandObject) -> None:
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        parts = (command.args or "").strip().split(maxsplit=2)
        if len(parts) != 3:
            await message.answer("用法：/admin_approve_rebate_request <request_id> <amount> <reason>")
            return
        row = await database.update_rebate_request_status(int(parts[0]), "approved", approved_amount=Decimal(parts[1]), reason=parts[2])
        await database.add_admin_audit_log(message.from_user.id, "admin_approve_rebate_request", "rebate_request", parts[0], {"approved": bool(row), "amount": parts[1], "reason": parts[2]})
        await message.answer("返水申请已批准。" if row else "返水申请不存在或状态不允许。")

    @router.message(Command("admin_reject_rebate_request"))
    async def admin_reject_rebate_request(message: Message, command: CommandObject) -> None:
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        parts = (command.args or "").strip().split(maxsplit=1)
        if len(parts) != 2:
            await message.answer("用法：/admin_reject_rebate_request <request_id> <reason>")
            return
        row = await database.update_rebate_request_status(int(parts[0]), "rejected", reason=parts[1])
        await database.add_admin_audit_log(message.from_user.id, "admin_reject_rebate_request", "rebate_request", parts[0], {"rejected": bool(row), "reason": parts[1]})
        await message.answer("返水申请已拒绝。" if row else "返水申请不存在或状态不允许。")

    @router.message(Command("admin_approve_rebate"))
    @router.message(Command("admin_approve_agent_rebate"))
    async def admin_approve_rebate(message: Message, command: CommandObject) -> None:
        if not await _require_super_admin(message):
            return
        request_id = _first_int_arg(command)
        if request_id is None:
            await message.answer(t(await _event_lang(message, database, settings), "usage_approve_rebate"))
            return
        row = await database.approve_agent_rebate_request(request_id, message.from_user.id)
        await database.add_admin_audit_log(message.from_user.id, "admin_approve_rebate", "rebate_request", str(request_id), {"approved": bool(row)})
        await message.answer("返水申请已审核通过并入账。" if row else t(await _event_lang(message, database, settings), "rebate_already_processed"))
        if row:
            await _notify_user(
                message.bot,
                int(row["user_id"]),
                t(await database.get_user_language(int(row["user_id"]), settings.default_language), "rebate_approved", amount=_money(row.get("rebate_amount")), currency=settings.wallet_currency),
            )

    @router.message(Command("admin_reject_rebate"))
    @router.message(Command("admin_reject_agent_rebate"))
    async def admin_reject_rebate(message: Message, command: CommandObject) -> None:
        if not await _require_super_admin(message):
            return
        parts = (command.args or "").strip().split(maxsplit=1)
        if not parts:
            await message.answer(t(await _event_lang(message, database, settings), "usage_reject_rebate"))
            return
        reason = parts[1] if len(parts) > 1 else "-"
        row = await database.reject_agent_rebate_request(int(parts[0]), message.from_user.id, reason)
        await database.add_admin_audit_log(message.from_user.id, "admin_reject_rebate", "rebate_request", parts[0], {"rejected": bool(row), "reason": reason})
        await message.answer("返水申请已拒绝。" if row else t(await _event_lang(message, database, settings), "rebate_already_processed"))
        if row:
            await _notify_user(
                message.bot,
                int(row["user_id"]),
                t(await database.get_user_language(int(row["user_id"]), settings.default_language), "rebate_rejected", reason=reason),
            )

    @router.message(Command("admin_pay_rebate_request"))
    async def admin_pay_rebate_request(message: Message, command: CommandObject) -> None:
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        request_id = _first_int_arg(command)
        if request_id is None:
            await message.answer("用法：/admin_pay_rebate_request <request_id>")
            return
        request = await database.get_rebate_request(request_id)
        if not request or request.get("status") != "approved":
            await message.answer("返水申请不存在或未批准。")
            return
        amount = Decimal(str(request.get("approved_amount") or request.get("requested_amount") or 0))
        if amount <= 0:
            await message.answer("批准金额无效。")
            return
        ledger = await wallet_service.add_ledger_entry(int(request["user_id"]), "rebate", amount, ref_type="rebate_request", ref_id=str(request_id), description="Admin rebate request payout")
        row = await database.mark_rebate_request_paid(request_id)
        await database.add_admin_audit_log(message.from_user.id, "admin_pay_rebate_request", "rebate_request", str(request_id), {"paid": bool(row), "amount": str(amount), "ledger_id": ledger["id"]})
        await message.answer("返水已派发到账。" if row else "返水派发状态更新失败。")

    @router.message(Command("admin_cancel_requests"))
    async def admin_cancel_requests(message: Message) -> None:
        if not await _require_super_admin(message):
            return
        await message.answer(_format_cancel_requests(await database.list_cancel_requests("pending", 50)))

    @router.message(Command("admin_approve_cancel"))
    async def admin_approve_cancel(message: Message, command: CommandObject) -> None:
        if not await _require_super_admin(message):
            return
        parts = (command.args or "").strip().split(maxsplit=1)
        if len(parts) != 2:
            await message.answer("用法：/admin_approve_cancel <request_id> <reason>")
            return
        request_id = _parse_id_token(parts[0])
        if request_id is None:
            await message.answer("request_id 必须是真实数字ID。")
            return
        request = await database.get_cancel_request(request_id)
        if not request or request.get("status") != "pending":
            await message.answer("退单申请不存在或已处理。")
            return
        try:
            bet = await resolve_bet_by_id_or_no(database, str(request["bet_id"]))
        except ValueError:
            bet = None
        if not bet:
            await message.answer("未找到该注单。")
            return
        result = await wallet_service.settle_bet(int(bet["id"]), message.from_user.id, "cancelled", note=parts[1])
        if not result:
            await message.answer("注单已开奖或状态不允许退单。")
            return
        row = await database.review_cancel_request(request_id, "approved", message.from_user.id, parts[1])
        await database.add_admin_audit_log(
            message.from_user.id,
            "admin_approve_cancel",
            "cancel_request",
            str(request_id),
            {"approved": bool(row), "bet_id": int(request["bet_id"]), "ledger_id": result.get("ledger_id"), "reason": parts[1]},
        )
        await message.answer(f"退单已批准，ledger_id={result.get('ledger_id')}")

    @router.message(Command("admin_reject_cancel"))
    async def admin_reject_cancel(message: Message, command: CommandObject) -> None:
        if not await _require_super_admin(message):
            return
        parts = (command.args or "").strip().split(maxsplit=1)
        if len(parts) != 2:
            await message.answer("用法：/admin_reject_cancel <request_id> <reason>")
            return
        request_id = _parse_id_token(parts[0])
        if request_id is None:
            await message.answer("request_id 必须是真实数字ID。")
            return
        row = await database.review_cancel_request(request_id, "rejected", message.from_user.id, parts[1])
        await database.add_admin_audit_log(
            message.from_user.id,
            "admin_reject_cancel",
            "cancel_request",
            str(request_id),
            {"rejected": bool(row), "reason": parts[1]},
        )
        await message.answer("退单申请已拒绝。" if row else "退单申请不存在或已处理。")

    @router.message(Command("admin_payout_freezes"))
    async def admin_payout_freezes(message: Message) -> None:
        if not await _require_super_admin(message):
            return
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        await message.answer(_format_payout_freezes(await database.list_payout_freezes("frozen", 50), settings.wallet_currency))

    @router.message(Command("admin_unlock_payout"))
    async def admin_unlock_payout(message: Message, command: CommandObject) -> None:
        if not await _require_super_admin(message):
            return
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        parts = (command.args or "").strip().split(maxsplit=1)
        if len(parts) != 2:
            await message.answer("用法：/admin_unlock_payout <freeze_id> <reason>")
            return
        row = await wallet_service.unlock_payout_freeze(int(parts[0]), reason=parts[1])
        await database.add_admin_audit_log(message.from_user.id, "admin_unlock_payout", "payout_freeze", parts[0], {"unlocked": bool(row), "reason": parts[1]})
        await message.answer("派彩冻结已解冻。" if row else "派彩冻结不存在或状态不允许。")

    @router.message(Command("admin_extend_payout_freeze"))
    async def admin_extend_payout_freeze(message: Message, command: CommandObject) -> None:
        if not await _require_super_admin(message):
            return
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        parts = (command.args or "").strip().split(maxsplit=2)
        if len(parts) != 3:
            await message.answer("用法：/admin_extend_payout_freeze <freeze_id> <hours> <reason>")
            return
        row = await wallet_service.extend_payout_freeze(int(parts[0]), int(parts[1]), parts[2])
        await database.add_admin_audit_log(message.from_user.id, "admin_extend_payout_freeze", "payout_freeze", parts[0], {"extended": bool(row), "hours": parts[1], "reason": parts[2]})
        await message.answer("派彩冻结已延期。" if row else "派彩冻结不存在或状态不允许。")

    @router.message(Command("admin_freeze_balance"))
    async def admin_freeze_balance(message: Message, command: CommandObject) -> None:
        if not _admin_private_allowed(message, settings) or not await permission_service.is_super_admin(message.from_user.id):
            await message.answer("只有超级管理员可冻结余额。")
            return
        parts = (command.args or "").strip().split(maxsplit=2)
        if len(parts) != 3:
            await message.answer("用法：/admin_freeze_balance <telegram_user_id> <amount> <reason>")
            return
        row = await wallet_service.freeze_balance(int(parts[0]), Decimal(parts[1]), parts[2], message.from_user.id)
        await database.add_admin_audit_log(message.from_user.id, "admin_freeze_balance", "wallet", parts[0], {"frozen": bool(row), "amount": parts[1], "reason": parts[2]})
        await message.answer(f"余额冻结完成，freeze_id={row['id']}。" if row else "余额不足，无法冻结。")

    @router.message(Command("admin_unfreeze_balance"))
    async def admin_unfreeze_balance(message: Message, command: CommandObject) -> None:
        if not await _require_super_admin(message):
            return
        parts = (command.args or "").strip().split(maxsplit=1)
        if len(parts) != 2:
            await message.answer("用法：/admin_unfreeze_balance <freeze_id> <reason>")
            return
        raw_id = parts[0].strip()
        if raw_id == "<freeze_id>":
            await message.answer("请把 <freeze_id> 替换为真实冻结记录ID，例如 /admin_unfreeze_balance 1 test_unfreeze")
            return
        freeze_id = _parse_id_token(raw_id)
        if freeze_id is None:
            await message.answer("freeze_id 必须是真实数字ID，例如 /admin_unfreeze_balance 1 test_unfreeze")
            return
        try:
            row = await wallet_service.unfreeze_balance(freeze_id, parts[1])
        except ValueError as exc:
            await message.answer(f"解冻失败：{exc}")
            return
        await database.add_admin_audit_log(
            message.from_user.id,
            "admin_unfreeze_balance",
            "wallet_freeze",
            str(freeze_id),
            {"unfrozen": bool(row), "reason": parts[1], "ledger_id": (row or {}).get("ledger_id")},
        )
        if not row:
            await message.answer("冻结记录不存在或状态不允许。")
            return
        await message.answer(f"解冻完成，ledger_id={row.get('ledger_id')}")
        return
        if not _admin_private_allowed(message, settings) or not await permission_service.is_super_admin(message.from_user.id):
            await message.answer("只有超级管理员可解冻余额。")
            return
        parts = (command.args or "").strip().split(maxsplit=1)
        if len(parts) != 2:
            await message.answer("用法：/admin_unfreeze_balance <freeze_id> <reason>")
            return
        row = await wallet_service.unfreeze_balance(int(parts[0]), parts[1])
        await database.add_admin_audit_log(message.from_user.id, "admin_unfreeze_balance", "wallet_freeze", parts[0], {"unfrozen": bool(row), "reason": parts[1]})
        await message.answer("余额已解冻。" if row else "冻结记录不存在或状态不允许。")

    @router.message(Command("admin_user_freezes"))
    async def admin_user_freezes(message: Message, command: CommandObject) -> None:
        if not await _require_super_admin(message):
            return
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        user_id = _first_int_arg(command)
        if user_id is None:
            await message.answer("用法：/admin_user_freezes <telegram_user_id>")
            return
        await message.answer(_format_wallet_freezes(await database.list_wallet_freezes(user_id), settings.wallet_currency))

    async def _risk_command(message: Message, command: CommandObject, action: str, **updates: Any) -> None:
        if not _admin_private_allowed(message, settings) or not await permission_service.is_super_admin(message.from_user.id):
            await message.answer("只有超级管理员可操作风控。")
            return
        parts = (command.args or "").strip().split(maxsplit=1)
        if not parts:
            await message.answer(f"用法：/{action} <telegram_user_id> [reason]")
            return
        reason = parts[1] if len(parts) > 1 else None
        row = await database.update_user_risk_status(int(parts[0]), ban_reason=reason, risk_note=reason, **updates)
        await database.add_admin_audit_log(message.from_user.id, action, "user", parts[0], {"updated": bool(row), "reason": reason, **updates})
        await message.answer("用户风控状态已更新。" if row else "用户不存在。")

    @router.message(Command("admin_ban_user"))
    async def admin_ban_user(message: Message, command: CommandObject) -> None:
        await _risk_command(message, command, "admin_ban_user", status="banned", bet_restricted=True, withdraw_restricted=True)

    @router.message(Command("admin_unban_user"))
    async def admin_unban_user(message: Message, command: CommandObject) -> None:
        await _risk_command(message, command, "admin_unban_user", status="active", bet_restricted=False, withdraw_restricted=False)

    @router.message(Command("admin_freeze_user"))
    async def admin_freeze_user(message: Message, command: CommandObject) -> None:
        await _risk_command(message, command, "admin_freeze_user", status="frozen", bet_restricted=True, withdraw_restricted=True)

    @router.message(Command("admin_unfreeze_user"))
    async def admin_unfreeze_user(message: Message, command: CommandObject) -> None:
        await _risk_command(message, command, "admin_unfreeze_user", status="active", bet_restricted=False, withdraw_restricted=False)

    @router.message(Command("admin_restrict_bet"))
    async def admin_restrict_bet(message: Message, command: CommandObject) -> None:
        await _risk_command(message, command, "admin_restrict_bet", bet_restricted=True)

    @router.message(Command("admin_unrestrict_bet"))
    async def admin_unrestrict_bet(message: Message, command: CommandObject) -> None:
        await _risk_command(message, command, "admin_unrestrict_bet", bet_restricted=False)

    @router.message(Command("admin_restrict_withdraw"))
    async def admin_restrict_withdraw(message: Message, command: CommandObject) -> None:
        await _risk_command(message, command, "admin_restrict_withdraw", withdraw_restricted=True)

    @router.message(Command("admin_unrestrict_withdraw"))
    async def admin_unrestrict_withdraw(message: Message, command: CommandObject) -> None:
        await _risk_command(message, command, "admin_unrestrict_withdraw", withdraw_restricted=False)

    @router.callback_query(F.data.in_({
        "admin:stats",
        "admin:markets",
        "admin:bets",
        "admin:wallets",
        "admin:withdrawals",
        "admin:deposits",
        "admin:users",
        "admin:rebates",
        "admin:commissions",
        "admin:settings",
    }))
    async def admin_panel_callback(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        if not callback.from_user:
            return
        role = await permission_service.get_user_role(callback.from_user.id)
        if role not in {"super_admin", "admin", "agent"}:
            await callback.message.answer("无管理员权限。")
            return
        data = callback.data
        super_only_panels = {
            "admin:stats",
            "admin:markets",
            "admin:bets",
            "admin:wallets",
            "admin:withdrawals",
            "admin:deposits",
            "admin:users",
            "admin:settings",
        }
        if data in super_only_panels and role != "super_admin":
            await callback.message.answer("当前权限不足，请联系超级管理员。")
            return
        if data == "admin:stats":
            await callback.message.answer(_format_admin_dashboard(await database.admin_dashboard(), settings.wallet_currency))
        elif data == "admin:markets":
            await callback.message.answer("🎯 可投注赛事管理\n\n使用 /admin_markets 查看当前可投注赛事；使用 /admin_suspend 和 /admin_resume 管理封盘。")
        elif data == "admin:bets":
            await callback.message.answer(_format_admin_bets(await database.list_admin_bets("pending", 20)))
        elif data == "admin:wallets":
            await callback.message.answer("💰 用户钱包\n\n请输入：/admin_wallet <telegram_user_id>\n手动调账：/admin_adjust_balance <telegram_user_id> <amount> <reason>")
        elif data == "admin:withdrawals":
            await callback.message.answer(_format_withdrawals(await database.list_withdraw_requests("pending", 20)))
        elif data == "admin:deposits":
            await callback.message.answer(_format_deposit_records(await database.list_deposit_orders(20)))
        elif data == "admin:users":
            if role != "super_admin":
                await callback.message.answer("👥 用户/代理管理\n\n代理可在推广页面查看自己的下级。授权管理员/代理需要超级管理员权限。")
            else:
                await callback.message.answer(_format_admin_users(await database.list_users(50)))
        elif data == "admin:rebates":
            await callback.message.answer(
                _format_rebate_requests(
                    await database.list_rebate_requests(None, 50, "pending"),
                    await _callback_lang(callback, database, settings),
                )
            )
        elif data == "admin:commissions":
            await callback.message.answer(_format_commissions(await database.list_commissions(None if role == "super_admin" else callback.from_user.id, 20)))
        elif data == "admin:settings":
            await callback.message.answer(
                "系统设置\n\n"
                f"真实下注：{'开启' if settings.real_betting_enabled else '关闭'}\n"
                f"测试下注余额校验：{'开启' if settings.bet_require_balance_for_simulation else '关闭'}\n"
                f"提现：{'开启' if settings.withdraw_enabled else '关闭'}"
            )

    @router.callback_query(F.data == "support")
    async def support_callback(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        await callback.message.answer("该入口已停用。下注确认后买定离手，暂不支持取消。")

    @router.callback_query()
    async def unknown_callback(callback: CallbackQuery) -> None:
        user_id = callback.from_user.id if callback.from_user else None
        logger.warning("unhandled callback data=%s user_id=%s", callback.data, user_id)
        await _safe_callback_answer(callback, "该功能暂未开放或按钮已过期，请返回首页重试。")

    return router


async def _start_text(
    cache: RedisCache,
    api_client: ApiFootballClient,
    database: Database,
    settings: Settings,
    telegram_user_id: int | None,
    lang: str = "zh",
) -> str:
    today_matches, _ = await get_bettable_matches_range(cache, api_client, database, settings)
    tomorrow = date.today() + timedelta(days=1)
    tomorrow_matches, _ = await get_bettable_matches_for_date(cache, api_client, database, settings, tomorrow)
    live = await _get_live(cache, api_client)
    stats = await database.get_user_bet_stats(telegram_user_id) if telegram_user_id else {}
    pending = int(stats.get("pending_count") or 0)
    simulated_pending = int(stats.get("simulated_pending_count") or 0)
    mode_lines = []
    if not settings.real_betting_enabled:
        mode_lines.append("当前为模拟下注模式，不扣真实余额。")
        if settings.bet_require_balance_for_simulation:
            mode_lines.append("模拟下注仍需钱包余额覆盖下注金额。")
    if lang == "en":
        return (
            "WorldCupTop Bot\n\n"
            f"Featured Matches: {_count_by_date(today_matches, date.today())}\n"
            f"Tomorrow Fixtures: {len(tomorrow_matches)}\n"
            f"Live Matches: {len(live)}\n"
            f"My Pending Bets: {pending}\n"
            f"Test Bets: {simulated_pending}"
        )
    return (
        "WorldCupTop Bot\n\n"
        f"今日可投注：{_count_by_date(today_matches, date.today())} 场\n"
        f"明日可投注：{len(tomorrow_matches)} 场\n"
        f"实时比赛：{len(live)} 场\n"
        f"我的待结算注单：{pending} 张\n"
        f"其中模拟注单：{simulated_pending} 张"
        + (("\n" + "\n".join(mode_lines)) if mode_lines else "")
    )


async def get_bettable_matches_range(
    cache: RedisCache,
    api_client: ApiFootballClient,
    database: Database,
    settings: Settings,
    *,
    force_refresh: bool = False,
) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    settings = await _effective_settings(cache, settings)
    days = settings.bettable_days_ahead if settings.show_tomorrow_matches else 1
    days = max(days, 1)
    all_matches: list[dict[str, Any]] = []
    all_odds: dict[int, dict[str, Any]] = {}
    for offset in range(days):
        fixture_date = date.today() + timedelta(days=offset)
        matches, odds = await get_bettable_matches_for_date(
            cache, api_client, database, settings, fixture_date, force_refresh=force_refresh
        )
        all_matches.extend(matches)
        all_odds.update(odds)
    all_matches.sort(key=lambda item: int((item.get("fixture") or {}).get("timestamp") or 0))
    all_matches = all_matches[: settings.max_bettable_matches]
    await cache.set_json(
        f"football:bettable_matches:range:{date.today().isoformat()}:{days}",
        all_matches,
        ttl_seconds=60,
    )
    await cache.set_text("football:bettable_matches:last_update", _now_hhmm(), ttl_seconds=120)
    return all_matches, all_odds


async def get_bettable_matches_for_date(
    cache: RedisCache,
    api_client: ApiFootballClient,
    database: Database,
    settings: Settings,
    fixture_date: date,
    *,
    force_refresh: bool = False,
) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    settings = await _effective_settings(cache, settings)
    fixtures = await _get_fixtures_by_date(cache, api_client, fixture_date, force_refresh=force_refresh)
    odds_items = await _get_odds_raw_by_date(cache, api_client, fixture_date, force_refresh=force_refresh)
    matches, odds_by_fixture = build_odds_first_matches(odds_items or [], fixtures)
    raw_by_fixture = {
        int((item.get("fixture") or {}).get("id") or item.get("fixture_id")): item
        for item in odds_items or []
        if (item.get("fixture") or {}).get("id") or item.get("fixture_id")
    }
    overrides = await database.get_market_overrides([int(item.get("fixture", {}).get("id")) for item in matches if item.get("fixture", {}).get("id")])
    bettable: list[dict[str, Any]] = []
    for item in matches:
        fixture_id = item.get("fixture", {}).get("id")
        if fixture_id is None:
            continue
        raw = raw_by_fixture.get(int(fixture_id))
        normalized = normalize_fixture_odds_full(raw) if raw else await _get_fixture_odds(cache, api_client, int(fixture_id))
        override = overrides.get(int(fixture_id))
        status = is_bettable_fixture(
            item,
            normalized,
            settings,
            is_suspended_by_admin=bool(override and override.get("is_suspended")),
        )
        if status.is_bettable:
            bettable.append(item)
        if raw:
            await cache.set_json(f"football:odds_raw:fixture:{fixture_id}", raw, ttl_seconds=120)
            await cache.set_json(f"football:fixture_detail:{fixture_id}", item, ttl_seconds=300)
    await cache.set_json(f"football:bettable_matches:{fixture_date.isoformat()}", bettable, ttl_seconds=60)
    return bettable, odds_by_fixture


async def get_all_schedule_range(
    cache: RedisCache,
    api_client: ApiFootballClient,
    database: Database,
    settings: Settings,
) -> tuple[list[dict[str, Any]], dict[int, BettableStatus]]:
    settings = await _effective_settings(cache, settings)
    days = 2 if settings.show_tomorrow_matches else 1
    fixtures: list[dict[str, Any]] = []
    statuses: dict[int, BettableStatus] = {}
    for offset in range(days):
        fixture_date = date.today() + timedelta(days=offset)
        day_fixtures = await _get_fixtures_by_date(cache, api_client, fixture_date)
        odds_items = await _get_odds_raw_by_date(cache, api_client, fixture_date)
        raw_by_fixture = {
            int((item.get("fixture") or {}).get("id") or item.get("fixture_id")): item
            for item in odds_items or []
            if (item.get("fixture") or {}).get("id") or item.get("fixture_id")
        }
        overrides = await database.get_market_overrides([int(item.get("fixture", {}).get("id")) for item in day_fixtures if item.get("fixture", {}).get("id")])
        for item in day_fixtures:
            fixture_id = item.get("fixture", {}).get("id")
            if fixture_id is None:
                continue
            raw = raw_by_fixture.get(int(fixture_id))
            normalized = normalize_fixture_odds_full(raw) if raw else None
            override = overrides.get(int(fixture_id))
            statuses[int(fixture_id)] = is_bettable_fixture(
                item,
                normalized,
                settings,
                is_suspended_by_admin=bool(override and override.get("is_suspended")),
            )
            await cache.set_json(f"football:fixture_detail:{fixture_id}", item, ttl_seconds=300)
        fixtures.extend(day_fixtures)
    fixtures.sort(key=lambda item: int((item.get("fixture") or {}).get("timestamp") or 0))
    await cache.set_text("football:all_schedule:last_update", _now_hhmm(), ttl_seconds=120)
    return fixtures, statuses


async def _get_fixtures_by_date(
    cache: RedisCache,
    api_client: ApiFootballClient,
    fixture_date: date,
    *,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    key = f"football:today_fixtures:{fixture_date.isoformat()}"
    fixtures = [] if force_refresh else await cache.get_json(key, [])
    if fixtures:
        return fixtures
    try:
        fixtures = await api_client.get_fixtures_by_date(fixture_date)
        await cache.set_json(key, fixtures, ttl_seconds=300)
        return fixtures
    except Exception as exc:
        _log_api_failure(
            f"fixtures:{fixture_date.isoformat()}",
            "fixtures fetch failed date=%s; keeping existing cache: %s",
            fixture_date.isoformat(),
            exc,
        )
        return await cache.get_json(key, [])


async def _get_odds_raw_by_date(
    cache: RedisCache,
    api_client: ApiFootballClient,
    fixture_date: date,
    *,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    key = f"football:odds_raw:{fixture_date.isoformat()}"
    odds_items = [] if force_refresh else await cache.get_json(key, None)
    if odds_items is not None and odds_items != []:
        return odds_items
    try:
        odds_items = await api_client.get_pre_match_odds_by_date(fixture_date)
        await cache.set_json(key, odds_items, ttl_seconds=120)
        return odds_items
    except Exception as exc:
        return await cache.get_json(key, [])


async def _get_live(cache: RedisCache, api_client: ApiFootballClient) -> list[dict[str, Any]]:
    fixtures = await cache.get_json("football:live_fixtures", [])
    if fixtures:
        return fixtures
    try:
        fixtures = await api_client.get_live_fixtures()
        await cache.set_json("football:live_fixtures", fixtures)
        await cache.set_text("football:last_update:live", _now_hhmm())
        return fixtures
    except Exception as exc:
        _log_api_failure("live-fixtures", "live fixtures fetch failed; keeping existing cache: %s", exc)
        return await cache.get_json("football:live_fixtures", [])


async def _get_featured_live(
    cache: RedisCache,
    api_client: ApiFootballClient,
    settings: Settings,
) -> list[dict[str, Any]]:
    key = f"football:featured_live:{date.today().isoformat()}"
    fixtures = await cache.get_json(key, [])
    if fixtures:
        return fixtures
    live = await _get_live(cache, api_client)
    fixtures = filter_featured_fixtures(live, settings)
    await cache.set_json(key, fixtures)
    return fixtures


async def _get_featured_today(
    cache: RedisCache,
    api_client: ApiFootballClient,
    settings: Settings,
) -> list[dict[str, Any]]:
    today = date.today().isoformat()
    key = f"football:featured_matches:{today}"
    fixtures = await cache.get_json(key, [])
    if fixtures:
        return fixtures
    all_fixtures = await cache.get_json(f"football:today_fixtures:{today}", [])
    if not all_fixtures:
        all_fixtures = await _get_fixtures_by_date(cache, api_client, date.today())
        if not all_fixtures:
            return []
    fixtures = filter_featured_fixtures(all_fixtures, settings)
    await cache.set_json(key, fixtures)
    await cache.set_text("football:last_update:featured", _now_hhmm())
    return fixtures


async def get_odds_first_matches(
    cache: RedisCache,
    api_client: ApiFootballClient,
    fixture_date: date,
) -> list[dict[str, Any]]:
    date_key = fixture_date.isoformat()
    matches_key = f"football:odds_first_matches:{date_key}"
    cached = await cache.get_json(matches_key, [])
    if cached:
        return cached

    raw_key = f"football:odds_raw:{date_key}"
    odds_items = await cache.get_json(raw_key, None)
    if odds_items is None:
        try:
            odds_items = await api_client.get_pre_match_odds_by_date(fixture_date)
            await cache.set_json(raw_key, odds_items, ttl_seconds=120)
        except Exception:
            odds_items = await cache.get_json(raw_key, [])

    fixtures = await _get_today(cache, api_client)
    matches, odds_by_fixture = build_odds_first_matches(odds_items or [], fixtures)
    await cache.set_json(matches_key, matches, ttl_seconds=120)
    await cache.set_json(f"football:featured_odds:{date_key}", odds_by_fixture, ttl_seconds=120)
    await cache.set_text(f"football:odds_first_matches:updated_at:{date_key}", _now_hhmm(), ttl_seconds=120)
    for item in odds_items or []:
        fixture_id = (item.get("fixture") or {}).get("id")
        if fixture_id is not None:
            await cache.set_json(f"football:odds_raw:fixture:{fixture_id}", item, ttl_seconds=120)
    return matches


async def _get_today(cache: RedisCache, api_client: ApiFootballClient) -> list[dict[str, Any]]:
    return await _get_fixtures_by_date(cache, api_client, date.today())


async def _get_today_odds(cache: RedisCache) -> dict[str, dict[str, Any]]:
    return await cache.get_json(f"football:featured_odds:{date.today().isoformat()}", {})


async def _get_fixture_odds(
    cache: RedisCache,
    api_client: ApiFootballClient,
    fixture_id: int,
) -> Any:
    key = f"football:odds:fixture:{fixture_id}"
    cached = await cache.get_json(key)
    if cached:
        return normalized_from_dict(cached)
    raw = await cache.get_json(f"football:odds_raw:fixture:{fixture_id}")
    if not raw:
        days = max(1, 3)
        for offset in range(days):
            raw_items = await cache.get_json(f"football:odds_raw:{(date.today() + timedelta(days=offset)).isoformat()}", [])
            raw = next(
                (
                    item
                    for item in raw_items
                    if str((item.get("fixture") or {}).get("id") or item.get("fixture_id")) == str(fixture_id)
                ),
                None,
            )
            if raw:
                break
    if raw:
        normalized = normalize_fixture_odds_full(raw)
        await cache.set_json(key, normalized.to_dict(), ttl_seconds=120)
        await cache.set_text(f"football:odds:last_update:{fixture_id}", _now_hhmm(), ttl_seconds=120)
        return normalized
    try:
        odds_items = await api_client.get_odds_by_fixture(fixture_id)
        if not odds_items:
            odds_items = await api_client.get_live_odds_by_fixture(fixture_id)
        raw = odds_items[0] if odds_items else {"fixture": {"id": fixture_id}, "bookmakers": []}
        normalized = normalize_fixture_odds_full(raw)
        await cache.set_json(key, normalized.to_dict(), ttl_seconds=120)
        await cache.set_text(f"football:odds:last_update:{fixture_id}", _now_hhmm(), ttl_seconds=120)
        return normalized
    except Exception as exc:
        cached = await cache.get_json(key)
        return normalized_from_dict(cached) if cached else None


async def _ensure_odds_markets(cache: RedisCache, api_client: ApiFootballClient) -> list[dict[str, Any]]:
    cached = await cache.get_json("football:odds:markets")
    if cached:
        return cached
    try:
        markets = await api_client.get_odds_bets()
        await cache.set_json("football:odds:markets", markets, ttl_seconds=86400)
        return markets
    except Exception:
        cached = await cache.get_json("football:odds:markets", [])
        return cached


async def _find_cached_fixture(
    cache: RedisCache,
    api_client: ApiFootballClient,
    settings: Settings,
    fixture_id: int,
) -> dict[str, Any] | None:
    candidates = []
    detail = await cache.get_json(f"football:fixture_detail:{fixture_id}")
    if detail:
        return detail
    for offset in range(max(3, settings.bettable_days_ahead)):
        day = (date.today() + timedelta(days=offset)).isoformat()
        for key in (
            f"football:bettable_matches:{day}",
            f"football:odds_first_matches:{day}",
            f"football:featured_matches:{day}",
            f"football:featured_live:{day}",
            f"football:today_fixtures:{day}",
        ):
            candidates.extend(await cache.get_json(key, []))
    candidates.extend(await cache.get_json("football:live_fixtures", []))
    if not candidates:
        for offset in range(max(3, settings.bettable_days_ahead)):
            candidates.extend(await _get_fixtures_by_date(cache, api_client, date.today() + timedelta(days=offset)))
        candidates.extend(await _get_live(cache, api_client))
    for item in candidates:
        if item.get("fixture", {}).get("id") == fixture_id:
            return item
    return None


async def _remember_user_and_lang(message: Message, database: Database, settings: Settings) -> str:
    await _remember_chat(message, database)
    if not message.from_user:
        return settings.default_language
    return normalize_language(
        await database.get_user_language(message.from_user.id, settings.default_language),
        settings.default_language,
    )


async def _remember_chat(message: Message, database: Database) -> None:
    if message.from_user:
        await database.upsert_user(message.from_user)
    if message.chat.type in {"group", "supergroup"}:
        await database.upsert_group(message.chat)


async def _event_lang(event: Message | CallbackQuery, database: Database, settings: Settings) -> str:
    if isinstance(event, CallbackQuery):
        return await _callback_lang(event, database, settings)
    return await _remember_user_and_lang(event, database, settings)


async def _callback_lang(callback: CallbackQuery, database: Database, settings: Settings) -> str:
    if not callback.from_user:
        return settings.default_language
    return normalize_language(
        await database.get_user_language(callback.from_user.id, settings.default_language),
        settings.default_language,
    )


def _message(event: Message | CallbackQuery) -> Message:
    return event if isinstance(event, Message) else event.message


async def _answer_callback(event: Message | CallbackQuery, text: str | None = None) -> None:
    if isinstance(event, CallbackQuery):
        await _safe_callback_answer(event, text)


async def _safe_callback_answer(callback: CallbackQuery, text: str | None = None) -> None:
    try:
        await callback.answer(text)
    except Exception:
        return


def _market_for(normalized_odds: Any, market_key: str) -> Any:
    if not normalized_odds:
        return None
    if market_key == "handicap":
        return normalized_odds.markets.get("asian_handicap") or normalized_odds.markets.get("handicap")
    return normalized_odds.markets.get(market_key)


async def _get_fixture_events_cached(
    cache: RedisCache,
    api_client: ApiFootballClient,
    fixture_id: int,
) -> tuple[list[dict[str, Any]], bool]:
    key = f"football:fixture_events:{fixture_id}"
    cached = await cache.get_json(key, None)
    if cached is not None:
        return cached, False
    try:
        events = await api_client.get_fixture_events(fixture_id)
        await cache.set_json(key, events, ttl_seconds=300)
        logger.info("fixture_events fixture_id=%s count=%s", fixture_id, len(events))
        return events, False
    except Exception as exc:
        cached = await cache.get_json(key, None)
        if cached is not None:
            return cached, False
        _log_api_failure(
            f"fixture-events:{fixture_id}",
            "fixture_events fixture_id=%s failed; keeping existing cache: %s",
            fixture_id,
            exc,
        )
        return [], True


async def _effective_settings(cache: RedisCache, settings: Settings) -> Settings:
    cutoff = await cache.get_text("football:admin:bet_cutoff_minutes")
    if cutoff is None:
        return settings
    try:
        return replace(settings, bet_cutoff_minutes=max(int(cutoff), 0))
    except ValueError:
        return settings


def _is_admin(telegram_user_id: int | None, settings: Settings) -> bool:
    return bool(
        telegram_user_id
        and (
            telegram_user_id in settings.super_admin_user_ids
            or telegram_user_id in settings.admin_user_ids
            or telegram_user_id in settings.agent_user_ids
        )
    )


def _admin_private_allowed(message: Message, settings: Settings) -> bool:
    user_id = message.from_user.id if message.from_user else None
    return _is_admin(user_id, settings) and message.chat.type == "private"


def _first_int_arg(command: CommandObject) -> int | None:
    try:
        return int(_clean_command_token((command.args or "").strip().split()[0]))
    except (IndexError, TypeError, ValueError):
        return None


def _clean_command_token(value: str) -> str:
    token = " ".join(str(value or "").strip().split())
    if token.startswith("<") and token.endswith(">") and len(token) >= 2:
        token = token[1:-1].strip()
    return token


def _parse_command_parts(args: str | None, maxsplit: int = -1) -> list[str]:
    return (args or "").strip().split(maxsplit=maxsplit)


def _parse_id_token(raw: str) -> int | None:
    token = _clean_command_token(raw)
    return int(token) if token.isdigit() else None


def _command_fixture_id(command: CommandObject) -> int | None:
    try:
        return int((command.args or "").strip().split()[0])
    except (IndexError, TypeError, ValueError):
        return None


def _count_by_date(fixtures: list[dict[str, Any]], fixture_date: date) -> int:
    prefix = fixture_date.isoformat()
    count = 0
    for item in fixtures:
        raw = str((item.get("fixture") or {}).get("date") or "")
        if raw.startswith(prefix):
            count += 1
            continue
        timestamp = (item.get("fixture") or {}).get("timestamp")
        if timestamp and datetime.fromtimestamp(int(timestamp)).date() == fixture_date:
            count += 1
    return count


async def _maybe_bind_referral(message: Message, command: CommandObject, database: Database) -> None:
    if not message.from_user:
        return
    args = (command.args or "").strip()
    if not args.startswith("ref_"):
        return
    code = args[4:].strip()
    parent_user_id = await database.referral_parent_by_code(code)
    if parent_user_id:
        await database.bind_referral_parent(message.from_user.id, parent_user_id)


async def _create_recharge_order(
    message: Message,
    user_id: int,
    amount: Decimal,
    database: Database,
    settings: Settings,
    gmpay_client: GMPayClient,
    network: str | None = None,
    lang: str = "zh",
) -> None:
    deposit_network = network or settings.gmpay_default_network
    if amount < settings.min_recharge_amount:
        await message.answer(f"最低充值金额：{_money(settings.min_recharge_amount)} {settings.wallet_currency}")
        return
    if amount > settings.max_recharge_amount:
        await message.answer(f"充值金额不能超过：{_money(settings.max_recharge_amount)} {settings.wallet_currency}")
        return
    for _ in range(5):
        order_id = generate_gmpay_order_id()
        try:
            order = await database.create_deposit_order(
                user_id,
                order_id,
                amount,
                settings.wallet_currency,
                deposit_network,
            )
            break
        except asyncpg.UniqueViolationError:
            continue
    else:
        logger.warning("failed to allocate unique gmpay order_id user_id=%s", user_id)
        await message.answer("充值订单创建失败，请稍后再试。")
        return
    logger.info(
        "creating gmpay deposit order order_id=%s order_id_length=%s amount=%s network=%s",
        order_id,
        len(order_id),
        amount,
        deposit_network,
    )
    try:
        transaction = await gmpay_client.create_transaction(
            order_id=order_id,
            amount=amount,
            user_id=user_id,
            notify_url=settings.gmpay_notify_url,
            redirect_url=settings.gmpay_redirect_url,
            network=deposit_network,
        )
    except Exception as exc:
        raw_response = _gmpay_create_failure_response(exc)
        await database.fail_deposit_order(order_id, raw_response, error_message="create transaction failed")
        logger.warning("gmpay create transaction failed order_id=%s", order_id, exc_info=True)
        await message.answer("充值订单创建失败，请稍后再试。")
        return
    original_payment_url = transaction.payment_url
    final_payment_url = _build_safe_gmpay_cashier_url(
        original_payment_url,
        transaction.trade_id,
        settings.gmpay_public_cashier_base_url,
    )
    if not final_payment_url:
        await database.fail_deposit_order(
            order_id,
            transaction.raw_json,
            error_message="invalid payment url",
            payment_url_check_status="invalid",
        )
        await message.answer("支付页面暂时不可用，请联系管理员。")
        return
    order = await database.update_deposit_order_transaction(
        order_id,
        trade_id=transaction.trade_id,
        actual_amount=transaction.actual_amount,
        token=transaction.token,
        network=transaction.network,
        payment_url=final_payment_url,
        original_payment_url=original_payment_url,
        final_payment_url=final_payment_url,
        payment_url_check_status="passed",
        expires_at=transaction.expires_at,
        raw_response=transaction.raw_json,
    ) or order
    prefix = "Deposit request created\nPlease wait for admin review\n\n" if lang == "en" else "充值申请已创建\n请等待管理员审核\n\n"
    await message.answer(prefix + _format_deposit_order(order, settings.wallet_currency, lang), reply_markup=_deposit_order_keyboard(order))


def _gmpay_create_failure_response(exc: Exception) -> dict[str, Any]:
    response: dict[str, Any] = {
        "error": str(exc),
        "type": exc.__class__.__name__,
    }
    if isinstance(exc, GMPayCreateOrderError):
        response["status_code"] = exc.status_code
        if exc.response_body:
            try:
                response["response_body"] = json.loads(exc.response_body)
            except json.JSONDecodeError:
                response["response_body"] = exc.response_body
    return response


def _build_safe_gmpay_cashier_url(original_url: str, trade_id: str | None, public_cashier_base_url: str) -> str | None:
    source = urlparse(str(original_url or ""))
    detected_trade_id = (trade_id or "").strip()
    prefix = "/pay/checkout-counter/"
    if source.path.startswith(prefix):
        detected_trade_id = source.path[len(prefix) :].strip("/").split("/", 1)[0] or detected_trade_id
    if not detected_trade_id:
        detected_trade_id = parse_qs(source.query).get("trade_id", [""])[0].strip()
    base = urlparse(public_cashier_base_url)
    if base.scheme != "https" or base.netloc != "pay.hosea.cc.cd":
        return None
    if not detected_trade_id or "/" in detected_trade_id or "\\" in detected_trade_id:
        return None
    final = f"{base.scheme}://{base.netloc}/cashier/{detected_trade_id}?t={int(time())}"
    return final if _safe_final_payment_url(final) else None


def _safe_final_payment_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.netloc != "pay.hosea.cc.cd":
        return False
    if parsed.path == "/" or not parsed.path.startswith("/cashier/"):
        return False
    lowered = value.lower()
    return not any(token in lowered for token in ("login", "admin", "dashboard", "panel", "backend"))


def _risk_blocks(risk: dict | None, action: str) -> bool:
    status = str((risk or {}).get("status") or "active")
    if status == "banned":
        return action in {"bet", "withdraw", "deposit", "rebate"}
    if status == "frozen":
        return action in {"bet", "withdraw"}
    if action == "bet" and bool((risk or {}).get("bet_restricted")):
        return True
    if action == "withdraw" and bool((risk or {}).get("withdraw_restricted")):
        return True
    return False


def _wallet_keyboard(lang: str = "zh") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "deposit_usdt"), callback_data="wallet:recharge")],
            [
                InlineKeyboardButton(text="Deposit Records" if lang == "en" else "充值记录", callback_data="wallet:records"),
                InlineKeyboardButton(text=t(lang, "ledger"), callback_data="wallet:ledger"),
            ],
            [InlineKeyboardButton(text=t(lang, "withdraw"), callback_data="wallet:withdraw_prompt")],
            [InlineKeyboardButton(text=t(lang, "back_home"), callback_data="home")],
        ]
    )


def _network_keyboard(prefix: str) -> InlineKeyboardMarkup:
    networks = [
        ("TRON / TRC20", "tron"),
        ("Polygon", "polygon"),
        ("BSC", "bsc"),
        ("Arbitrum", "arbitrum"),
        ("Ethereum", "ethereum"),
    ]
    rows = [[InlineKeyboardButton(text=label, callback_data=f"{prefix}:{value}")] for label, value in networks]
    rows.append([InlineKeyboardButton(text="取消", callback_data=f"{prefix}:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _cancel_keyboard(target: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="取消", callback_data=f"fsm_cancel:{target}")]])


def _recharge_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="确认创建订单", callback_data="recharge:confirm")],
            [InlineKeyboardButton(text="重新选择金额", callback_data="recharge:amounts")],
            [InlineKeyboardButton(text="取消", callback_data="fsm_cancel:wallet")],
        ]
    )


def _withdraw_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="提交申请", callback_data="withdraw:confirm")],
            [InlineKeyboardButton(text="取消", callback_data="fsm_cancel:wallet")],
        ]
    )


def _rebate_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="提交申请", callback_data="rebate:confirm")],
            [InlineKeyboardButton(text="取消", callback_data="fsm_cancel:referrals")],
        ]
    )


def _admin_adjust_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="确认调账", callback_data="admin_adjust:confirm")],
            [InlineKeyboardButton(text="取消", callback_data="fsm_cancel:admin")],
        ]
    )


def _recharge_amount_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="10 USDT", callback_data="wallet:amount:10"),
                InlineKeyboardButton(text="20 USDT", callback_data="wallet:amount:20"),
            ],
            [
                InlineKeyboardButton(text="50 USDT", callback_data="wallet:amount:50"),
                InlineKeyboardButton(text="100 USDT", callback_data="wallet:amount:100"),
            ],
            [InlineKeyboardButton(text="自定义金额", callback_data="wallet:amount:custom")],
            [InlineKeyboardButton(text="返回钱包", callback_data="wallet")],
        ]
    )


def _deposit_order_keyboard(order: dict | None) -> InlineKeyboardMarkup:
    rows = []
    if order and order.get("payment_url"):
        rows.append([InlineKeyboardButton(text="打开收银台", url=str(order["payment_url"]))])
    if order:
        rows.append([InlineKeyboardButton(text="刷新充值状态", callback_data=f"deposit:refresh:{order['order_id']}")])
    rows.append([InlineKeyboardButton(text="返回钱包", callback_data="wallet")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _recharge_amount_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="2 USDT", callback_data="wallet:amount:2"),
                InlineKeyboardButton(text="5 USDT", callback_data="wallet:amount:5"),
            ],
            [
                InlineKeyboardButton(text="10 USDT", callback_data="wallet:amount:10"),
                InlineKeyboardButton(text="20 USDT", callback_data="wallet:amount:20"),
            ],
            [
                InlineKeyboardButton(text="50 USDT", callback_data="wallet:amount:50"),
                InlineKeyboardButton(text="100 USDT", callback_data="wallet:amount:100"),
            ],
            [InlineKeyboardButton(text="自定义金额", callback_data="wallet:amount:custom")],
            [InlineKeyboardButton(text="返回钱包", callback_data="wallet")],
        ]
    )


def _referral_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="下级管理", callback_data="referrals:children"),
                InlineKeyboardButton(text="返佣记录", callback_data="referrals:commissions"),
            ],
            [
                InlineKeyboardButton(text="申请返水", callback_data="referrals:rebate_apply"),
                InlineKeyboardButton(text="申请成为代理", callback_data="referrals:agent_apply"),
            ],
            [InlineKeyboardButton(text="复制邀请链接", callback_data="referrals:copy")],
            [InlineKeyboardButton(text="返回首页", callback_data="home")],
        ]
    )


def _referral_keyboard(role: str = "user", application: dict | None = None) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="下级管理", callback_data="referrals:children"),
            InlineKeyboardButton(text="返佣记录", callback_data="referrals:commissions"),
        ],
        [InlineKeyboardButton(text="返水管理", callback_data="referrals:rebate_apply")],
    ]
    if role in {"agent", "admin", "super_admin"}:
        rows.append(
            [
                InlineKeyboardButton(text="下级充值", callback_data="referrals:sub_deposits"),
                InlineKeyboardButton(text="下级投注", callback_data="referrals:sub_bets"),
                InlineKeyboardButton(text="下级返水", callback_data="referrals:sub_rebates"),
            ]
        )
    else:
        status = str((application or {}).get("status") or "")
        if status == "pending":
            rows.append([InlineKeyboardButton(text="代理申请审核中", callback_data="referrals:agent_pending")])
        else:
            rows.append([InlineKeyboardButton(text="申请成为代理", callback_data="referrals:agent_apply")])
    rows.extend(
        [
            [InlineKeyboardButton(text="复制邀请链接", callback_data="referrals:copy")],
            [InlineKeyboardButton(text="返回首页", callback_data="home")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_wallet(wallet: dict, currency: str, lang: str = "zh") -> str:
    if lang == "en":
        return (
            "💰 Wallet\n"
            f"Balance: {_money(wallet.get('balance'))} {currency}\n"
            f"Frozen: {_money(wallet.get('frozen_balance'))} {currency}"
        )
    return (
        "💰 钱包\n"
        f"余额：{_money(wallet.get('balance'))} {currency}\n"
        f"冻结：{_money(wallet.get('frozen_balance'))} {currency}\n"
        f"累计充值：{_money(wallet.get('total_deposit'))} {currency}"
    )


def _format_recharge_confirm(data: dict[str, Any], settings: Settings, lang: str = "zh") -> str:
    if lang == "en":
        return (
            "Confirm Deposit\n\n"
            f"Amount: {_money(data.get('amount'))} {settings.wallet_currency}\n"
            "Payment: GMPay cashier\n"
            "Network/Token: select on cashier page\n"
            f"Expires: {settings.gmpay_order_expire_minutes} minutes"
        )
    return (
        "确认充值\n\n"
        f"金额：{_money(data.get('amount'))} {settings.wallet_currency}\n"
        "支付方式：GMPay 收银台\n"
        "链/代币：请在收银台页面选择\n"
        f"有效期：{settings.gmpay_order_expire_minutes} 分钟"
    )


def _format_withdraw_confirm(data: dict[str, Any], currency: str, lang: str = "zh") -> str:
    if lang == "en":
        return (
            "🏧 Confirm Withdrawal\n\n"
            f"Amount: {_money(data.get('amount'))} {currency}\n"
            f"Network: {_network_label(str(data.get('network') or ''))}\n"
            f"Address: {data.get('address') or '-'}\n\n"
            "Withdrawals require admin review."
        )
    return (
        "🏧 确认提现申请\n\n"
        f"金额：{_money(data.get('amount'))} {currency}\n"
        f"网络：{_network_label(str(data.get('network') or ''))}\n"
        f"地址：{data.get('address') or '-'}\n\n"
        "提现需要管理员审核，不会自动出款。"
    )


def _format_rebate_confirm(data: dict[str, Any]) -> str:
    return (
        "🎁 返水申请\n\n"
        f"本次申请投注额：{_money(data.get('turnover'))} USDT\n"
        f"返水比例：{_percent_text(data.get('rebate_rate'))}\n"
        f"预计返水：{_money(data.get('rebate_amount'))} USDT\n"
        f"申请说明：{data.get('note') or '-'}"
    )


def _format_agent_progress(metrics: dict[str, Any], settings: Settings) -> str:
    return (
        "当前还未达到代理申请条件：\n\n"
        f"累计充值：{_money(metrics.get('total_deposit'))} / {_money(settings.agent_min_total_deposit)}\n"
        f"累计投注：{_money(metrics.get('total_turnover'))} / {_money(settings.agent_min_total_turnover)}\n"
        f"有效下级：{metrics.get('valid_referrals') or 0} / {settings.agent_min_valid_referrals}"
    )


def _format_admin_adjust_confirm(data: dict[str, Any]) -> str:
    return (
        "确认调账\n\n"
        f"用户：{data.get('target_user_id')}\n"
        f"金额：{data.get('amount')}\n"
        f"原因：{data.get('reason')}"
    )


def _network_label(network: str) -> str:
    return {
        "tron": "TRON / TRC20",
        "polygon": "Polygon",
        "bsc": "BSC",
        "arbitrum": "Arbitrum",
        "ethereum": "Ethereum",
    }.get(network, network or "-")


def _format_deposit_order(order: dict, currency: str, lang: str = "zh") -> str:
    status = str(order.get("status") or "")
    if lang == "en":
        return (
            "Deposit request created\n\n"
            f"Order ID: {order.get('order_id')}\n"
            f"Status: {status}\n"
            f"Amount: {_money(order.get('amount_requested'))} {currency}\n"
            f"Payment Amount: {_money(order.get('actual_amount') or order.get('amount_requested'))} {currency}\n\n"
            "Open the cashier below to complete payment.\n"
            "Please wait for admin review."
        )
    return (
        "充值订单已创建\n\n"
        f"订单号：{order.get('order_id')}\n"
        f"状态：{status}\n"
        f"金额：{_money(order.get('amount_requested'))} {currency}\n"
        f"实际需支付：{_money(order.get('actual_amount') or order.get('amount_requested'))} {currency}\n"
        "链/代币：请在收银台页面选择\n"
        "有效期：30 分钟\n\n"
        "请点击下方按钮打开收银台完成支付。\n"
        "请以收银台页面显示的链、地址和实际金额为准。\n\n"
        "支付须知\n"
        "1. 请按收银台页面显示的实际金额支付。\n"
        "2. 请勿少付、多付或分多笔支付。\n"
        "3. 如果金额不一致，可能不会自动到账。\n"
        "4. 如已付款但未到账，请保存 txid 并联系管理员核查。\n\n"
        f"{_deposit_status_hint(status)}"
    )


def _format_rebate_requests(rows: list[dict | None], lang: str = "zh") -> str:
    clean = [row for row in rows if row]
    if not clean:
        return "🎁 Rebate Management\n\nNo pending rebate requests." if lang == "en" else "🎁 返水管理\n\n暂无待审核返水申请。"
    lines = ["🎁 Rebate Management", "", "Pending rebate requests:"] if lang == "en" else ["🎁 返水管理", "", "待审核返水申请："]
    for row in clean:
        stake = _money(row.get("stake_amount") or row.get("turnover"))
        amount = _money(row.get("rebate_amount") or row.get("requested_amount"))
        rate = _percent_text(row.get("rebate_rate"))
        if lang == "en":
            lines.extend(
                [
                    "",
                    f"#{row.get('id')}",
                    f"User: {row.get('user_id')}",
                    f"Stake Amount: {stake} USDT",
                    f"Rebate Rate: {rate}",
                    f"Rebate Amount: {amount} USDT",
                    f"Status: {row.get('status')}",
                    f"Created At: {row.get('created_at')}",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    f"#{row.get('id')}",
                    f"用户：{row.get('user_id')}",
                    f"申请投注额：{stake} USDT",
                    f"返水比例：{rate}",
                    f"预计返水：{amount} USDT",
                    f"状态：{row.get('status')}",
                    f"申请时间：{row.get('created_at')}",
                ]
            )
    lines.extend(
        [
            "",
            "Commands:" if lang == "en" else "命令：",
            "/admin_approve_rebate <request_id>",
            "/admin_reject_rebate <request_id> reason",
        ]
    )
    return "\n".join(lines)


def _format_cancel_requests(rows: list[dict]) -> str:
    if not rows:
        return "暂无待审核退单申请。"
    lines = ["待审核退单申请"]
    for row in rows:
        lines.append(
            f"#{row.get('id')} bet={row.get('bet_no') or row.get('bet_id')} "
            f"user={row.get('user_id')} stake={row.get('stake')} status={row.get('bet_status')}"
        )
    lines.append("命令：/admin_approve_cancel <request_id> <reason> 或 /admin_reject_cancel <request_id> <reason>")
    return "\n".join(lines)


def _format_payout_freezes(rows: list[dict], currency: str) -> str:
    if not rows:
        return "暂无冻结派彩。"
    lines = ["冻结派彩"]
    for row in rows:
        lines.append(
            f"#{row.get('id')} user={row.get('user_id')} bet={row.get('bet_id') or '-'} "
            f"amount={_money(row.get('amount'))} {currency} status={row.get('status')} unlock_at={row.get('unlock_at')}"
        )
    return "\n".join(lines)


def _format_wallet_freezes(rows: list[dict], currency: str) -> str:
    if not rows:
        return "暂无余额冻结记录。"
    lines = ["余额冻结记录"]
    for row in rows:
        lines.append(
            f"#{row.get('id')} user={row.get('user_id')} amount={_money(row.get('amount'))} {currency} "
            f"type={row.get('freeze_type')} status={row.get('status')} reason={row.get('reason') or '-'}"
        )
    return "\n".join(lines)


def _deposit_status_hint(status: str) -> str:
    normalized = status.lower()
    if normalized == "pending":
        return "订单待支付或等待链上确认。\n请以收银台页面显示的实际金额为准。"
    if normalized == "paid":
        return "充值已到账。"
    if normalized == "manual_review":
        return "订单金额或状态异常，已进入人工核查。\n请准备 txid 联系管理员。"
    if normalized == "expired":
        return "订单已过期，请重新创建充值订单。"
    if normalized == "failed":
        return "订单创建失败或已被拒绝，请重新尝试。"
    if normalized == "cancelled":
        return "订单已取消。"
    return "请打开收银台查看订单状态。"


def _format_admin_deposit_order(order: dict | None) -> str:
    if not order:
        return "订单不存在。"
    return (
        "充值订单详情\n\n"
        f"order_id={order.get('order_id')}\n"
        f"user_id={order.get('user_id')}\n"
        f"amount_requested={_money(order.get('amount_requested'))}\n"
        f"actual_amount={_money(order.get('actual_amount'))}\n"
        f"status={order.get('status')}\n"
        f"manual_review_required={order.get('manual_review_required')}\n"
        f"manual_review_note={order.get('manual_review_note') or '-'}\n"
        f"error_message={order.get('error_message') or '-'}\n"
        f"trade_id={order.get('trade_id') or '-'}\n"
        f"chain_tx_id={order.get('chain_tx_id') or '-'}\n"
        f"network={order.get('network') or '-'}\n"
        f"payment_url={order.get('payment_url') or '-'}\n"
        f"raw_response_json={_short_json(order.get('raw_response_json'))}\n"
        f"raw_callback_json={_short_json(order.get('raw_callback_json'))}\n"
        f"created_at={order.get('created_at')}\n"
        f"paid_at={order.get('paid_at') or '-'}"
    )


def _format_deposit_order(order: dict, currency: str) -> str:
    status = str(order.get("status") or "")
    return (
        "充值订单已创建\n\n"
        f"订单号：{order.get('order_id')}\n"
        f"状态：{status}\n"
        f"金额：{_money(order.get('amount_requested'))} {currency}\n"
        f"实际需支付：{_money(order.get('actual_amount') or order.get('amount_requested'))} {currency}\n\n"
        "请点击下方按钮打开收银台完成支付。\n"
        "请以收银台页面显示的链、地址和实际金额为准。\n\n"
        "如果页面异常，请点击右上角选择在浏览器打开，不要点击页面内返回首页。\n\n"
        f"{_deposit_status_hint(status)}"
    )


def _short_json(value: Any) -> str:
    try:
        text = json.dumps(value or {}, ensure_ascii=False, default=str)
    except Exception:
        text = str(value or {})
    return text if len(text) <= 1200 else text[:1200] + "...(truncated)"


def _format_deposit_records(rows: list[dict]) -> str:
    if not rows:
        return "暂无充值记录。"
    lines = ["充值记录"]
    for row in rows:
        lines.append(
            f"{row.get('order_id')} | user={row.get('user_id')} | {_money(row.get('actual_amount') or row.get('amount_requested'))} | {row.get('status')}"
        )
    return "\n".join(lines)


def _format_ledger(rows: list[dict]) -> str:
    if not rows:
        return "暂无账变记录。"
    lines = ["账变记录"]
    for row in rows:
        lines.append(
            f"{row.get('type')} {_money(row.get('amount'))} -> {_money(row.get('balance_after'))} | {row.get('description') or '-'}"
        )
    return "\n".join(lines)


def _format_referrals(link: str, summary: dict, currency: str) -> str:
    return (
        "👥 邀请推广\n"
        "我的邀请链接：\n"
        f"{link}\n\n"
        f"直属下级：{summary.get('direct_count') or 0} 人\n"
        f"累计充值：{_money(summary.get('total_deposit'))} {currency}\n"
        f"待结算返佣：{_money(summary.get('pending_commission'))} {currency}\n"
        f"已结算返佣：{_money(summary.get('settled_commission'))} {currency}"
    )


def _format_referral_children(rows: list[dict]) -> str:
    if not rows:
        return "暂无直属下级。"
    lines = ["直属下级"]
    for row in rows:
        name = row.get("username") or row.get("first_name") or "-"
        lines.append(f"{row.get('user_id')} {name}")
    return "\n".join(lines)


def _format_admin_referral_summary(summary: dict, currency: str) -> str:
    return (
        "下级统计\n"
        f"直属下级：{summary.get('direct_count') or 0} 人\n"
        f"累计下级充值：{_money(summary.get('total_deposit'))} {currency}\n"
        f"待结算返佣：{_money(summary.get('pending_commission'))} {currency}\n"
        f"已结算返佣：{_money(summary.get('settled_commission'))} {currency}"
    )


def _format_commissions(rows: list[dict]) -> str:
    if not rows:
        return "暂无返佣记录。"
    lines = ["返佣记录"]
    for row in rows:
        lines.append(
            f"#{row.get('id')} user={row.get('user_id')} source={row.get('source_user_id')} {_money(row.get('amount'))} {row.get('status')}"
        )
    return "\n".join(lines)


def _format_admin_dashboard(row: dict, currency: str) -> str:
    return (
        "管理员面板\n"
        f"今日充值：{_money(row.get('today_deposit'))} {currency}\n"
        f"今日提现申请：{_money(row.get('today_withdraw_request'))} {currency}\n"
        f"待结算注单：{row.get('pending_bets') or 0}\n"
        f"待审核提现：{row.get('pending_withdrawals') or 0}\n"
        f"待结算佣金：{row.get('pending_commissions') or 0}\n"
        f"待结算返水：{row.get('pending_rebates') or 0}\n"
        f"用户总数：{row.get('total_users') or 0}\n"
        f"有效代理数：{row.get('active_agents') or 0}"
    )


def _format_referrals(link: str, summary: dict, currency: str) -> str:
    return (
        "邀请推广\n"
        "我的邀请链接：\n"
        f"{link}\n\n"
        f"直属下级：{summary.get('direct_count') or 0} 人\n"
        f"有效下级：{summary.get('active_count') or 0} 人\n"
        f"下级总充值：{_money(summary.get('total_deposit'))} {currency}\n"
        f"下级总投注流水：{_money(summary.get('total_turnover'))} {currency}\n"
        f"待结算佣金：{_money(summary.get('pending_commission'))} {currency}\n"
        f"已结算佣金：{_money(summary.get('settled_commission'))} {currency}\n"
        f"待结算返水：{_money(summary.get('pending_rebate'))} {currency}"
    )


def _format_referral_children(rows: list[dict]) -> str:
    if not rows:
        return "暂无直属下级。"
    lines = ["直属下级"]
    for row in rows:
        name = row.get("username") or row.get("first_name") or "-"
        lines.append(
            f"{row.get('user_id')} {name} | registered={row.get('created_at')} "
            f"| deposit={_money(row.get('total_deposit'))} | turnover={_money(row.get('total_turnover'))} "
            f"| active={'Y' if row.get('is_active') else 'N'}"
        )
    return "\n".join(lines)


def _format_admin_referral_summary(summary: dict, currency: str) -> str:
    return (
        "下级统计\n"
        f"直属下级：{summary.get('direct_count') or 0} 人\n"
        f"有效下级：{summary.get('active_count') or 0} 人\n"
        f"累计下级充值：{_money(summary.get('total_deposit'))} {currency}\n"
        f"累计下级投注流水：{_money(summary.get('total_turnover'))} {currency}\n"
        f"待结算返佣：{_money(summary.get('pending_commission'))} {currency}\n"
        f"已结算返佣：{_money(summary.get('settled_commission'))} {currency}\n"
        f"待结算返水：{_money(summary.get('pending_rebate'))} {currency}"
    )


def _format_referrals(
    link: str,
    summary: dict,
    currency: str,
    role: str = "user",
    application: dict | None = None,
) -> str:
    lines = [
        "👥 推广邀请",
        "我的邀请链接：",
        link,
        "",
        f"直属下级：{summary.get('direct_count') or 0} 人",
        f"有效下级：{summary.get('active_count') or 0} 人",
        f"累计返佣：{_money(summary.get('settled_commission'))} {currency}",
        f"待结算返佣：{_money(summary.get('pending_commission'))} {currency}",
    ]
    if role in {"super_admin", "admin", "agent"}:
        lines.insert(1, f"当前身份：{_role_label(role)}")
    elif application and str(application.get("status")) == "pending":
        lines.append("")
        lines.append("代理申请审核中")
    elif application and str(application.get("status")) == "rejected":
        lines.append("")
        lines.append("代理申请未通过，可重新申请成为代理。")
    return "\n".join(lines)


def _format_admin_bets(rows: list[dict]) -> str:
    if not rows:
        return "暂无待结算注单。"
    lines = ["待结算注单"]
    for row in rows:
        lines.append(
            f"#{row.get('id')} user={row.get('user_id')} {row.get('fixture_label')} "
            f"{row.get('selection')} stake={row.get('stake')} payout={row.get('potential_payout')}"
        )
    return "\n".join(lines)


def _format_admin_bet(row: dict | None) -> str:
    if not row:
        return "注单不存在。"
    return (
        f"注单 #{row.get('id')}\n"
        f"user={row.get('user_id')}\n"
        f"fixture={row.get('fixture_label')}\n"
        f"market={row.get('market_title')}\n"
        f"selection={row.get('selection')}\n"
        f"stake={row.get('stake')}\n"
        f"odds={row.get('odds')}\n"
        f"potential_payout={row.get('potential_payout')}\n"
        f"status={row.get('status')}\n"
        f"balance_frozen={row.get('balance_frozen')}"
    )


def _format_withdrawals(rows: list[dict]) -> str:
    if not rows:
        return "暂无待审核提现。"
    lines = ["待审核提现"]
    for row in rows:
        lines.append(
            f"#{row.get('id')} user={row.get('user_id')} amount={_money(row.get('amount'))} "
            f"{row.get('network') or '-'} {row.get('status')}"
        )
    return "\n".join(lines)


def _format_withdraw(row: dict | None) -> str:
    if not row:
        return "提现申请不存在。"
    return (
        f"提现 #{row.get('id')}\n"
        f"user={row.get('user_id')}\n"
        f"amount={_money(row.get('amount'))}\n"
        f"network={row.get('network') or '-'}\n"
        f"address={row.get('address') or '-'}\n"
        f"status={row.get('status')}\n"
        f"admin_note={row.get('admin_note') or '-'}"
    )


def _format_rebate_rules(rows: list[dict]) -> str:
    if not rows:
        return "暂无返水规则。请直接在 rebate_rules 表配置 active 规则。"
    lines = ["返水规则"]
    for row in rows:
        lines.append(
            f"#{row.get('id')} {row.get('name')} mode={row.get('mode')} "
            f"active_ref={row.get('min_active_referrals')} turnover={_money(row.get('min_turnover'))} "
            f"rate={row.get('rebate_rate')} {row.get('status')}"
        )
    return "\n".join(lines)


def _format_rebates(rows: list[dict]) -> str:
    if not rows:
        return "暂无返水记录。"
    lines = ["返水记录"]
    for row in rows:
        lines.append(
            f"#{row.get('id')} user={row.get('user_id')} amount={_money(row.get('rebate_amount'))} "
            f"turnover={_money(row.get('turnover'))} active_ref={row.get('active_referrals')} {row.get('status')}"
        )
    return "\n".join(lines)


def _format_admin_users(rows: list[dict]) -> str:
    if not rows:
        return "暂无用户。"
    lines = ["用户列表"]
    for row in rows:
        lines.append(
            f"{row.get('telegram_user_id')} {row.get('username') or row.get('first_name') or '-'} "
            f"role={row.get('role')} balance={_money(row.get('balance'))}"
        )
    return "\n".join(lines)


def _format_admin_user(row: dict | None) -> str:
    if not row:
        return "用户不存在。"
    return (
        "用户详情\n"
        f"user_id={row.get('telegram_user_id')}\n"
        f"name={row.get('username') or row.get('first_name') or '-'}\n"
        f"role={row.get('role')}\n"
        f"balance={_money(row.get('balance'))}\n"
        f"frozen={_money(row.get('frozen_balance'))}\n"
        f"direct_referrals={row.get('direct_referrals') or 0}\n"
        f"bets_count={row.get('bets_count') or 0}"
    )


def _format_agent_applications(rows: list[dict]) -> str:
    if not rows:
        return "暂无待审核代理申请。"
    lines = ["代理申请"]
    for row in rows:
        lines.append(
            f"#{row.get('id')} user={row.get('user_id')} deposit={_money(row.get('total_deposit'))} "
            f"turnover={_money(row.get('total_turnover'))} referrals={row.get('valid_referrals')} {row.get('status')}"
        )
    return "\n".join(lines)


async def _send_bets_page(
    message: Message,
    user_id: int,
    status_group: str,
    page: int,
    database: Database,
    settings: Settings,
) -> None:
    page = max(page, 0)
    per_page = 5
    stats = await database.get_user_bet_stats(user_id)
    rows = await database.list_user_bets(user_id, status_group=status_group, limit=per_page, offset=page * per_page)
    total = int(stats.get("settled_count") or 0) if status_group == "settled" else (
        int(stats.get("pending_count") or 0) + int(stats.get("manual_required_count") or 0)
    )
    await message.answer(
        _format_bets_page(rows, stats, status_group, settings),
        reply_markup=my_bets_keyboard(
            rows,
            status_group,
            page,
            has_prev=page > 0,
            has_next=(page + 1) * per_page < total,
        ),
    )


async def _send_bet_confirm_for_amount(
    message: Message,
    fixture_id: int,
    market_key: str,
    page: int,
    outcome_index: int,
    amount: str,
    cache: RedisCache,
    api_client: ApiFootballClient,
    settings: Settings,
    lang: str = "zh",
) -> None:
    fixture = await _find_cached_fixture(cache, api_client, settings, fixture_id)
    normalized_odds = await _get_fixture_odds(cache, api_client, fixture_id)
    market = _market_for(normalized_odds, market_key)
    outcomes = market.outcomes[page * 20 : (page + 1) * 20] if market else []
    outcome = outcomes[outcome_index] if outcome_index < len(outcomes) else None
    if not fixture or not outcome:
        await message.answer("该赔率当前不可用，请返回赛事重新选择。")
        return
    await message.answer(
        format_bet_confirm(
            fixture,
            getattr(market, "title", market_key),
            _outcome_button_label(outcome),
            outcome.odds,
            stake=amount,
            lang=lang,
        )
        + "\n\n"
        + _bet_mode_notice(settings),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="确认下注", callback_data=f"bet_confirm:{fixture_id}:{market_key}:{page}:{outcome_index}:{amount}")],
                [InlineKeyboardButton(text="修改金额", callback_data=f"bet_amount:{fixture_id}:{market_key}:{page}:{outcome_index}")],
                [InlineKeyboardButton(text="取消", callback_data=f"odds:fixture:{fixture_id}:market:{market_key}:page:{page}")],
            ]
        ),
    )


async def _notify_admins(bot: Any, settings: Settings, text: str) -> None:
    for user_id in settings.super_admin_user_ids | settings.admin_user_ids:
        await _notify_user(bot, user_id, text)


async def _notify_user(bot: Any, user_id: int | None, text: str) -> None:
    if not user_id:
        return
    try:
        await bot.send_message(int(user_id), text)
    except Exception:
        logger.info("failed to send notification user_id=%s", user_id, exc_info=True)


async def _notify_super_admins_rebate(bot: Any, database: Database, settings: Settings, row: dict) -> None:
    for user_id in settings.super_admin_user_ids:
        lang = normalize_language(await database.get_user_language(int(user_id), settings.default_language), settings.default_language)
        if lang == "en":
            text = (
                "🎁 New Rebate Request\n\n"
                f"Request ID: {row.get('id')}\n"
                f"User: {row.get('user_id')}\n"
                f"Stake Amount: {_money(row.get('stake_amount') or row.get('turnover'))} {settings.wallet_currency}\n"
                f"Rebate Rate: {_percent_text(row.get('rebate_rate'))}\n"
                f"Rebate Amount: {_money(row.get('rebate_amount') or row.get('requested_amount'))} {settings.wallet_currency}\n"
                f"Status: {row.get('status')}\n\n"
                "Commands:\n"
                f"/admin_approve_rebate {row.get('id')}\n"
                f"/admin_reject_rebate {row.get('id')} reason"
            )
        else:
            text = (
                "🎁 新的返水申请\n\n"
                f"申请ID：{row.get('id')}\n"
                f"用户：{row.get('user_id')}\n"
                f"本次申请投注额：{_money(row.get('stake_amount') or row.get('turnover'))} {settings.wallet_currency}\n"
                f"返水比例：{_percent_text(row.get('rebate_rate'))}\n"
                f"预计返水：{_money(row.get('rebate_amount') or row.get('requested_amount'))} {settings.wallet_currency}\n"
                f"状态：{row.get('status')}\n\n"
                "命令：\n"
                f"/admin_approve_rebate {row.get('id')}\n"
                f"/admin_reject_rebate {row.get('id')} reason"
            )
        await _notify_user(bot, int(user_id), text)


def _format_bets_page(rows: list[dict], stats: dict, status_group: str, settings: Settings) -> str:
    title = "📊 我的注单"
    pending_count = int(stats.get("pending_count") or 0)
    manual_required_count = int(stats.get("manual_required_count") or 0)
    settled_count = int(stats.get("settled_count") or 0)
    simulated_pending_count = int(stats.get("simulated_pending_count") or 0)
    lines = [
        title,
        "",
        f"我的待结算注单：{pending_count} 张",
        f"其中模拟注单：{simulated_pending_count} 张",
        f"待人工结算：{manual_required_count} 张",
        f"已结算：{settled_count} 张",
    ]
    if not settings.real_betting_enabled:
        lines.append("当前为模拟下注模式，不扣真实余额。")
        if settings.bet_require_balance_for_simulation:
            lines.append("模拟下注仍需钱包余额覆盖下注金额。")
    lines.append("")
    if not rows:
        lines.append("暂无注单。")
        return "\n".join(lines)
    for index, bet in enumerate(rows, 1):
        lines.append(
            f"{index}. {bet.get('bet_no') or bet.get('id')} | {bet.get('fixture_label') or '-'} | "
            f"{_money(bet.get('stake'))} USDT | {_bet_status_label(str(bet.get('status')))}"
        )
    return "\n".join(lines)


def _format_bet_created(bet: dict, currency: str) -> str:
    return (
        "🎫 注单已创建\n\n"
        f"注单号：{bet.get('bet_no') or bet.get('id')}\n"
        f"比赛：{bet.get('fixture_label') or '-'}\n"
        f"玩法：{bet.get('market_title') or bet.get('market_key') or '-'}\n"
        f"选择：{bet.get('selection') or '-'}\n"
        f"金额：{_money(bet.get('stake'))} {currency}\n"
        f"赔率：{bet.get('odds') or '-'}\n"
        f"预计返还：{_money(bet.get('potential_payout'))} {currency}\n"
        "状态：待结算"
    )


def _format_insufficient_balance(stake: Decimal, balance: Decimal, currency: str) -> str:
    return (
        "💰 钱包余额不足\n\n"
        f"本次下注：{_money(stake)} {currency}\n"
        f"当前余额：{_money(balance)} {currency}\n\n"
        "请先充值后再下注。"
    )


def _insufficient_balance_keyboard(fixture_id: int | None = None) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="充值 USDT", callback_data="wallet:recharge")]]
    if fixture_id is not None:
        rows.append([InlineKeyboardButton(text="返回赛事", callback_data=f"fixture:{fixture_id}")])
    rows.append([InlineKeyboardButton(text="返回首页", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _bet_action_keyboard(
    bet_id_or_no: str,
    status: str,
    status_group: str = "pending",
    page: int = 0,
    *,
    fixture_id: int | None = None,
) -> InlineKeyboardMarkup:
    rows = []
    if status in {"pending", "manual_required"}:
        rows.append([InlineKeyboardButton(text="查看开奖", callback_data=f"bet_settle:{bet_id_or_no}")])
    if fixture_id is not None:
        rows.append([InlineKeyboardButton(text="返回赛事", callback_data=f"fixture:{fixture_id}")])
    else:
        rows.append([InlineKeyboardButton(text="返回我的注单", callback_data=f"bets:{status_group}:{page}")])
    rows.append([InlineKeyboardButton(text="返回首页", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _bet_unavailable_message(reason: str) -> str:
    if reason in {"cutoff_reached", "suspended_by_admin"}:
        return "本场比赛已封盘，无法下注。"
    if reason == "already_started":
        return "本场比赛已开始，当前暂不支持滚球下注。"
    if reason in {"no_odds", "no_market"}:
        return "赔率已更新，请返回赛事重新选择。"
    return f"当前不可投注：{reason_label(reason)}"


def _format_bet_detail(bet: dict, currency: str) -> str:
    status = str(bet.get("status") or "")
    settled = status in {"won", "lost", "void", "cancelled"}
    title = "🎫 已结算注单" if settled else "🎫 注单详情"
    lines = [
        title,
        "",
        f"注单号：{bet.get('bet_no') or bet.get('id')}",
        f"比赛：{bet.get('fixture_label') or '-'}",
        f"玩法：{bet.get('market_title') or bet.get('market_key') or '-'}",
        f"选择：{bet.get('selection') or '-'}",
    ]
    if settled:
        lines.append(f"赛果：{bet.get('result_score') or '-'}")
    lines.extend(
        [
            f"金额：{_money(bet.get('stake'))} {currency}",
            f"赔率：{bet.get('odds') or '-'}",
            f"预计返还：{_money(bet.get('potential_payout'))} {currency}",
        ]
    )
    if settled:
        lines.append(f"返还：{_money(bet.get('payout'))} {currency}")
    lines.append(f"状态：{_bet_status_label(status)}")
    if bet.get("settled_at"):
        lines.append(f"结算时间：{bet.get('settled_at')}")
    if bet.get("settlement_note"):
        lines.append(f"备注：{bet.get('settlement_note')}")
    return "\n".join(lines)


def _bet_status_label(status: str) -> str:
    return {
        "pending": "待结算",
        "manual_required": "待人工结算",
        "won": "已中奖",
        "lost": "未中奖",
        "void": "已作废",
        "cancelled": "已取消",
    }.get(status, status or "-")


def _format_admin_bets(rows: list[dict]) -> str:
    if not rows:
        return "暂无待开奖注单。"
    lines = ["注单开奖"]
    for row in rows:
        lines.append(
            f"#{row.get('id')} user={row.get('user_id')} {row.get('fixture_label')} "
            f"{row.get('selection')} stake={row.get('stake')} payout={row.get('potential_payout')}"
        )
    lines.append("\n命令：/admin_settle_win 判定中奖，/admin_settle_loss 判定未中奖，/admin_settle_void 作废退还。")
    return "\n".join(lines)


def _validated_amount(raw: str, minimum: Decimal, maximum: Decimal) -> Decimal:
    try:
        amount = Decimal(str(raw).strip())
    except Exception as exc:
        raise ValueError("金额必须是数字。") from exc
    if amount.as_tuple().exponent < -2:
        raise ValueError("金额最多支持 2 位小数。")
    if amount < minimum or amount > maximum:
        raise ValueError(f"金额范围：{_money(minimum)}-{_money(maximum)} USDT")
    return amount.quantize(Decimal("0.01"))


def _fixture_start_time(fixture: dict[str, Any]) -> datetime | None:
    raw = (fixture.get("fixture") or {}).get("date")
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    timestamp = (fixture.get("fixture") or {}).get("timestamp")
    if timestamp:
        try:
            return datetime.fromtimestamp(int(timestamp))
        except (TypeError, ValueError, OSError):
            return None
    return None


def _money(value: Any) -> str:
    try:
        return f"{Decimal(str(value or 0)):.2f}"
    except Exception:
        return "0.00"


def _percent_text(value: Any) -> str:
    try:
        percent = (Decimal(str(value or 0)) * Decimal("100")).quantize(Decimal("0.01"))
        text = f"{percent:.2f}".rstrip("0").rstrip(".")
        return f"{text}%"
    except Exception:
        return "0%"


def _localized_fixtures(fixtures: list[dict[str, Any]], lang: str) -> list[dict[str, Any]]:
    return [_localized_fixture(item, lang) for item in fixtures]


def _localized_fixture(item: dict[str, Any], lang: str) -> dict[str, Any]:
    copied = deepcopy(item)
    league = copied.get("league") or {}
    if "name" in league:
        league["name"] = league.get("name") if lang == "en" else zh_league_name(league.get("name"))
    teams = copied.get("teams") or {}
    for side in ("home", "away"):
        if isinstance(teams.get(side), dict) and "name" in teams[side]:
            teams[side]["name"] = teams[side].get("name") if lang == "en" else zh_team_name(teams[side].get("name"))
    return copied


def _outcome_button_label(outcome: object) -> str:
    label = getattr(outcome, "label", "-")
    group = getattr(outcome, "group", None)
    if group == "home" and str(label).lower() in {"home", "1"}:
        return "主胜"
    if group == "draw" and str(label).lower() in {"draw", "x"}:
        return "平局"
    if group == "away" and str(label).lower() in {"away", "2"}:
        return "客胜"
    if group == "over":
        return str(label).replace("Over", "大", 1)
    if group == "under":
        return str(label).replace("Under", "小", 1)
    return str(label)


def _translated_texts(key: str) -> set[str]:
    return {t(lang, key) for lang in SUPPORTED_LANGUAGES}


def _worldcup_home_keyboard(lang: str = "zh") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 " + t(lang, "worldcup_schedule"), callback_data="worldcup:schedule:0")],
            [InlineKeyboardButton(text="🏆 " + t(lang, "winner_prediction"), callback_data="worldcup:futures:0")],
            [InlineKeyboardButton(text="🎲 " + t(lang, "worldcup_betting"), callback_data="worldcup:betting:0")],
            [InlineKeyboardButton(text=t(lang, "back_home"), callback_data="home")],
        ]
    )


def _format_worldcup_schedule_page(fixtures: list[dict[str, Any]], lang: str = "zh") -> tuple[str, int]:
    lines = [t(lang, "worldcup_schedule_title"), ""]
    weekdays_zh = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    for item in fixtures:
        dt = fixture_beijing_datetime(item)
        if dt:
            if lang == "en":
                date_line = f"{dt.strftime('%b')} {dt.day} {dt.strftime('%a')}"
            else:
                date_line = f"{dt.month}月{dt.day}日 {weekdays_zh[dt.weekday()]}"
            time_line = dt.strftime("%H:%M")
        else:
            date_line = "--"
            time_line = "--:--"
        lines.extend(
            [
                f"📅 {date_line}",
                "",
                f"【{worldcup_stage_label(item, lang)}】",
                worldcup_match_line(item, lang),
                f" {time_line}",
                f"🎲 {'Odds' if lang == 'en' else '预测赔率'}: {t(lang, 'odds_na')}" if lang == "en" else f"🎲 预测赔率：{t(lang, 'odds_na')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip(), 1


def _format_worldcup_futures(options: list[dict[str, Any]], page: int = 0, per_page: int = 8, lang: str = "zh") -> str:
    visible = options[page * per_page : (page + 1) * per_page]
    lines = [f"🏆 {t(lang, 'worldcup_futures_title')}", ""]
    for option in visible:
        lines.append(f"{_worldcup_option_label(option, lang)} @ {_money(option.get('odds'))}")
    total_pages = max((len(options) - 1) // per_page + 1, 1)
    if total_pages > 1:
        lines.append("")
        lines.append(t(lang, "page", page=page + 1, total=total_pages))
    return "\n".join(lines)


def _worldcup_option_label(option: dict[str, Any], lang: str = "zh") -> str:
    if lang != "en":
        return str(option.get("label") or "-")
    metadata = option.get("metadata_json") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    team = str((metadata or {}).get("team") or option.get("option_key") or option.get("label") or "-")
    team = team.replace("_", " ").title() if "_" in team else team
    flag = str((metadata or {}).get("flag") or "").strip()
    return f"{flag} {team}".strip()


def _fallback_worldcup_fixtures() -> list[dict[str, Any]]:
    matches = [
        (1, "2026-06-13T03:00:00+08:00", "Group B", "Canada", "Bosnia and Herzegovina"),
        (2, "2026-06-14T03:00:00+08:00", "Group C", "Spain", "Cape Verde Islands"),
        (3, "2026-06-14T10:00:00+08:00", "Group C", "Haiti", "Scotland"),
        (4, "2026-06-15T03:00:00+08:00", "Group D", "Switzerland", "Bosnia & Herzegovina"),
    ]
    fixtures = []
    for fixture_id, raw_time, group, home, away in matches:
        dt = datetime.fromisoformat(raw_time)
        fixtures.append(
            {
                "fixture": {"id": 20260000 + fixture_id, "date": raw_time, "timestamp": int(dt.timestamp())},
                "league": {"id": 1, "name": "World Cup", "season": 2026, "round": group},
                "teams": {"home": {"name": home}, "away": {"name": away}},
            }
        )
    return fixtures


def _role_label(role: str) -> str:
    return {
        "super_admin": "超级管理员",
        "admin": "管理员",
        "agent": "代理",
    }.get(role, "普通用户")


def _potential_payout_text(stake: str, odds: str) -> str:
    try:
        return _money(Decimal(str(stake)) * Decimal(str(odds)))
    except Exception:
        return "0.00"


def _bet_mode_notice(settings: Settings, lang: str = "zh") -> str:
    if lang == "en":
        if settings.real_betting_enabled:
            return "Real betting mode: stake is frozen and payouts are settled after result."
        if settings.bet_require_balance_for_simulation:
            return "Test betting mode: wallet balance must cover the stake, but no real debit is made."
        return "Simulation mode: no balance check and no real debit."
    if settings.real_betting_enabled:
        return "真实下注模式：下注将冻结余额，开奖后自动派彩。"
    if settings.bet_require_balance_for_simulation:
        return "当前为测试下注模式，需钱包余额覆盖下注金额，但不会真实扣款。"
    return "当前为模拟下注模式，不校验余额，不扣真实余额。"


def _admin_menu_text(role: str, lang: str = "zh") -> str:
    if lang == "en":
        if role == "super_admin":
            return "🛡 Super Admin Panel\n\nFull risk control, settlement, deposit/withdrawal, wallet and agent management."
        if role in {"admin", "agent"}:
            return (
                "Agent Panel\n\n"
                f"Current Role: {'Agent' if role == 'agent' else 'Admin'}\n"
                "Settled Valid Stake:\n"
                "Current Rebate Rate:\n"
                "Available Rebate:"
            )
        return "Admin Panel"
    if role == "super_admin":
        return (
            "超级管理员面板\n\n"
            "高风险功能仅超级管理员可用：注单开奖、提现审核、充值订单、用户钱包/调账、用户风控、冻结余额、退单审批。"
        )
    if role == "admin":
        return "管理员面板\n\n当前仅开放返水管理、佣金管理、下级/代理数据。"
    if role == "agent":
        return "代理面板\n\n只能查看自己的下级、佣金、推广和返水申请信息，不能进行资金操作。"
    if role == "super_admin":
        return (
            "🛡 超级管理员面板\n\n"
            "当前身份：超级管理员\n\n"
            "常用功能：\n"
            "/admin_stats 平台统计\n"
            "/admin_deposits 充值订单\n"
            "/admin_withdrawals 提现审核\n"
            "/admin_bets 注单开奖\n"
            "/admin_wallet <telegram_user_id> 用户钱包\n"
            "/admin_invite_agent <telegram_user_id> 授权代理\n"
            "/admin_invite_admin <telegram_user_id> 授权管理员\n"
            "/admin_adjust_balance <telegram_user_id> <amount> <reason> 手动调账"
        )
    return (
        "👥 代理/管理员面板\n\n"
        f"当前身份：{_role_label(role)}\n\n"
        "/admin_stats 平台统计\n"
        "/admin_deposits 充值订单\n"
        "/admin_withdrawals 提现审核\n"
        "/admin_bets 注单开奖\n"
        "/admin_commissions 佣金记录\n"
        "/admin_referrals <telegram_user_id> 下级统计"
    )


def _admin_panel_keyboard(role: str, lang: str = "zh") -> InlineKeyboardMarkup:
    if role == "super_admin":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=t(lang, "bet_settlement"), callback_data="admin:bets")],
                [InlineKeyboardButton(text=t(lang, "withdrawal_review"), callback_data="admin:withdrawals")],
                [InlineKeyboardButton(text=t(lang, "deposit_orders"), callback_data="admin:deposits")],
                [InlineKeyboardButton(text=t(lang, "user_wallet_adjust"), callback_data="admin:wallets")],
                [InlineKeyboardButton(text=t(lang, "user_risk"), callback_data="admin:users")],
                [InlineKeyboardButton(text=t(lang, "rebate_management"), callback_data="admin:rebates")],
                [InlineKeyboardButton(text=t(lang, "commission_management"), callback_data="admin:commissions")],
                [InlineKeyboardButton(text=t(lang, "back_home"), callback_data="home")],
            ]
        )
    if role == "admin":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎁 返水管理", callback_data="admin:rebates")],
                [InlineKeyboardButton(text="💸 佣金管理", callback_data="admin:commissions")],
                [InlineKeyboardButton(text="👥 下级/代理数据", callback_data="referrals:children")],
                [InlineKeyboardButton(text="返回首页", callback_data="home")],
            ]
        )
    if role == "super_admin":
        rows = [
            [InlineKeyboardButton(text="📊 平台统计", callback_data="admin:stats")],
            [InlineKeyboardButton(text="🎯 可投注赛事管理", callback_data="admin:markets")],
            [InlineKeyboardButton(text="🎫 注单开奖", callback_data="admin:bets")],
            [InlineKeyboardButton(text="💰 用户钱包", callback_data="admin:wallets")],
            [InlineKeyboardButton(text="🏧 提现审核", callback_data="admin:withdrawals")],
            [InlineKeyboardButton(text="💳 充值订单", callback_data="admin:deposits")],
            [InlineKeyboardButton(text="👥 用户/代理管理", callback_data="admin:users")],
            [InlineKeyboardButton(text="🎁 返水管理", callback_data="admin:rebates")],
            [InlineKeyboardButton(text="💸 佣金管理", callback_data="admin:commissions")],
            [InlineKeyboardButton(text="系统设置", callback_data="admin:settings")],
        ]
    else:
        rows = [
            [InlineKeyboardButton(text="我的下级", callback_data="referrals:children")],
            [InlineKeyboardButton(text="下级充值", callback_data="referrals:sub_deposits")],
            [InlineKeyboardButton(text="下级投注", callback_data="referrals:sub_bets")],
            [InlineKeyboardButton(text="返水申请", callback_data="admin:rebates")],
            [InlineKeyboardButton(text="佣金记录", callback_data="admin:commissions")],
            [InlineKeyboardButton(text="返回首页", callback_data="home")],
        ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _now_hhmm() -> str:
    return now_hhmm()


def _log_api_failure(key: str, message: str, *args: Any) -> None:
    now = datetime.now()
    last = _api_failure_log_times.get(key)
    if last and (now - last).total_seconds() < 300:
        return
    _api_failure_log_times[key] = now
    logger.warning(message, *args)


# M12 payment safety overrides: only expose the vetted public cashier URL.
def _deposit_order_keyboard(order: dict | None) -> InlineKeyboardMarkup:
    rows = []
    if order:
        payment_url = str(order.get("final_payment_url") or order.get("payment_url") or "")
        if payment_url and _safe_final_payment_url(payment_url):
            rows.append([InlineKeyboardButton(text="打开收银台", url=payment_url)])
        rows.append([InlineKeyboardButton(text="刷新充值状态", callback_data=f"deposit:refresh:{order['order_id']}")])
    rows.append([InlineKeyboardButton(text="返回钱包", callback_data="wallet")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_admin_deposit_order(order: dict | None) -> str:
    if not order:
        return "订单不存在。"
    return (
        "充值订单详情\n\n"
        f"order_id={order.get('order_id')}\n"
        f"user_id={order.get('user_id')}\n"
        f"amount_requested={_money(order.get('amount_requested'))}\n"
        f"actual_amount={_money(order.get('actual_amount'))}\n"
        f"status={order.get('status')}\n"
        f"manual_review_required={order.get('manual_review_required')}\n"
        f"manual_review_note={order.get('manual_review_note') or '-'}\n"
        f"error_message={order.get('error_message') or '-'}\n"
        f"trade_id={order.get('trade_id') or '-'}\n"
        f"chain_tx_id={order.get('chain_tx_id') or '-'}\n"
        f"network={order.get('network') or '-'}\n"
        f"payment_url={order.get('payment_url') or '-'}\n"
        f"original_payment_url={order.get('original_payment_url') or '-'}\n"
        f"final_payment_url={order.get('final_payment_url') or '-'}\n"
        f"payment_url_check_status={order.get('payment_url_check_status') or '-'}\n"
        f"raw_response_json={_short_json(order.get('raw_response_json'))}\n"
        f"raw_callback_json={_short_json(order.get('raw_callback_json'))}\n"
        f"created_at={order.get('created_at')}\n"
        f"paid_at={order.get('paid_at') or '-'}"
    )


def _format_bet_placeholder(fixture: dict[str, Any], selection: str, odds: str) -> str:
    teams = fixture.get("teams", {})
    home = teams.get("home", {}).get("name", "主队")
    away = teams.get("away", {}).get("name", "客队")
    return (
        "🎯 投注功能即将开放\n"
        f"比赛：{home} vs {away}\n"
        f"选择：{selection}\n"
        f"赔率：{odds}\n\n"
        "当前仅展示赔率，不扣余额，不生成真实注单。"
    )

# M11-Fix-3 final wording overrides.
def _format_bets_page(rows: list[dict], stats: dict, status_group: str, settings: Settings) -> str:
    pending_count = int(stats.get("pending_count") or 0)
    manual_required_count = int(stats.get("manual_required_count") or 0)
    settled_count = int(stats.get("settled_count") or 0)
    lines = [
        "📊 我的注单",
        "",
        f"待开奖：{pending_count + manual_required_count} 张",
        f"已开奖：{settled_count} 张",
        _bet_mode_notice(settings),
        "",
    ]
    if not rows:
        lines.append("暂无注单。")
        return "\n".join(lines)
    for index, bet in enumerate(rows, 1):
        tag = " ｜ 测试单" if bet.get("is_simulated") else ""
        lines.append(
            f"{index}. {bet.get('bet_no') or bet.get('id')} | {bet.get('fixture_label') or '-'} | "
            f"{_money(bet.get('stake'))} {settings.wallet_currency} | {_bet_status_label(str(bet.get('status')))}{tag}"
        )
    return "\n".join(lines)


def _format_bet_created(bet: dict, currency: str, lang: str = "zh") -> str:
    tag = "\n类型：测试单" if bet.get("is_simulated") else ""
    if lang == "en":
        tag = "\nType: Test Bet" if bet.get("is_simulated") else ""
        return (
            "🎫 Bet Created\n\n"
            f"Bet No: {bet.get('bet_no') or bet.get('id')}\n"
            f"Match: {bet.get('fixture_label') or '-'}\n"
            f"Market: {bet.get('market_title') or bet.get('market_key') or '-'}\n"
            f"Selection: {bet.get('selection') or '-'}\n"
            f"Amount: {_money(bet.get('stake'))} {currency}\n"
            f"Odds: {bet.get('odds') or '-'}\n"
            f"Estimated Payout: {_money(bet.get('potential_payout'))} {currency}\n"
            "Status: Pending"
            f"{tag}"
        )
    return (
        "🎫 注单已创建\n\n"
        f"注单号：{bet.get('bet_no') or bet.get('id')}\n"
        f"比赛：{bet.get('fixture_label') or '-'}\n"
        f"玩法：{bet.get('market_title') or bet.get('market_key') or '-'}\n"
        f"选择：{bet.get('selection') or '-'}\n"
        f"金额：{_money(bet.get('stake'))} {currency}\n"
        f"赔率：{bet.get('odds') or '-'}\n"
        f"预计派彩：{_money(bet.get('potential_payout'))} {currency}\n"
        "状态：待开奖"
        f"{tag}"
    )


def _format_insufficient_balance(stake: Decimal, balance: Decimal, currency: str, lang: str = "zh") -> str:
    if lang == "en":
        return (
            "💰 Insufficient balance\n\n"
            f"Amount: {_money(stake)} {currency}\n"
            f"Balance: {_money(balance)} {currency}\n\n"
            "Please deposit before betting."
        )
    return (
        "💰 钱包余额不足\n\n"
        f"本次下注：{_money(stake)} {currency}\n"
        f"当前余额：{_money(balance)} {currency}\n\n"
        "请先充值后再下注。"
    )


def _insufficient_balance_keyboard(fixture_id: int | None = None, lang: str = "zh") -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=t(lang, "deposit_usdt"), callback_data="wallet:recharge")]]
    if fixture_id is not None:
        rows.append([InlineKeyboardButton(text=t(lang, "back_to_match"), callback_data=f"fixture:{fixture_id}")])
    rows.append([InlineKeyboardButton(text=t(lang, "back_home"), callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_bet_detail(bet: dict, currency: str) -> str:
    status = str(bet.get("status") or "")
    opened = status in {"won", "lost", "void", "cancelled"}
    title = "🎫 已开奖注单" if opened else "🎫 注单详情"
    lines = [
        title,
        "",
        f"注单号：{bet.get('bet_no') or bet.get('id')}",
        f"比赛：{bet.get('fixture_label') or '-'}",
        f"玩法：{bet.get('market_title') or bet.get('market_key') or '-'}",
        f"选择：{bet.get('selection') or '-'}",
        f"金额：{_money(bet.get('stake'))} {currency}",
        f"赔率：{bet.get('odds') or '-'}",
        f"预计派彩：{_money(bet.get('potential_payout'))} {currency}",
        f"状态：{_bet_status_label(status)}",
    ]
    if bet.get("is_simulated"):
        lines.append("类型：测试单")
    if opened:
        lines.append(f"派彩：{_money(bet.get('payout'))} {currency}")
        if bet.get("result_score"):
            lines.append(f"赛果：{bet.get('result_score')}")
    if bet.get("settled_at"):
        lines.append(f"开奖时间：{bet.get('settled_at')}")
    if bet.get("settlement_note"):
        lines.append(f"备注：{bet.get('settlement_note')}")
    return "\n".join(lines)


def _bet_status_label(status: str) -> str:
    return {
        "pending": "待开奖",
        "manual_required": "待人工开奖",
        "won": "已中奖",
        "lost": "未中奖",
        "void": "已作废",
        "cancelled": "已取消",
    }.get(status, status or "-")


async def _start_text(
    cache: RedisCache,
    api_client: ApiFootballClient,
    database: Database,
    settings: Settings,
    telegram_user_id: int | None,
    lang: str = "zh",
) -> str:
    today_matches, _ = await get_bettable_matches_range(cache, api_client, database, settings)
    tomorrow = date.today() + timedelta(days=1)
    tomorrow_matches, _ = await get_bettable_matches_for_date(cache, api_client, database, settings, tomorrow)
    live = await _get_live(cache, api_client)
    stats = await database.get_user_bet_stats(telegram_user_id) if telegram_user_id else {}
    pending = int(stats.get("pending_count") or 0) + int(stats.get("manual_required_count") or 0)
    simulated_pending = int(stats.get("simulated_pending_count") or 0)
    if lang == "en":
        return (
            "WorldCupTop Bot\n\n"
            f"Featured Matches: {_count_by_date(today_matches, date.today())}\n"
            f"Tomorrow Fixtures: {len(tomorrow_matches)}\n"
            f"Live Matches: {len(live)}\n"
            f"My Pending Bets: {pending}\n"
            f"Test Bets: {simulated_pending}\n"
            f"{_bet_mode_notice(settings, lang)}"
        )
    return (
        "WorldCupTop Bot\n\n"
        f"今日可投注：{_count_by_date(today_matches, date.today())} 场\n"
        f"明日可投注：{len(tomorrow_matches)} 场\n"
        f"实时比赛：{len(live)} 场\n"
        f"我的待开奖注单：{pending} 张\n"
        f"其中测试单：{simulated_pending} 张\n"
        f"{_bet_mode_notice(settings)}"
    )
def _localized_bet_value(value: Any, lang: str, kind: str = "generic") -> str:
    text = str(value or "-")
    if lang != "en":
        return text
    market_map = {
        "胜平负": "1X2",
        "冠军": "Champion",
        "match_winner": "1X2",
        "world_cup_winner": "Champion",
    }
    selection_map = {
        "主胜": "Home Win",
        "平局": "Draw",
        "客胜": "Away Win",
        "冠军": "Champion",
        "Home": "Home Win",
        "Draw": "Draw",
        "Away": "Away Win",
    }
    mapping = market_map if kind == "market" else selection_map if kind == "selection" else {}
    return mapping.get(text, text)


def _bet_status_label(status: str, lang: str = "zh") -> str:
    if lang == "en":
        return {
            "pending": "Pending",
            "manual_required": "Pending",
            "won": "Won",
            "lost": "Lost",
            "void": "Void",
            "cancelled": "Void",
            "approved": "Approved",
            "rejected": "Rejected",
        }.get(status, status or "-")
    return {
        "pending": "待开奖",
        "manual_required": "待开奖",
        "won": "中奖",
        "lost": "未中奖",
        "void": "作废",
        "cancelled": "作废",
        "approved": "已通过",
        "rejected": "已拒绝",
    }.get(status, status or "-")


def _format_bets_page(rows: list[dict], stats: dict, status_group: str, settings: Settings, lang: str = "zh") -> str:
    pending_count = int(stats.get("pending_count") or 0)
    manual_required_count = int(stats.get("manual_required_count") or 0)
    settled_count = int(stats.get("settled_count") or 0)
    if lang == "en":
        lines = [
            "📊 My Bets",
            "",
            f"Pending: {pending_count + manual_required_count}",
            f"Settled: {settled_count}",
            _bet_mode_notice(settings, lang),
            "",
        ]
        if not rows:
            lines.append("No bets yet.")
            return "\n".join(lines)
        for index, bet in enumerate(rows, 1):
            lines.append(
                f"{index}. {bet.get('bet_no') or bet.get('id')} | {bet.get('fixture_label') or '-'} | "
                f"{_money(bet.get('stake'))} {settings.wallet_currency} | {_bet_status_label(str(bet.get('status')), lang)}"
            )
        return "\n".join(lines)
    lines = [
        "📊 我的注单",
        "",
        f"待开奖：{pending_count + manual_required_count} 张",
        f"已开奖：{settled_count} 张",
        _bet_mode_notice(settings, lang),
        "",
    ]
    if not rows:
        lines.append("暂无注单。")
        return "\n".join(lines)
    for index, bet in enumerate(rows, 1):
        lines.append(
            f"{index}. {bet.get('bet_no') or bet.get('id')} | {bet.get('fixture_label') or '-'} | "
            f"{_money(bet.get('stake'))} {settings.wallet_currency} | {_bet_status_label(str(bet.get('status')), lang)}"
        )
    return "\n".join(lines)


def _bet_action_keyboard(
    bet_id_or_no: str,
    status: str,
    status_group: str = "pending",
    page: int = 0,
    *,
    fixture_id: int | None = None,
    lang: str = "zh",
) -> InlineKeyboardMarkup:
    rows = []
    if status in {"pending", "manual_required"}:
        rows.append([InlineKeyboardButton(text=t(lang, "check_result"), callback_data=f"bet_settle:{bet_id_or_no}")])
    if fixture_id is not None:
        rows.append([InlineKeyboardButton(text=t(lang, "back_to_match"), callback_data=f"fixture:{fixture_id}")])
    else:
        rows.append([InlineKeyboardButton(text="Back to My Bets" if lang == "en" else "返回我的注单", callback_data=f"bets:{status_group}:{page}")])
    rows.append([InlineKeyboardButton(text=t(lang, "back_home"), callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_bet_detail(bet: dict, currency: str, lang: str = "zh") -> str:
    status = str(bet.get("status") or "")
    opened = status in {"won", "lost", "void", "cancelled"}
    if lang == "en":
        lines = [
            "🧾 Bet Detail",
            "",
            f"Bet No: {bet.get('bet_no') or bet.get('id')}",
            f"Match: {bet.get('fixture_label') or '-'}",
            f"Market: {_localized_bet_value(bet.get('market_title') or bet.get('market_key') or '-', lang, 'market')}",
            f"Selection: {_localized_bet_value(bet.get('selection') or '-', lang, 'selection')}",
        ]
        if opened and bet.get("result_score"):
            lines.append(f"Result: {bet.get('result_score')}")
        lines.extend(
            [
                f"Amount: {_money(bet.get('stake'))} {currency}",
                f"Odds: {bet.get('odds') or '-'}",
                f"Estimated Payout: {_money(bet.get('potential_payout'))} {currency}",
            ]
        )
        if opened:
            lines.append(f"Payout: {_money(bet.get('payout'))} {currency}")
        lines.append(f"Status: {_bet_status_label(status, lang)}")
        if bet.get("settled_at"):
            lines.append(f"Settlement Time: {bet.get('settled_at')}")
        if bet.get("settlement_note"):
            lines.append(f"Note: {bet.get('settlement_note')}")
        return "\n".join(lines)
    lines = [
        "🧾 注单详情",
        "",
        f"注单号：{bet.get('bet_no') or bet.get('id')}",
        f"比赛：{bet.get('fixture_label') or '-'}",
        f"玩法：{bet.get('market_title') or bet.get('market_key') or '-'}",
        f"选择：{bet.get('selection') or '-'}",
    ]
    if opened and bet.get("result_score"):
        lines.append(f"赛果：{bet.get('result_score')}")
    lines.extend(
        [
            f"金额：{_money(bet.get('stake'))} {currency}",
            f"赔率：{bet.get('odds') or '-'}",
            f"预计派彩：{_money(bet.get('potential_payout'))} {currency}",
        ]
    )
    if opened:
        lines.append(f"派彩：{_money(bet.get('payout'))} {currency}")
    lines.append(f"状态：{_bet_status_label(status, lang)}")
    return "\n".join(lines)


def _referral_keyboard(role: str = "user", application: dict | None = None, lang: str = "zh") -> InlineKeyboardMarkup:
    if lang == "en":
        rows = [
            [
                InlineKeyboardButton(text="Subordinates", callback_data="referrals:children"),
                InlineKeyboardButton(text="Reward Records", callback_data="referrals:commissions"),
            ]
        ]
        if role in {"agent", "admin", "super_admin"}:
            rows.append([InlineKeyboardButton(text="My Consumption", callback_data="referrals:sub_bets")])
            rows.append([InlineKeyboardButton(text="Apply Rebate", callback_data="referrals:rebate_apply")])
        rows.extend(
            [
                [InlineKeyboardButton(text="Copy Referral Link", callback_data="referrals:copy")],
                [InlineKeyboardButton(text=t(lang, "back_home"), callback_data="home")],
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=rows)
    rows = [
        [
            InlineKeyboardButton(text="下级管理", callback_data="referrals:children"),
            InlineKeyboardButton(text="返佣记录", callback_data="referrals:commissions"),
        ],
        [InlineKeyboardButton(text="返水管理", callback_data="referrals:rebate_apply")],
    ]
    if role in {"agent", "admin", "super_admin"}:
        rows.append([InlineKeyboardButton(text="下级投注", callback_data="referrals:sub_bets")])
    else:
        status = str((application or {}).get("status") or "")
        if status == "pending":
            rows.append([InlineKeyboardButton(text="代理申请审核中", callback_data="referrals:agent_pending")])
        else:
            rows.append([InlineKeyboardButton(text="申请成为代理", callback_data="referrals:agent_apply")])
    rows.extend(
        [
            [InlineKeyboardButton(text="复制邀请链接", callback_data="referrals:copy")],
            [InlineKeyboardButton(text=t(lang, "back_home"), callback_data="home")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_referrals(
    link: str,
    summary: dict,
    currency: str,
    role: str = "user",
    application: dict | None = None,
    lang: str = "zh",
) -> str:
    if lang == "en":
        return "\n".join(
            [
                "👥 Referral",
                f"Current Role: {_role_label_en(role)}",
                "My referral link:",
                link,
                "",
                f"Direct referrals: {summary.get('direct_count') or 0}",
                f"Qualified referrals: {summary.get('active_count') or 0}",
                f"Total rewards: {_money(summary.get('settled_commission'))} {currency}",
                f"Pending rewards: {_money(summary.get('pending_commission'))} {currency}",
            ]
        )
    return "\n".join(
        [
            "👥 推广邀请",
            f"当前身份：{_role_label(role)}",
            "我的邀请链接：",
            link,
            "",
            f"直属下级：{summary.get('direct_count') or 0}",
            f"有效下级：{summary.get('active_count') or 0}",
            f"累计返佣：{_money(summary.get('settled_commission'))} {currency}",
            f"待结算返佣：{_money(summary.get('pending_commission'))} {currency}",
        ]
    )


def _role_label_en(role: str) -> str:
    return {
        "super_admin": "Super Admin",
        "admin": "Admin",
        "agent": "Agent",
    }.get(role, "User")


async def _send_bets_page(
    message: Message,
    user_id: int,
    status_group: str,
    page: int,
    database: Database,
    settings: Settings,
) -> None:
    page = max(page, 0)
    per_page = 5
    lang = normalize_language(await database.get_user_language(user_id, settings.default_language), settings.default_language)
    stats = await database.get_user_bet_stats(user_id)
    rows = await database.list_user_bets(user_id, status_group=status_group, limit=per_page, offset=page * per_page)
    total = int(stats.get("settled_count") or 0) if status_group == "settled" else (
        int(stats.get("pending_count") or 0) + int(stats.get("manual_required_count") or 0)
    )
    await message.answer(
        _format_bets_page(rows, stats, status_group, settings, lang),
        reply_markup=my_bets_keyboard(
            rows,
            status_group,
            page,
            has_prev=page > 0,
            has_next=(page + 1) * per_page < total,
            lang=lang,
        ),
    )


def _bet_mode_notice(settings: Settings, lang: str = "zh") -> str:
    if lang == "en":
        if settings.real_betting_enabled:
            return "Real betting mode: your stake is frozen after placing a bet, and payouts are released after settlement."
        if settings.bet_require_balance_for_simulation:
            return "Test betting mode: wallet balance must cover the stake, but no real debit is made."
        return "Simulation mode: no balance check and no real debit."
    if settings.real_betting_enabled:
        return "真实下注模式：下注将冻结余额，开奖后自动派奖。"
    if settings.bet_require_balance_for_simulation:
        return "测试下注模式：钱包余额需覆盖下注金额，但不会真实扣款。"
    return "模拟下注模式：不校验余额，不扣真实余额。"


def _network_keyboard(prefix: str, lang: str = "zh") -> InlineKeyboardMarkup:
    networks = [
        ("TRON / TRC20", "tron"),
        ("Polygon", "polygon"),
        ("BSC", "bsc"),
        ("Arbitrum", "arbitrum"),
        ("Ethereum", "ethereum"),
    ]
    rows = [[InlineKeyboardButton(text=label, callback_data=f"{prefix}:{value}")] for label, value in networks]
    rows.append([InlineKeyboardButton(text=t(lang, "cancel"), callback_data=f"{prefix}:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _cancel_keyboard(target: str, lang: str = "zh") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t(lang, "cancel"), callback_data=f"fsm_cancel:{target}")]])


def _recharge_confirm_keyboard(lang: str = "zh") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Create Deposit Order" if lang == "en" else "确认创建订单", callback_data="recharge:confirm")],
            [InlineKeyboardButton(text="Change Amount" if lang == "en" else "重新选择金额", callback_data="recharge:amounts")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="fsm_cancel:wallet")],
        ]
    )


def _withdraw_confirm_keyboard(lang: str = "zh") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Submit Request" if lang == "en" else "提交申请", callback_data="withdraw:confirm")],
            [InlineKeyboardButton(text=t(lang, "cancel"), callback_data="fsm_cancel:wallet")],
        ]
    )


def _recharge_amount_keyboard(lang: str = "zh") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="2 USDT", callback_data="wallet:amount:2"),
                InlineKeyboardButton(text="5 USDT", callback_data="wallet:amount:5"),
            ],
            [
                InlineKeyboardButton(text="10 USDT", callback_data="wallet:amount:10"),
                InlineKeyboardButton(text="20 USDT", callback_data="wallet:amount:20"),
            ],
            [
                InlineKeyboardButton(text="50 USDT", callback_data="wallet:amount:50"),
                InlineKeyboardButton(text="100 USDT", callback_data="wallet:amount:100"),
            ],
            [InlineKeyboardButton(text="Custom Amount" if lang == "en" else "自定义金额", callback_data="wallet:amount:custom")],
            [InlineKeyboardButton(text="Back to Wallet" if lang == "en" else "返回钱包", callback_data="wallet")],
        ]
    )


def _format_bet_created(bet: dict, currency: str, lang: str = "zh") -> str:
    if lang == "en":
        return (
            "🧾 Bet Created\n\n"
            f"Bet No: {bet.get('bet_no') or bet.get('id')}\n"
            f"Match: {bet.get('fixture_label') or '-'}\n"
            f"Market: {_localized_bet_value(bet.get('market_title') or bet.get('market_key') or '-', lang, 'market')}\n"
            f"Selection: {_localized_bet_value(bet.get('selection') or '-', lang, 'selection')}\n"
            f"Amount: {_money(bet.get('stake'))} {currency}\n"
            f"Odds: {bet.get('odds') or '-'}\n"
            f"Estimated Payout: {_money(bet.get('potential_payout'))} {currency}\n"
            "Status: Pending"
        )
    return (
        "🧾 注单已创建\n\n"
        f"注单号：{bet.get('bet_no') or bet.get('id')}\n"
        f"比赛：{bet.get('fixture_label') or '-'}\n"
        f"玩法：{bet.get('market_title') or bet.get('market_key') or '-'}\n"
        f"选择：{bet.get('selection') or '-'}\n"
        f"金额：{_money(bet.get('stake'))} {currency}\n"
        f"赔率：{bet.get('odds') or '-'}\n"
        f"预计派彩：{_money(bet.get('potential_payout'))} {currency}\n"
        "状态：待开奖"
    )


def _format_worldcup_futures(options: list[dict[str, Any]], page: int = 0, per_page: int = 8, lang: str = "zh") -> str:
    visible = options[page * per_page : (page + 1) * per_page]
    lines = ["🏆 2026 World Cup Champion Futures" if lang == "en" else "🏆 2026 世界杯冠军预测", ""]
    for option in visible:
        lines.append(f"{_worldcup_option_label(option, lang)} @ {_money(option.get('odds'))}")
    total_pages = max((len(options) - 1) // per_page + 1, 1)
    if total_pages > 1:
        lines.append("")
        lines.append(t(lang, "page", page=page + 1, total=total_pages))
    return "\n".join(lines)
