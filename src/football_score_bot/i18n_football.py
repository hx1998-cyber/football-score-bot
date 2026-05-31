from __future__ import annotations

from datetime import datetime
from typing import Any


LEAGUE_ZH_NAMES = {
    "UEFA Champions League": "欧冠",
    "Champions League": "欧冠",
    "UEFA Europa League": "欧联杯",
    "Europa League": "欧联杯",
    "Premier League": "英超",
    "La Liga": "西甲",
    "Bundesliga": "德甲",
    "Serie A": "意甲",
    "Ligue 1": "法甲",
    "FIFA World Cup": "世界杯",
    "World Cup": "世界杯",
    "Club World Cup": "世俱杯",
    "Friendlies": "友谊赛",
    "Friendlies Women": "女子友谊赛",
    "UEFA Nations League": "欧国联",
    "FA Cup": "英足总杯",
    "EFL Cup": "英联杯",
    "Copa del Rey": "国王杯",
    "DFB Pokal": "德国杯",
    "Coppa Italia": "意大利杯",
    "Major League Soccer": "美职联",
    "AFC Champions League": "亚冠",
    "Copa America": "美洲杯",
    "Africa Cup of Nations": "非洲杯",
}

TEAM_ZH_NAMES = {
    "Paris Saint Germain": "巴黎圣日耳曼",
    "Paris Saint-Germain": "巴黎圣日耳曼",
    "PSG": "巴黎圣日耳曼",
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
    "Borussia Dortmund": "多特蒙德",
    "Inter": "国际米兰",
    "Inter Milan": "国际米兰",
    "AC Milan": "AC米兰",
    "Juventus": "尤文图斯",
    "Atletico Madrid": "马德里竞技",
    "Athletic Club": "毕尔巴鄂竞技",
    "Granada CF": "格拉纳达",
    "Granada": "格拉纳达",
    "Sporting Gijon": "希洪竞技",
    "Athletic Club W": "毕尔巴鄂竞技女足",
    "Alabama W": "阿拉巴马女足",
    "Real Sociedad": "皇家社会",
    "Sevilla": "塞维利亚",
    "Valencia": "瓦伦西亚",
    "Villarreal": "比利亚雷亚尔",
    "Napoli": "那不勒斯",
    "AS Roma": "罗马",
    "Lazio": "拉齐奥",
    "Fiorentina": "佛罗伦萨",
    "Bayer Leverkusen": "勒沃库森",
    "RB Leipzig": "莱比锡",
    "Ajax": "阿贾克斯",
    "Benfica": "本菲卡",
    "FC Porto": "波尔图",
}

COUNTRY_TEAM_ZH_NAMES = {
    "Mexico": "墨西哥",
    "South Africa": "南非",
    "South Korea": "韩国",
    "Korea Republic": "韩国",
    "Czech Republic": "捷克",
    "Czechia": "捷克",
    "Canada": "加拿大",
    "Bosnia and Herzegovina": "波黑",
    "United States": "美国",
    "USA": "美国",
    "Paraguay": "巴拉圭",
    "Qatar": "卡塔尔",
    "Brazil": "巴西",
    "Morocco": "摩洛哥",
    "Haiti": "海地",
    "Scotland": "苏格兰",
    "Australia": "澳大利亚",
    "Turkey": "土耳其",
    "Türkiye": "土耳其",
    "Germany": "德国",
    "Curacao": "库拉索",
    "Curaçao": "库拉索",
    "Netherlands": "荷兰",
    "Japan": "日本",
    "Ivory Coast": "科特迪瓦",
    "Cote d'Ivoire": "科特迪瓦",
    "Ecuador": "厄瓜多尔",
    "Sweden": "瑞典",
    "Tunisia": "突尼斯",
    "France": "法国",
    "England": "英格兰",
    "Argentina": "阿根廷",
    "Spain": "西班牙",
    "Portugal": "葡萄牙",
    "Belgium": "比利时",
    "Italy": "意大利",
    "Uruguay": "乌拉圭",
    "Colombia": "哥伦比亚",
    "Chile": "智利",
    "Poland": "波兰",
    "Croatia": "克罗地亚",
    "Serbia": "塞尔维亚",
    "Denmark": "丹麦",
    "Switzerland": "瑞士",
    "Austria": "奥地利",
    "Norway": "挪威",
    "Wales": "威尔士",
    "Ireland": "爱尔兰",
    "Ukraine": "乌克兰",
    "Ghana": "加纳",
    "Senegal": "塞内加尔",
    "Nigeria": "尼日利亚",
    "Cameroon": "喀麦隆",
    "Egypt": "埃及",
    "Algeria": "阿尔及利亚",
    "Iran": "伊朗",
    "Saudi Arabia": "沙特阿拉伯",
    "Costa Rica": "哥斯达黎加",
    "Panama": "巴拿马",
    "New Zealand": "新西兰",
}

