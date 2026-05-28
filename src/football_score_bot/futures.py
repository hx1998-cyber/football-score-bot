from __future__ import annotations

from datetime import date, datetime
from typing import Any


WORLD_CUP_START_DATE = date(2026, 6, 11)


def world_cup_countdown_days(today: date | None = None) -> int:
    current = today or date.today()
    return max((WORLD_CUP_START_DATE - current).days, 0)


def format_worldcup_zone(lang_text: dict[str, str] | None = None) -> str:
    days = world_cup_countdown_days()
    return (
        "🏆 2026 世界杯专区\n\n"
        f"开赛倒计时：{days} 天\n"
        "可查看赛程、小组、积分和预测市场。"
    )


def format_futures_market(market_key: str, options: list[dict[str, Any]], page: int = 0, per_page: int = 5) -> str:
    title = _market_title(market_key, options)
    if market_key == "world_cup_winner":
        header = "🔥 世界杯冠军预测"
        prompt = "请选择你看好的冠军球队："
    elif market_key == "golden_boot":
        header = "🥇 金靴奖预测"
        prompt = "请选择你看好的金靴球员："
    else:
        header = title
        prompt = "请选择你的预测："

    visible = options[page * per_page : (page + 1) * per_page]
    lines = [header, "演示赔率，仅供功能测试。", "", prompt, ""]
    lines.extend(f"{option['label']} {_format_odds(option['odds'])}" for option in visible)
    total_pages = max((len(options) - 1) // per_page + 1, 1)
    if total_pages > 1:
        lines.append(f"\n第 {page + 1}/{total_pages} 页")
    return "\n".join(lines)


def format_prediction_confirm(option: dict[str, Any]) -> str:
    return (
        "🎯 预测确认\n\n"
        f"市场：{option['market_title']}\n"
        f"选择：{option['label']}\n"
        f"赔率：{_format_odds(option['odds'])}\n\n"
        "当前版本为模拟预测，不扣除余额，不产生真实注单。"
    )


def format_prediction_saved(option: dict[str, Any], prediction_id: int) -> str:
    return (
        "🎯 模拟预测已记录\n\n"
        f"编号：{prediction_id}\n"
        f"市场：{option['market_title']}\n"
        f"选择：{option['label']}\n"
        f"赔率：{_format_odds(option['odds'])}\n\n"
        "当前仅展示预测记录，不扣余额，不生成真实注单。"
    )


def format_my_predictions(predictions: list[dict[str, Any]]) -> str:
    if not predictions:
        return "🎯 我的预测\n\n暂无模拟预测记录。"
    lines = ["🎯 我的预测"]
    for item in predictions:
        created_at = item.get("created_at")
        if isinstance(created_at, datetime):
            created_text = created_at.strftime("%m-%d %H:%M")
        else:
            created_text = "-"
        lines.append(
            "\n"
            f"#{item['id']} {item['market_title']}\n"
            f"选择：{item['option_label']} ｜ 赔率：{_format_odds(item['odds'])}\n"
            f"模拟金额：{_format_odds(item['stake_simulated'])} ｜ 状态：{item['status']}\n"
            f"时间：{created_text}"
        )
    return "\n".join(lines)


def format_futures_placeholder(title: str) -> str:
    return f"{title}即将开放\n后续将根据 FIFA 官方分组和赛程开放。"


def _market_title(market_key: str, options: list[dict[str, Any]]) -> str:
    if options:
        return str(options[0].get("market_title") or "预测市场")
    return {
        "world_cup_winner": "世界杯冠军预测",
        "golden_boot": "金靴奖预测",
    }.get(market_key, "预测市场")


def _format_odds(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)
