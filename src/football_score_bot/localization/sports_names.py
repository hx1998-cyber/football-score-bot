from __future__ import annotations


LEAGUE_TRANSLATIONS = {
    "World Cup": {"zh-CN": "世界杯", "zh-TW": "世界盃", "ja": "ワールドカップ", "ko": "월드컵"},
    "UEFA Champions League": {"zh-CN": "欧冠", "zh-TW": "歐冠", "ja": "UEFAチャンピオンズリーグ", "ko": "UEFA 챔피언스리그"},
    "Premier League": {"zh-CN": "英超", "zh-TW": "英超", "ja": "プレミアリーグ", "ko": "프리미어리그"},
    "La Liga": {"zh-CN": "西甲", "zh-TW": "西甲", "ja": "ラ・リーガ", "ko": "라리가"},
    "Serie A": {"zh-CN": "意甲", "zh-TW": "義甲", "ja": "セリエA", "ko": "세리에 A"},
    "Bundesliga": {"zh-CN": "德甲", "zh-TW": "德甲", "ja": "ブンデスリーガ", "ko": "분데스리가"},
    "Ligue 1": {"zh-CN": "法甲", "zh-TW": "法甲", "ja": "リーグ・アン", "ko": "리그 1"},
    "Copa America": {"zh-CN": "美洲杯", "zh-TW": "美洲盃", "ja": "コパ・アメリカ", "ko": "코파 아메리카"},
    "AFC Champions League": {"zh-CN": "亚冠", "zh-TW": "亞冠", "ja": "AFCチャンピオンズリーグ", "ko": "AFC 챔피언스리그"},
}

TEAM_TRANSLATIONS = {
    "Brazil": {"zh-CN": "巴西", "zh-TW": "巴西", "ja": "ブラジル", "ko": "브라질"},
    "France": {"zh-CN": "法国", "zh-TW": "法國", "ja": "フランス", "ko": "프랑스"},
    "England": {"zh-CN": "英格兰", "zh-TW": "英格蘭", "ja": "イングランド", "ko": "잉글랜드"},
    "Argentina": {"zh-CN": "阿根廷", "zh-TW": "阿根廷", "ja": "アルゼンチン", "ko": "아르헨티나"},
    "Spain": {"zh-CN": "西班牙", "zh-TW": "西班牙", "ja": "スペイン", "ko": "스페인"},
    "Germany": {"zh-CN": "德国", "zh-TW": "德國", "ja": "ドイツ", "ko": "독일"},
    "Portugal": {"zh-CN": "葡萄牙", "zh-TW": "葡萄牙", "ja": "ポルトガル", "ko": "포르투갈"},
    "Netherlands": {"zh-CN": "荷兰", "zh-TW": "荷蘭", "ja": "オランダ", "ko": "네덜란드"},
    "Japan": {"zh-CN": "日本", "zh-TW": "日本", "ja": "日本", "ko": "일본"},
    "Korea Republic": {"zh-CN": "韩国", "zh-TW": "韓國", "ja": "韓国", "ko": "대한민국"},
    "China": {"zh-CN": "中国", "zh-TW": "中國", "ja": "中国", "ko": "중국"},
    "USA": {"zh-CN": "美国", "zh-TW": "美國", "ja": "アメリカ", "ko": "미국"},
    "United States": {"zh-CN": "美国", "zh-TW": "美國", "ja": "アメリカ", "ko": "미국"},
    "Uruguay": {"zh-CN": "乌拉圭", "zh-TW": "烏拉圭", "ja": "ウルグアイ", "ko": "우루과이"},
    "Belgium": {"zh-CN": "比利时", "zh-TW": "比利時", "ja": "ベルギー", "ko": "벨기에"},
    "Italy": {"zh-CN": "意大利", "zh-TW": "義大利", "ja": "イタリア", "ko": "이탈리아"},
    "Mexico": {"zh-CN": "墨西哥", "zh-TW": "墨西哥", "ja": "メキシコ", "ko": "멕시코"},
    "Canada": {"zh-CN": "加拿大", "zh-TW": "加拿大", "ja": "カナダ", "ko": "캐나다"},
}


def translate_team_name(name: str | None, lang: str) -> str:
    return _translate(name, lang, TEAM_TRANSLATIONS)


def translate_league_name(name: str | None, lang: str) -> str:
    return _translate(name, lang, LEAGUE_TRANSLATIONS)


def _translate(name: str | None, lang: str, translations: dict[str, dict[str, str]]) -> str:
    if not name:
        return "-"
    if lang.startswith("en"):
        return name
    return translations.get(name, {}).get(lang) or translations.get(name, {}).get(lang.split("-", 1)[0]) or name