WORLD_CUP_FLAGS = {
    "Mexico": "🇲🇽",
    "South Africa": "🇿🇦",
    "South Korea": "🇰🇷",
    "Korea Republic": "🇰🇷",
    "Czech Republic": "🇨🇿",
    "Czechia": "🇨🇿",
    "Canada": "🇨🇦",
    "Bosnia and Herzegovina": "🇧🇦",
    "United States": "🇺🇸",
    "USA": "🇺🇸",
    "Paraguay": "🇵🇾",
    "Qatar": "🇶🇦",
    "Brazil": "🇧🇷",
    "Morocco": "🇲🇦",
    "Haiti": "🇭🇹",
    "Scotland": "🏴",
    "Australia": "🇦🇺",
    "Turkey": "🇹🇷",
    "Türkiye": "🇹🇷",
    "Germany": "🇩🇪",
    "Curacao": "🇨🇼",
    "Curaçao": "🇨🇼",
    "Netherlands": "🇳🇱",
    "Japan": "🇯🇵",
    "Ivory Coast": "🇨🇮",
    "Cote d'Ivoire": "🇨🇮",
    "Ecuador": "🇪🇨",
    "Sweden": "🇸🇪",
    "Tunisia": "🇹🇳",
    "France": "🇫🇷",
    "England": "🏴",
    "Argentina": "🇦🇷",
    "Spain": "🇪🇸",
    "Portugal": "🇵🇹",
    "Belgium": "🇧🇪",
    "Italy": "🇮🇹",
    "Uruguay": "🇺🇾",
    "Colombia": "🇨🇴",
    "Poland": "🇵🇱",
    "Croatia": "🇭🇷",
    "Serbia": "🇷🇸",
    "Denmark": "🇩🇰",
    "Switzerland": "🇨🇭",
    "Austria": "🇦🇹",
    "Norway": "🇳🇴",
    "Wales": "🏴",
    "Ukraine": "🇺🇦",
    "Ghana": "🇬🇭",
    "Senegal": "🇸🇳",
    "Nigeria": "🇳🇬",
    "Cameroon": "🇨🇲",
    "Egypt": "🇪🇬",
    "Iran": "🇮🇷",
    "Saudi Arabia": "🇸🇦",
    "Costa Rica": "🇨🇷",
    "Panama": "🇵🇦",
    "New Zealand": "🇳🇿",
}


def zh_league_name(name: str | None) -> str:
    if not name:
        return "-"
    return LEAGUE_ZH_NAMES.get(name, name)


def zh_team_name(name: str | None) -> str:
    if not name:
        return "-"
    return TEAM_ZH_NAMES.get(name) or COUNTRY_TEAM_ZH_NAMES.get(name) or name


def zh_country_team(name: str | None) -> str:
    if not name:
        return "-"
    return COUNTRY_TEAM_ZH_NAMES.get(name, name)


def team_flag(name: str | None) -> str:
    return WORLD_CUP_FLAGS.get(name or "", "🏳")


def format_match_title(fixture: dict[str, Any]) -> str:
    league = fixture.get("league") or {}
    teams = fixture.get("teams") or {}
    league_name = zh_league_name(league.get("name"))
    round_label = _short_round_label(league.get("round"))
    home = zh_team_name((teams.get("home") or {}).get("name"))
    away = zh_team_name((teams.get("away") or {}).get("name"))
    if league_name == "-":
        return f"{home} vs {away}"
    suffix = f"  {round_label}" if round_label and league_name == "世界杯" else ""
    return f"【{league_name}{suffix}】{home} vs {away}"


def worldcup_stage_label(fixture: dict[str, Any]) -> str:
    league = fixture.get("league") or {}
    return _short_round_label(league.get("round")) or zh_league_name(league.get("name"))


def worldcup_match_line(fixture: dict[str, Any]) -> str:
    teams = fixture.get("teams") or {}
    home_raw = (teams.get("home") or {}).get("name")
    away_raw = (teams.get("away") or {}).get("name")
    return f"{team_flag(home_raw)} {zh_country_team(home_raw)}  vs  {team_flag(away_raw)} {zh_country_team(away_raw)}"


def fixture_beijing_datetime(fixture: dict[str, Any]) -> datetime | None:
    info = fixture.get("fixture") or {}
    timestamp = info.get("timestamp")
    if timestamp:
        try:
            return datetime.fromtimestamp(int(timestamp))
        except (TypeError, ValueError, OSError):
            return None
    raw = info.get("date")
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
        except ValueError:
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
