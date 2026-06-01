from __future__ import annotations

from decimal import Decimal
from typing import Any

from football_score_bot.i18n_football import format_flag_team, team_flag, zh_country_team


WORLD_CUP_CHAMPION_MARKET_KEY = "worldcup_champion_2026"
WORLD_CUP_CHAMPION_LEGACY_KEY = "world_cup_winner"
WORLD_CUP_CHAMPION_TITLE = "2026世界杯冠军"
WORLD_CUP_CHAMPION_FIXTURE_LABEL = "2026世界杯冠军预测"

WORLD_CUP_CHAMPION_ODDS = [
    {"team": "Spain", "team_zh": "西班牙", "flag": "🇪🇸", "odds": Decimal("5.50")},
    {"team": "France", "team_zh": "法国", "flag": "🇫🇷", "odds": Decimal("6.50")},
    {"team": "England", "team_zh": "英格兰", "flag": "🏴", "odds": Decimal("7.50")},
    {"team": "Brazil", "team_zh": "巴西", "flag": "🇧🇷", "odds": Decimal("9.00")},
    {"team": "Argentina", "team_zh": "阿根廷", "flag": "🇦🇷", "odds": Decimal("9.00")},
    {"team": "Portugal", "team_zh": "葡萄牙", "flag": "🇵🇹", "odds": Decimal("11.00")},
    {"team": "Germany", "team_zh": "德国", "flag": "🇩🇪", "odds": Decimal("13.00")},
    {"team": "Netherlands", "team_zh": "荷兰", "flag": "🇳🇱", "odds": Decimal("21.00")},
    {"team": "Norway", "team_zh": "挪威", "flag": "🇳🇴", "odds": Decimal("26.00")},
    {"team": "Belgium", "team_zh": "比利时", "flag": "🇧🇪", "odds": Decimal("34.00")},
    {"team": "United States", "team_zh": "美国", "flag": "🇺🇸", "odds": Decimal("41.00")},
    {"team": "Colombia", "team_zh": "哥伦比亚", "flag": "🇨🇴", "odds": Decimal("51.00")},
    {"team": "Uruguay", "team_zh": "乌拉圭", "flag": "🇺🇾", "odds": Decimal("51.00")},
    {"team": "Switzerland", "team_zh": "瑞士", "flag": "🇨🇭", "odds": Decimal("67.00")},
    {"team": "Mexico", "team_zh": "墨西哥", "flag": "🇲🇽", "odds": Decimal("67.00")},
    {"team": "Morocco", "team_zh": "摩洛哥", "flag": "🇲🇦", "odds": Decimal("67.00")},
    {"team": "Japan", "team_zh": "日本", "flag": "🇯🇵", "odds": Decimal("67.00")},
    {"team": "Turkey", "team_zh": "土耳其", "flag": "🇹🇷", "odds": Decimal("67.00")},
    {"team": "Croatia", "team_zh": "克罗地亚", "flag": "🇭🇷", "odds": Decimal("81.00")},
    {"team": "Ecuador", "team_zh": "厄瓜多尔", "flag": "🇪🇨", "odds": Decimal("81.00")},
    {"team": "Sweden", "team_zh": "瑞典", "flag": "🇸🇪", "odds": Decimal("81.00")},
    {"team": "Senegal", "team_zh": "塞内加尔", "flag": "🇸🇳", "odds": Decimal("101.00")},
    {"team": "Canada", "team_zh": "加拿大", "flag": "🇨🇦", "odds": Decimal("151.00")},
    {"team": "Paraguay", "team_zh": "巴拉圭", "flag": "🇵🇾", "odds": Decimal("151.00")},
    {"team": "Austria", "team_zh": "奥地利", "flag": "🇦🇹", "odds": Decimal("151.00")},
    {"team": "Czech Republic", "team_zh": "捷克", "flag": "🇨🇿", "odds": Decimal("201.00")},
    {"team": "Bosnia and Herzegovina", "team_zh": "波黑", "flag": "🇧🇦", "odds": Decimal("201.00")},
    {"team": "Scotland", "team_zh": "苏格兰", "flag": "🏴", "odds": Decimal("251.00")},
    {"team": "South Korea", "team_zh": "韩国", "flag": "🇰🇷", "odds": Decimal("251.00")},
    {"team": "Ivory Coast", "team_zh": "科特迪瓦", "flag": "🇨🇮", "odds": Decimal("251.00")},
    {"team": "Egypt", "team_zh": "埃及", "flag": "🇪🇬", "odds": Decimal("251.00")},
    {"team": "Algeria", "team_zh": "阿尔及利亚", "flag": "🇩🇿", "odds": Decimal("301.00")},
    {"team": "Ghana", "team_zh": "加纳", "flag": "🇬🇭", "odds": Decimal("401.00")},
    {"team": "Australia", "team_zh": "澳大利亚", "flag": "🇦🇺", "odds": Decimal("501.00")},
    {"team": "Tunisia", "team_zh": "突尼斯", "flag": "🇹🇳", "odds": Decimal("501.00")},
    {"team": "Iran", "team_zh": "伊朗", "flag": "🇮🇷", "odds": Decimal("501.00")},
    {"team": "Congo DR", "team_zh": "民主刚果", "flag": "🇨🇩", "odds": Decimal("751.00")},
    {"team": "Panama", "team_zh": "巴拿马", "flag": "🇵🇦", "odds": Decimal("1001.00")},
    {"team": "South Africa", "team_zh": "南非", "flag": "🇿🇦", "odds": Decimal("1001.00")},
    {"team": "Uzbekistan", "team_zh": "乌兹别克斯坦", "flag": "🇺🇿", "odds": Decimal("1001.00")},
    {"team": "Saudi Arabia", "team_zh": "沙特阿拉伯", "flag": "🇸🇦", "odds": Decimal("1001.00")},
    {"team": "Qatar", "team_zh": "卡塔尔", "flag": "🇶🇦", "odds": Decimal("1001.00")},
    {"team": "New Zealand", "team_zh": "新西兰", "flag": "🇳🇿", "odds": Decimal("1001.00")},
    {"team": "Jordan", "team_zh": "约旦", "flag": "🇯🇴", "odds": Decimal("1001.00")},
    {"team": "Cape Verde", "team_zh": "佛得角", "flag": "🇨🇻", "odds": Decimal("1001.00")},
    {"team": "Iraq", "team_zh": "伊拉克", "flag": "🇮🇶", "odds": Decimal("1001.00")},
    {"team": "Haiti", "team_zh": "海地", "flag": "🇭🇹", "odds": Decimal("2501.00")},
    {"team": "Curacao", "team_zh": "库拉索", "flag": "🇨🇼", "odds": Decimal("2501.00")},
]


def champion_option_label(team: str | None) -> str:
    return format_flag_team(team)


def champion_option_metadata(item: dict[str, Any]) -> dict[str, str]:
    team = str(item["team"])
    return {
        "team": team,
        "team_zh": str(item.get("team_zh") or zh_country_team(team)),
        "flag": str(item.get("flag") or team_flag(team)),
    }
