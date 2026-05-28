from __future__ import annotations

import logging
import json
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from datetime import date, datetime, timedelta
from typing import Any

import asyncpg
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from football_score_bot.api_football import ApiFootballClient
from football_score_bot.betting import BettableStatus, is_bettable_fixture, reason_label
from football_score_bot.cache import RedisCache
from football_score_bot.config import Settings
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
    worldcup_zone_keyboard,
)
from football_score_bot.odds import build_odds_first_matches
from football_score_bot.odds_normalizer import normalized_from_dict, normalize_fixture_odds as normalize_fixture_odds_full
from football_score_bot.time_utils import now_hhmm


logger = logging.getLogger(__name__)
_api_failure_log_times: dict[str, datetime] = {}


def build_router(
    api_client: ApiFootballClient,
    cache: RedisCache,
    database: Database,
    settings: Settings,
) -> Router:
    router = Router()
    wallet_service = WalletService(
        database,
        currency=settings.wallet_currency,
        referral_deposit_commission_rate=settings.referral_deposit_commission_rate,
        referral_agent_enabled=settings.referral_agent_enabled,
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

    @router.message(Command("start"))
    async def start(message: Message, command: CommandObject) -> None:
        lang = await _remember_user_and_lang(message, database, settings)
        await _maybe_bind_referral(message, command, database)
        await message.answer(
            await _start_text(cache, api_client, database, settings, message.from_user.id if message.from_user else None),
            reply_markup=main_menu_keyboard(lang),
        )

    @router.callback_query(F.data == "home")
    async def home_callback(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        lang = await _callback_lang(callback, database, settings)
        await callback.message.answer(
            await _start_text(cache, api_client, database, settings, callback.from_user.id if callback.from_user else None),
            reply_markup=main_menu_keyboard(lang),
        )

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        lang = await _remember_user_and_lang(message, database, settings)
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
    @router.message(F.text == "🎯 可投注赛事")
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
    @router.message(F.text.in_(_translated_texts("worldcup")))
    @router.callback_query(F.data == "worldcup")
    async def worldcup(event: Message | CallbackQuery) -> None:
        await _answer_callback(event, "加载中...")
        message = _message(event)
        lang = await _event_lang(event, database, settings)
        await _remember_chat(message, database)
        await message.answer(format_worldcup_zone(), reply_markup=worldcup_zone_keyboard(lang))

    @router.callback_query(F.data == "worldcup_schedule")
    async def worldcup_schedule(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        lang = await _callback_lang(callback, database, settings)
        await callback.message.answer("📅 世界杯赛程即将开放\n后续将接入 API-Football 世界杯赛程。", reply_markup=futures_back_keyboard(lang))

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
            reply_markup=futures_market_keyboard(market_key, page_options, page, total_pages)
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
        await callback.message.answer(
            format_bet_confirm(
                fixture,
                getattr(market, "title", market_key),
                _outcome_button_label(outcome),
                outcome.odds,
                stake=str(settings.default_bet_amount),
            ),
            reply_markup=bet_confirm_keyboard(fixture_id, market_key, page, outcome_index),
        )

    @router.callback_query(F.data.startswith("bet_confirm:"))
    async def bet_confirm(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        if not callback.from_user:
            await callback.message.answer("请先打开机器人后再提交投注。")
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
            await callback.message.answer(f"当前不可投注：{reason_label(bet_status.reason)}")
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
            await callback.message.answer("余额不足，无法提交真实下注。")
            return
        bet = await database.get_bet(bet_id)
        await callback.message.answer(
            _format_bet_created(bet or {"id": bet_id}, settings.wallet_currency),
            reply_markup=bet_created_keyboard(str((bet or {}).get("bet_no") or bet_id), fixture_id),
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
    async def bet_amount_set(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        parts = callback.data.split(":")
        fixture_id = int(parts[1])
        market_key = parts[2]
        page = int(parts[3])
        outcome_index = int(parts[4])
        amount = parts[5]
        if amount == "custom":
            await callback.message.answer("自定义金额暂未开放，请先选择固定金额。")
            return
        await callback.message.answer(
            f"金额已改为 {amount} USDT，请确认下注。",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="确认下注", callback_data=f"bet_confirm:{fixture_id}:{market_key}:{page}:{outcome_index}:{amount}")],
                    [InlineKeyboardButton(text="返回赔率", callback_data=f"odds:fixture:{fixture_id}:market:{market_key}:page:{page}")],
                ]
            ),
        )

    @router.callback_query(F.data == "bet_placeholder")
    async def bet_placeholder(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        await callback.message.answer("🎯 投注功能即将开放\n当前仅展示赔率，不扣余额，不生成真实注单。")

    @router.message(Command("language"))
    @router.message(F.text.in_({"🌐 " + text for text in _translated_texts("language_settings")}))
    async def language_settings(message: Message) -> None:
        await _remember_chat(message, database)
        await message.answer("请选择语言 / Choose language:", reply_markup=language_keyboard())

    @router.callback_query(F.data.startswith("lang:"))
    async def set_language(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        lang = callback.data.split(":", 1)[1]
        if lang not in SUPPORTED_LANGUAGES or not callback.from_user:
            return
        await database.set_user_language(callback.from_user.id, lang)
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

    @router.message(F.text.in_(_translated_texts("wallet")))
    @router.message(Command("wallet"))
    async def wallet(message: Message) -> None:
        await _remember_user_and_lang(message, database, settings)
        if not message.from_user:
            return
        wallet_row = await wallet_service.get_balance(message.from_user.id)
        await message.answer(_format_wallet(wallet_row, settings.wallet_currency), reply_markup=_wallet_keyboard())

    @router.callback_query(F.data == "wallet")
    async def wallet_callback(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        if not callback.from_user:
            return
        wallet_row = await wallet_service.get_balance(callback.from_user.id)
        await callback.message.answer(_format_wallet(wallet_row, settings.wallet_currency), reply_markup=_wallet_keyboard())

    @router.callback_query(F.data == "wallet:recharge")
    async def wallet_recharge(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        await callback.message.answer("选择充值金额：", reply_markup=_recharge_amount_keyboard())

    @router.callback_query(F.data.startswith("wallet:amount:"))
    async def wallet_recharge_amount(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        if not callback.from_user:
            return
        raw_amount = callback.data.rsplit(":", 1)[1]
        if raw_amount == "custom":
            await callback.message.answer("请发送 /recharge <金额> 创建自定义充值订单，例如：/recharge 25")
            return
        await _create_recharge_order(callback.message, callback.from_user.id, Decimal(raw_amount), database, settings, gmpay_client)

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
        await _create_recharge_order(message, message.from_user.id, amount, database, settings, gmpay_client)

    @router.callback_query(F.data == "wallet:records")
    async def wallet_records(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        rows = await database.list_user_deposit_orders(callback.from_user.id, 10)
        await callback.message.answer(_format_deposit_records(rows), reply_markup=_wallet_keyboard())

    @router.callback_query(F.data == "wallet:ledger")
    async def wallet_ledger(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        rows = await database.list_user_ledger(callback.from_user.id, 10)
        await callback.message.answer(_format_ledger(rows), reply_markup=_wallet_keyboard())

    @router.callback_query(F.data == "wallet:withdraw_prompt")
    async def wallet_withdraw_prompt(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        if not settings.withdraw_enabled:
            await callback.message.answer("提现申请功能暂未开放。")
            return
        await callback.message.answer("请发送：/withdraw <金额> <USDT-TRC20地址>\n第一版仅支持 TRC20，提交后等待管理员人工审核。")

    @router.callback_query(F.data == "wallet:withdraw")
    async def wallet_withdraw(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        await callback.message.answer("提现功能暂未自动开放。\n如需提现，请联系客服或等待管理员审核系统上线。")

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
        await callback.message.answer(_format_deposit_order(order, settings.wallet_currency), reply_markup=_deposit_order_keyboard(order))

    @router.callback_query(F.data.startswith("bets:"))
    async def bets_callback(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback, "加载中...")
        if not callback.from_user:
            await callback.message.answer("请先打开机器人后再查看注单。", reply_markup=my_bets_keyboard())
            return
        parts = callback.data.split(":")
        status_group = parts[1] if len(parts) > 1 else "pending"
        page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        await _send_bets_page(callback.message, callback.from_user.id, status_group, page, database)

    @router.message(F.text.in_(_translated_texts("betting_center") | _translated_texts("my_bets") | {"📊 我的注单"}))
    @router.message(Command("bets"))
    async def bets(message: Message) -> None:
        await _remember_user_and_lang(message, database, settings)
        if not message.from_user:
            await message.answer("请先打开机器人后再查看注单。", reply_markup=my_bets_keyboard())
            return
        await _send_bets_page(message, message.from_user.id, "pending", 0, database)

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
        await callback.message.answer(
            _format_bet_detail(bet, settings.wallet_currency),
            reply_markup=bet_detail_keyboard(str(bet.get("bet_no") or bet.get("id")), str(bet.get("status")), status_group, page),
        )

    @router.callback_query(F.data.startswith("bet_cancel:"))
    async def bet_cancel(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        if not callback.from_user:
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
            await callback.message.answer(_format_bet_detail(fresh or bet, settings.wallet_currency))
        elif result.get("reason") == "not_final":
            await callback.message.answer("比赛尚未结束，系统将在赛果确认后自动结算。")
        elif result.get("reason") == "unsupported_market":
            await callback.message.answer("该玩法需要人工结算，系统会尽快处理。")
        else:
            await callback.message.answer("赛果暂未确认，请稍后再试。")

    @router.message(F.text.in_(_translated_texts("referrals")))
    @router.message(Command("referrals"))
    async def referrals(message: Message) -> None:
        await _remember_user_and_lang(message, database, settings)
        if not message.from_user:
            return
        code = await database.get_referral_code(message.from_user.id)
        bot_info = await message.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start=ref_{code}"
        summary = await database.get_referral_summary(message.from_user.id)
        await message.answer(_format_referrals(link, summary, settings.wallet_currency), reply_markup=_referral_keyboard())

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

    @router.callback_query(F.data == "referrals:copy")
    async def referral_copy(callback: CallbackQuery) -> None:
        await _safe_callback_answer(callback)
        code = await database.get_referral_code(callback.from_user.id)
        bot_info = await callback.bot.get_me()
        await callback.message.answer(f"https://t.me/{bot_info.username}?start=ref_{code}")

    @router.message(F.text.in_(_translated_texts("settings")))
    @router.message(Command("settings"))
    async def settings_command(message: Message) -> None:
        await language_settings(message)

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
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        await message.answer(_format_deposit_records(await database.list_deposit_orders(20)))

    @router.message(Command("admin_deposit"))
    async def admin_deposit(message: Message, command: CommandObject) -> None:
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        order_id = (command.args or "").strip()
        if not order_id:
            await message.answer("用法：/admin_deposit <order_id>")
            return
        order = await database.get_deposit_order(order_id)
        await message.answer(_format_deposit_order(order, settings.wallet_currency) if order else "订单不存在。")

    @router.message(Command("admin_adjust_balance"))
    async def admin_adjust_balance(message: Message, command: CommandObject) -> None:
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        parts = (command.args or "").strip().split(maxsplit=2)
        if len(parts) < 3:
            await message.answer("用法：/admin_adjust_balance <telegram_user_id> <amount> <reason>")
            return
        try:
            target_user_id = int(parts[0])
            amount = Decimal(parts[1])
        except Exception:
            await message.answer("用法：/admin_adjust_balance <telegram_user_id> <amount> <reason>")
            return
        ledger = await wallet_service.manual_adjust(target_user_id, amount, parts[2], message.from_user.id)
        await database.add_admin_audit_log(
            message.from_user.id,
            "admin_adjust_balance",
            "wallet",
            str(target_user_id),
            {"amount": str(amount), "reason": parts[2], "ledger_id": ledger["id"]},
        )
        await message.answer(f"调整完成，ledger_id={ledger['id']}")

    @router.message(Command("admin_commissions"))
    async def admin_commissions(message: Message) -> None:
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
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        await message.answer(_format_admin_bets(await database.list_admin_bets("pending", 20)))

    @router.message(Command("admin_bet"))
    async def admin_bet(message: Message, command: CommandObject) -> None:
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        bet_id = _first_int_arg(command)
        if bet_id is None:
            await message.answer("用法：/admin_bet <bet_id>")
            return
        await message.answer(_format_admin_bet(await database.get_bet(bet_id)))

    async def _admin_settle_bet(message: Message, command: CommandObject, status: str, action: str) -> None:
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
        if not _admin_private_allowed(message, settings):
            await message.answer("无管理员权限，或请在私聊中使用。")
            return
        await message.answer(_format_withdrawals(await database.list_withdraw_requests("pending", 20)))

    @router.message(Command("admin_withdraw"))
    async def admin_withdraw(message: Message, command: CommandObject) -> None:
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

    return router


async def _start_text(
    cache: RedisCache,
    api_client: ApiFootballClient,
    database: Database,
    settings: Settings,
    telegram_user_id: int | None,
) -> str:
    today_matches, _ = await get_bettable_matches_range(cache, api_client, database, settings)
    tomorrow = date.today() + timedelta(days=1)
    tomorrow_matches, _ = await get_bettable_matches_for_date(cache, api_client, database, settings, tomorrow)
    live = await _get_live(cache, api_client)
    pending = await database.count_user_pending_bets(telegram_user_id) if telegram_user_id else 0
    return (
        "WorldCupTop Bot\n\n"
        f"今日可投注：{_count_by_date(today_matches, date.today())} 场\n"
        f"明日可投注：{len(tomorrow_matches)} 场\n"
        f"实时比赛：{len(live)} 场\n"
        f"我的待结算注单：{pending} 张"
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
        return int((command.args or "").strip().split()[0])
    except (IndexError, TypeError, ValueError):
        return None


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
) -> None:
    if amount < settings.gmpay_min_recharge_usdt:
        await message.answer(f"最低充值金额：{_money(settings.gmpay_min_recharge_usdt)} {settings.wallet_currency}")
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
                settings.gmpay_default_network,
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
        settings.gmpay_default_network,
    )
    try:
        transaction = await gmpay_client.create_transaction(
            order_id=order_id,
            amount=amount,
            user_id=user_id,
            notify_url=settings.gmpay_notify_url,
            redirect_url=settings.gmpay_redirect_url,
        )
    except Exception as exc:
        raw_response = _gmpay_create_failure_response(exc)
        await database.fail_deposit_order(order_id, raw_response)
        logger.warning("gmpay create transaction failed order_id=%s", order_id, exc_info=True)
        await message.answer("充值订单创建失败，请稍后再试。")
        return
    order = await database.update_deposit_order_transaction(
        order_id,
        trade_id=transaction.trade_id,
        actual_amount=transaction.actual_amount,
        token=transaction.token,
        network=transaction.network,
        payment_url=transaction.payment_url,
        expires_at=transaction.expires_at,
        raw_response=transaction.raw_json,
    ) or order
    await message.answer(_format_deposit_order(order, settings.wallet_currency), reply_markup=_deposit_order_keyboard(order))


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


def _wallet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="充值 USDT", callback_data="wallet:recharge")],
            [
                InlineKeyboardButton(text="充值记录", callback_data="wallet:records"),
                InlineKeyboardButton(text="账变记录", callback_data="wallet:ledger"),
            ],
            [InlineKeyboardButton(text="提现申请", callback_data="wallet:withdraw_prompt")],
            [InlineKeyboardButton(text="返回首页", callback_data="home")],
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
            [InlineKeyboardButton(text="复制邀请链接", callback_data="referrals:copy")],
            [InlineKeyboardButton(text="返回首页", callback_data="home")],
        ]
    )


def _format_wallet(wallet: dict, currency: str) -> str:
    return (
        "💰 钱包\n"
        f"余额：{_money(wallet.get('balance'))} {currency}\n"
        f"冻结：{_money(wallet.get('frozen_balance'))} {currency}\n"
        f"累计充值：{_money(wallet.get('total_deposit'))} {currency}"
    )


def _format_deposit_order(order: dict, currency: str) -> str:
    return (
        "充值订单已创建\n\n"
        f"订单号：{order.get('order_id')}\n"
        f"状态：{order.get('status')}\n"
        f"金额：{_money(order.get('amount_requested'))} {currency}\n"
        f"实际需支付：{_money(order.get('actual_amount') or order.get('amount_requested'))} {currency}\n"
        f"网络：{order.get('network') or '-'}\n"
        "有效期：30 分钟\n\n"
        "请点击下方按钮打开收银台完成支付。\n"
        "到账后系统会自动入账。"
    )


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


async def _send_bets_page(message: Message, user_id: int, status_group: str, page: int, database: Database) -> None:
    page = max(page, 0)
    per_page = 5
    pending_count = await database.count_user_bets_by_group(user_id, "pending")
    settled_count = await database.count_user_bets_by_group(user_id, "settled")
    rows = await database.list_user_bets(user_id, status_group=status_group, limit=per_page, offset=page * per_page)
    total = settled_count if status_group == "settled" else pending_count
    await message.answer(
        _format_bets_page(rows, pending_count, settled_count, status_group),
        reply_markup=my_bets_keyboard(
            rows,
            status_group,
            page,
            has_prev=page > 0,
            has_next=(page + 1) * per_page < total,
        ),
    )


def _format_bets_page(rows: list[dict], pending_count: int, settled_count: int, status_group: str) -> str:
    title = "📊 我的注单"
    lines = [title, "", f"待结算：{pending_count} 张", f"已结算：{settled_count} 张", ""]
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


def _localized_fixtures(fixtures: list[dict[str, Any]], lang: str) -> list[dict[str, Any]]:
    return [_localized_fixture(item, lang) for item in fixtures]


def _localized_fixture(item: dict[str, Any], lang: str) -> dict[str, Any]:
    copied = deepcopy(item)
    league = copied.get("league") or {}
    if "name" in league:
        league["name"] = translate_league_name(league.get("name"), lang)
    teams = copied.get("teams") or {}
    for side in ("home", "away"):
        if isinstance(teams.get(side), dict) and "name" in teams[side]:
            teams[side]["name"] = translate_team_name(teams[side].get("name"), lang)
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


def _now_hhmm() -> str:
    return now_hhmm()


def _log_api_failure(key: str, message: str, *args: Any) -> None:
    now = datetime.now()
    last = _api_failure_log_times.get(key)
    if last and (now - last).total_seconds() < 300:
        return
    _api_failure_log_times[key] = now
    logger.warning(message, *args)


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
