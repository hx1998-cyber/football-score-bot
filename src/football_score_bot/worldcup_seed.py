from __future__ import annotations

from datetime import date

WORLD_CUP_START_DATE = date(2026, 6, 11)

WORLD_CUP_DEMO_MARKETS = {
    "world_cup_winner": [
        ("Brazil", "巴西", "5.50"),
        ("France", "法国", "6.00"),
        ("England", "英格兰", "7.00"),
        ("Argentina", "阿根廷", "8.00"),
        ("Spain", "西班牙", "8.50"),
        ("Germany", "德国", "10.00"),
        ("Portugal", "葡萄牙", "12.00"),
        ("Netherlands", "荷兰", "15.00"),
    ],
    "golden_boot": [
        ("Mbappe", "姆巴佩", "7.00"),
        ("Kane", "凯恩", "9.00"),
        ("Vinicius", "维尼修斯", "12.00"),
        ("Haaland", "哈兰德", "15.00"),
    ],
}

WORLD_CUP_SECTION_ENTRIES = [
    "世界杯赛程",
    "分组积分",
    "冠军预测",
    "小组晋级",
    "金靴奖",
    "MVP",
    "我的预测",
]


def countdown_days(today: date | None = None) -> int:
    return max((WORLD_CUP_START_DATE - (today or date.today())).days, 0)
