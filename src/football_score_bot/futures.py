from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from football_score_bot.worldcup_futures import WORLD_CUP_CHAMPION_MARKET_KEY


WORLD_CUP_START_DATE = date(2026, 6, 11)


def world_cup_countdown_days(today: date | None = None) -> int:
    current = today or date.today()
    return max((WORLD_CUP_START_DATE - current).days, 0)


def format_worldcup_zone(lang_text: dict[str, str] | None = None) -> str:
    days = world_cup_countdown_days()
    return f"🏆 2026 世界杯专区\n\n开赛倒计时：{days} 天\n可查看赛程、小组、积分和冠军预测投注。"


def format_futures_market(market_key: str, options: list[dict[str, Any]], page: int = 0, per_page: int = 8) -> str:
    if market_key == WORLD_CUP_CHAMPION_MARKET_KEY:
        header = "🏆 2026 世界杯冠军预测"
    elif market_key == "golden_boot":
        header = "🥇 金靴奖预测"
    else:
        header = _market_title(market_key, options)

    visible = options[page * per_page : (page + 1) * per_page]
    lines = [header, ""]
    for index, option in enumerate(visible, start=page * per_page + 1):
        lines.append(f"{index}. {option['label']} @ {_format_odds(option['odds'])}")
    total_pages = max((len(options) - 1) // per_page + 1, 1)
    if total_pages > 1:
        lines.append(f"\n第 {page + 1}/{total_pages} 页")
    return "\n".join(lines)


def format_prediction_confirm(option: dict[str, Any]) -> str:
    if option.get("market_key") == WORLD_CUP_CHAMPION_MARKET_KEY:
        return (
            "🏆 世界杯冠军投注\n\n"
            f"选择：{option['label']}\n"
            f"赔率：{_format_odds(option['odds'])}\n\n"
            "请选择下注金额。"
        )
    return (
        "🎯 预测确认\n\n"
        f"市场：{option['market_title']}\n"
        f"选择：{option['label']}\n"
        f"赔率：{_format_odds(option['odds'])}\n\n"
        "当前版本为模拟预测。"
    )


def format_champion_bet_confirm(option: dict[str, Any], stake: Decimal) -> str:
    odds = Decimal(str(option["odds"]))
    payout = (stake * odds).quantize(Decimal("0.01"))
    return (
        "🏆 世界杯冠军投注确认\n\n"
        f"选择：{option['label']}\n"
        f"赔率：{_format_odds(option['odds'])}\n"
        f"金额：{stake:.2f} USDT\n"
        f"预计派彩：{payout:.2f} USDT"
    )


def format_prediction_saved(option: dict[str, Any], prediction_id: int) -> str:
    return (
        "🎯 模拟预测已记录\n\n"
        f"编号：{prediction_id}\n"
        f"市场：{option['market_title']}\n"
        f"选择：{option['label']}\n"
        f"赔率：{_format_odds(option['odds'])}"
    )


def format_my_predictions(predictions: list[dict[str, Any]]) -> str:
    if not predictions:
        return "🎯 我的预测\n\n暂无模拟预测记录。"
    lines = ["🎯 我的预测"]
    for item in predictions:
        created_at = item.get("created_at")
        created_text = created_at.strftime("%m-%d %H:%M") if isinstance(created_at, datetime) else "-"
        lines.append(
            "\n"
            f"#{item['id']} {item['market_title']}\n"
            f"选择：{item['option_label']} | 赔率：{_format_odds(item['odds'])}\n"
            f"金额：{_format_odds(item['stake_simulated'])} | 状态：{item['status']}\n"
            f"时间：{created_text}"
        )
    return "\n".join(lines)


def format_futures_placeholder(title: str) -> str:
    return f"{title}即将开放\n后续将根据 FIFA 官方分组和赛程开放。"


def _market_title(market_key: str, options: list[dict[str, Any]]) -> str:
    if options:
        return str(options[0].get("market_title") or "预测市场")
    return {
        WORLD_CUP_CHAMPION_MARKET_KEY: "世界杯冠军预测",
        "golden_boot": "金靴奖预测",
    }.get(market_key, "预测市场")


def _format_odds(value: Any) -> str:
    try:
        return f"{Decimal(str(value)):.2f}"
    except Exception:
        return str(value)
