from __future__ import annotations

from datetime import datetime
from typing import Any


LEAGUE_ZH_NAMES = {
    "FIFA World Cup": "世界杯",
    "World Cup": "世界杯",
    "Club World Cup": "世俱杯",
    "UEFA Champions League": "欧冠",
    "Champions League": "欧冠",
    "UEFA Europa League": "欧联杯",
    "Europa League": "欧联杯",
    "Premier League": "英超",
    "La Liga": "西甲",
    "Bundesliga": "德甲",
    "Serie A": "意甲",
    "Ligue 1": "法甲",
}

TEAM_ZH_NAMES = {
    "Arsenal": "阿森纳",
    "Real Madrid": "皇家马德里",
    "Barcelona": "巴塞罗那",
    "Manchester City": "曼城",
    "Manchester United": "曼联",
    "Liverpool": "利物浦",
    "Chelsea": "切尔西",
    "Tottenham": "热刺",
    "Tottenham Hotspur": "热刺",
    "Bayern Munich": "拜仁慕尼黑",
    "Paris Saint Germain": "巴黎圣日耳曼",
    "Paris Saint-Germain": "巴黎圣日耳曼",
    "PSG": "巴黎圣日耳曼",
}

COUNTRY_TEAM_ZH_NAMES = {
    "Spain": "西班牙",
    "France": "法国",
    "England": "英格兰",
    "Brazil": "巴西",
    "Argentina": "阿根廷",
    "Portugal": "葡萄牙",
    "Germany": "德国",
    "Netherlands": "荷兰",
    "Norway": "挪威",
    "Belgium": "比利时",
    "United States": "美国",
    "USA": "美国",
    "Colombia": "哥伦比亚",
    "Uruguay": "乌拉圭",
    "Switzerland": "瑞士",
    "Mexico": "墨西哥",
    "Morocco": "摩洛哥",
    "Japan": "日本",
    "Turkey": "土耳其",
    "Türkiye": "土耳其",
    "Croatia": "克罗地亚",
    "Ecuador": "厄瓜多尔",
    "Sweden": "瑞典",
    "Senegal": "塞内加尔",
    "Canada": "加拿大",
    "Paraguay": "巴拉圭",
    "Austria": "奥地利",
    "Czech Republic": "捷克",
    "Czechia": "捷克",
    "Bosnia & Herzegovina": "波黑",
    "Bosnia and Herzegovina": "波黑",
    "Bosnia-Herzegovina": "波黑",
    "Scotland": "苏格兰",
    "South Korea": "韩国",
    "Korea Republic": "韩国",
    "Republic of Korea": "韩国",
    "Ivory Coast": "科特迪瓦",
    "Cote d'Ivoire": "科特迪瓦",
    "Egypt": "埃及",
    "Algeria": "阿尔及利亚",
    "Ghana": "加纳",
    "Australia": "澳大利亚",
    "Tunisia": "突尼斯",
    "Iran": "伊朗",
    "Congo DR": "民主刚果",
    "DR Congo": "民主刚果",
    "Panama": "巴拿马",
    "South Africa": "南非",
    "Uzbekistan": "乌兹别克斯坦",
    "Saudi Arabia": "沙特阿拉伯",
    "Qatar": "卡塔尔",
    "New Zealand": "新西兰",
    "Jordan": "约旦",
    "Cape Verde": "佛得角",
    "Cape Verde Islands": "佛得角",
    "Iraq": "伊拉克",
    "Haiti": "海地",
    "Curacao": "库拉索",
    "Curaçao": "库拉索",
    "Jamaica": "牙买加",
    "Costa Rica": "哥斯达黎加",
    "Wales": "威尔士",
    "Ukraine": "乌克兰",
    "Poland": "波兰",
    "Serbia": "塞尔维亚",
    "Hungary": "匈牙利",
    "Romania": "罗马尼亚",
    "Slovakia": "斯洛伐克",
    "Slovenia": "斯洛文尼亚",
    "Greece": "希腊",
    "Denmark": "丹麦",
    "Chile": "智利",
    "Peru": "秘鲁",
    "Venezuela": "委内瑞拉",
    "Bolivia": "玻利维亚",
    "Nigeria": "尼日利亚",
    "Cameroon": "喀麦隆",
    "Mali": "马里",
    "Italy": "意大利",
    "Ireland": "爱尔兰",
}

WORLD_CUP_FLAGS = {
    "Spain": "🇪🇸",
    "France": "🇫🇷",
    "England": "🏴",
    "Brazil": "🇧🇷",
    "Argentina": "🇦🇷",
    "Portugal": "🇵🇹",
    "Germany": "🇩🇪",
    "Netherlands": "🇳🇱",
    "Norway": "🇳🇴",
    "Belgium": "🇧🇪",
    "United States": "🇺🇸",
    "USA": "🇺🇸",
    "Colombia": "🇨🇴",
    "Uruguay": "🇺🇾",
    "Switzerland": "🇨🇭",
    "Mexico": "🇲🇽",
    "Morocco": "🇲🇦",
    "Japan": "🇯🇵",
    "Turkey": "🇹🇷",
    "Türkiye": "🇹🇷",
    "Croatia": "🇭🇷",
    "Ecuador": "🇪🇨",
    "Sweden": "🇸🇪",
    "Senegal": "🇸🇳",
    "Canada": "🇨🇦",
    "Paraguay": "🇵🇾",
    "Austria": "🇦🇹",
    "Czech Republic": "🇨🇿",
    "Czechia": "🇨🇿",
    "Bosnia & Herzegovina": "🇧🇦",
    "Bosnia and Herzegovina": "🇧🇦",
    "Bosnia-Herzegovina": "🇧🇦",
    "Scotland": "🏴",
    "South Korea": "🇰🇷",
    "Korea Republic": "🇰🇷",
    "Republic of Korea": "🇰🇷",
    "Ivory Coast": "🇨🇮",
    "Cote d'Ivoire": "🇨🇮",
    "Egypt": "🇪🇬",
    "Algeria": "🇩🇿",
    "Ghana": "🇬🇭",
    "Australia": "🇦🇺",
    "Tunisia": "🇹🇳",
    "Iran": "🇮🇷",
    "Congo DR": "🇨🇩",
    "DR Congo": "🇨🇩",
    "Panama": "🇵🇦",
    "South Africa": "🇿🇦",
    "Uzbekistan": "🇺🇿",
    "Saudi Arabia": "🇸🇦",
    "Qatar": "🇶🇦",
    "New Zealand": "🇳🇿",
    "Jordan": "🇯🇴",
    "Cape Verde": "🇨🇻",
    "Cape Verde Islands": "🇨🇻",
    "Iraq": "🇮🇶",
    "Haiti": "🇭🇹",
    "Curacao": "🇨🇼",
    "Curaçao": "🇨🇼",
    "Jamaica": "🇯🇲",
    "Costa Rica": "🇨🇷",
    "Wales": "🏴",
    "Ukraine": "🇺🇦",
    "Poland": "🇵🇱",
    "Serbia": "🇷🇸",
    "Hungary": "🇭🇺",
    "Romania": "🇷🇴",
    "Slovakia": "🇸🇰",
    "Slovenia": "🇸🇮",
    "Greece": "🇬🇷",
    "Denmark": "🇩🇰",
    "Chile": "🇨🇱",
    "Peru": "🇵🇪",
    "Venezuela": "🇻🇪",
    "Bolivia": "🇧🇴",
    "Nigeria": "🇳🇬",
    "Cameroon": "🇨🇲",
    "Mali": "🇲🇱",
    "Italy": "🇮🇹",
    "Ireland": "🇮🇪",
}

TEAM_ALIASES = {
    "Bosnia": "Bosnia and Herzegovina",
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Cape Verde Islands": "Cape Verde",
}


def normalize_team_name(name: str | None) -> str:
    raw = str(name or "").strip()
    return TEAM_ALIASES.get(raw, raw)


def zh_league_name(name: str | None) -> str:
    if not name:
        return "-"
    return LEAGUE_ZH_NAMES.get(name, name)


def zh_team_name(name: str | None) -> str:
    if not name:
        return "-"
    normalized = normalize_team_name(name)
    return TEAM_ZH_NAMES.get(normalized) or COUNTRY_TEAM_ZH_NAMES.get(normalized) or name


def zh_country_team(name: str | None) -> str:
    if not name:
        return "-"
    normalized = normalize_team_name(name)
    return COUNTRY_TEAM_ZH_NAMES.get(normalized, name)


def team_flag(name: str | None) -> str:
    if not name:
        return "🏳"
    normalized = normalize_team_name(name)
    return WORLD_CUP_FLAGS.get(normalized, "🏳")


def format_flag_team(name: str | None, lang: str = "zh") -> str:
    if str(lang or "").lower().startswith("en"):
        label = normalize_team_name(name) or "-"
    else:
        label = zh_country_team(name)
    return f"{team_flag(name)} {label}"


def format_match_title(fixture: dict[str, Any]) -> str:
    league = fixture.get("league") or {}
    teams = fixture.get("teams") or {}
    league_name = zh_league_name(league.get("name"))
    round_label = _short_round_label(league.get("round"))
    home = zh_team_name((teams.get("home") or {}).get("name"))
    away = zh_team_name((teams.get("away") or {}).get("name"))
    if league_name == "-":
        return f"{home} vs {away}"
    suffix = f" {round_label}" if round_label and league_name == "世界杯" else ""
    return f"【{league_name}{suffix}】{home} vs {away}"


def worldcup_stage_label(fixture: dict[str, Any], lang: str = "zh") -> str:
    league = fixture.get("league") or {}
    raw = league.get("round") or league.get("name")
    if str(lang or "").lower().startswith("en"):
        return str(raw or "-")
    return _short_round_label(raw) or zh_league_name(league.get("name"))


def worldcup_match_line(fixture: dict[str, Any], lang: str = "zh") -> str:
    teams = fixture.get("teams") or {}
    home_raw = (teams.get("home") or {}).get("name")
    away_raw = (teams.get("away") or {}).get("name")
    return f"{format_flag_team(home_raw, lang)} vs {format_flag_team(away_raw, lang)}"


def fixture_beijing_datetime(fixture: dict[str, Any]) -> datetime | None:
    info = fixture.get("fixture") or {}
    raw = info.get("date")
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
    timestamp = info.get("timestamp")
    if timestamp:
        try:
            return datetime.fromtimestamp(int(timestamp))
        except (TypeError, ValueError, OSError):
            return None
    return None


def _short_round_label(round_name: str | None) -> str:
    if not round_name:
        return ""
    text = str(round_name)
    replacements = {
        "Group Stage - ": "",
        "Group ": "",
        "Regular Season - ": "",
        "Round of 16": "16强",
        "Quarter-finals": "1/4决赛",
        "Semi-finals": "半决赛",
        "3rd Place Final": "三四名决赛",
        "Final": "决赛",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    if len(text) == 1 and text.isalpha():
        return f"{text.upper()}组"
    if text.upper() in {"A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"}:
        return f"{text.upper()}组"
    return text
