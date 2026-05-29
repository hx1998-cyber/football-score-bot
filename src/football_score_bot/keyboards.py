from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from football_score_bot.i18n import LANGUAGE_LABELS, SUPPORTED_LANGUAGES, t


def main_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🎯 可投注赛事"),
                KeyboardButton(text=t(lang, "live_scores")),
            ],
            [KeyboardButton(text="📋 全部赛程"), KeyboardButton(text="📊 我的注单")],
            [KeyboardButton(text=t(lang, "wallet")), KeyboardButton(text=t(lang, "referrals"))],
            [KeyboardButton(text=t(lang, "worldcup")), KeyboardButton(text=t(lang, "settings"))],
        ],
        resize_keyboard=True,
        input_field_placeholder=t(lang, "start_title"),
    )


def featured_matches_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 全部赛程", callback_data="today_all"),
                InlineKeyboardButton(text=t(lang, "live_scores"), callback_data="live_featured"),
            ],
            [
                InlineKeyboardButton(text="📊 我的注单", callback_data="bets:pending"),
                InlineKeyboardButton(text=t(lang, "back_home"), callback_data="home"),
            ],
        ]
    )


def worldcup_zone_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 世界杯赛程", callback_data="worldcup_schedule"),
                InlineKeyboardButton(text="📊 小组积分", callback_data="worldcup_standings"),
            ],
            [
                InlineKeyboardButton(text="🔥 冠军预测", callback_data="futures:market:world_cup_winner:page:0"),
                InlineKeyboardButton(text="🚀 小组晋级", callback_data="futures:placeholder:group_qualification"),
            ],
            [
                InlineKeyboardButton(text="🥇 小组第一", callback_data="futures:placeholder:group_winner"),
                InlineKeyboardButton(text="🏁 四强/决赛", callback_data="futures:placeholder:knockout_futures"),
            ],
            [
                InlineKeyboardButton(text="🥇 金靴奖", callback_data="futures:market:golden_boot:page:0"),
                InlineKeyboardButton(text="MVP", callback_data="futures:placeholder:mvp"),
            ],
            [InlineKeyboardButton(text="🏆 世界杯海报", callback_data="worldcup_poster")],
            [InlineKeyboardButton(text="🎯 我的预测", callback_data="futures:my")],
            [InlineKeyboardButton(text=t(lang, "back_home"), callback_data="home")],
        ]
    )


def futures_market_keyboard(
    market_key: str,
    options: list[dict],
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for option in options:
        row.append(
            InlineKeyboardButton(
                text=f"{option['label']} {float(option['odds']):.2f}"[:32],
                callback_data=f"futures:option:{option['option_id']}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="上一页", callback_data=f"futures:market:{market_key}:page:{page - 1}"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton(text="更多球队", callback_data=f"futures:market:{market_key}:page:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="返回世界杯专区", callback_data="worldcup")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# M12-Fix-2 overrides: confirmed bets use review/contact flow, never direct user release.
def bet_created_keyboard(bet_id_or_no: str, fixture_id: int | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="查看开奖", callback_data=f"bet_detail:{bet_id_or_no}:pending:0")],
            [InlineKeyboardButton(text="申请退单/联系客服", callback_data=f"bet_cancel:{bet_id_or_no}")],
            [InlineKeyboardButton(text="返回赛事", callback_data=f"fixture:{fixture_id}" if fixture_id else "today_featured")],
            [InlineKeyboardButton(text="返回首页", callback_data="home")],
        ]
    )


def bet_detail_keyboard(
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
        rows.append([InlineKeyboardButton(text="申请退单/联系客服", callback_data=f"bet_cancel:{bet_id_or_no}")])
    if fixture_id is not None:
        rows.append([InlineKeyboardButton(text="返回赛事", callback_data=f"fixture:{fixture_id}")])
    else:
        rows.append([InlineKeyboardButton(text="返回我的注单", callback_data=f"bets:{status_group}:{page}")])
    rows.append([InlineKeyboardButton(text="返回首页", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def futures_confirm_keyboard(option_id: int, market_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="确认模拟预测", callback_data=f"futures:confirm:{option_id}")],
            [InlineKeyboardButton(text="返回市场", callback_data=f"futures:market:{market_key}:page:0")],
        ]
    )


def futures_back_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="返回世界杯专区", callback_data="worldcup")],
            [InlineKeyboardButton(text=t(lang, "back_home"), callback_data="home")],
        ]
    )


def live_matches_keyboard(lang: str, include_all: bool = True) -> InlineKeyboardMarkup:
    first_row = []
    if include_all:
        first_row.append(InlineKeyboardButton(text="查看全部实时比赛", callback_data="live_all"))
    first_row.append(InlineKeyboardButton(text=t(lang, "featured_matches"), callback_data="today_featured"))
    return InlineKeyboardMarkup(
        inline_keyboard=[
            first_row,
            [InlineKeyboardButton(text=t(lang, "back_home"), callback_data="home")],
        ]
    )


def fixture_list_keyboard(fixtures: list[dict], lang: str, mode: str = "today") -> InlineKeyboardMarkup:
    rows = []
    for item in fixtures[:20]:
        fixture = item.get("fixture", {})
        teams = item.get("teams", {})
        fixture_id = fixture.get("id")
        if fixture_id is None:
            continue
        home = teams.get("home", {}).get("name", "主队")
        away = teams.get("away", {}).get("name", "客队")
        rows.append(
            [InlineKeyboardButton(text=f"详情 {home} vs {away}"[:64], callback_data=f"fixture:{fixture_id}")]
        )
    if mode == "today":
        rows.extend(
            [
                [
                    InlineKeyboardButton(text="📋 全部赛程", callback_data="today_all"),
                    InlineKeyboardButton(text="📊 我的注单", callback_data="bets:pending"),
                ],
                [
                    InlineKeyboardButton(text="刷新赔率", callback_data="refresh_odds"),
                    InlineKeyboardButton(text=t(lang, "back_home"), callback_data="home"),
                ],
            ]
        )
    else:
        rows.extend(
            [
                [
                    InlineKeyboardButton(text="查看全部实时比赛", callback_data="live_all"),
                    InlineKeyboardButton(text=t(lang, "featured_matches"), callback_data="today_featured"),
                ],
                [InlineKeyboardButton(text=t(lang, "back_home"), callback_data="home")],
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


MARKET_BUTTONS = [
    ("match_winner", "胜平负"),
    ("correct_score", "波胆"),
    ("over_under", "大小球"),
    ("handicap", "让球"),
    ("ht_ft", "半全场"),
    ("btts", "双方进球"),
]


def match_detail_keyboard(lang: str, fixture_id: int | None = None, return_to: str = "today_featured") -> InlineKeyboardMarkup:
    if fixture_id is not None:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="胜平负", callback_data=f"odds:fixture:{fixture_id}:market:match_winner"),
                    InlineKeyboardButton(text="波胆", callback_data=f"odds:fixture:{fixture_id}:market:correct_score"),
                ],
                [
                    InlineKeyboardButton(text="大小球", callback_data=f"odds:fixture:{fixture_id}:market:over_under"),
                    InlineKeyboardButton(text="让球", callback_data=f"odds:fixture:{fixture_id}:market:handicap"),
                ],
                [
                    InlineKeyboardButton(text="半全场", callback_data=f"odds:fixture:{fixture_id}:market:ht_ft"),
                    InlineKeyboardButton(text="双方进球", callback_data=f"odds:fixture:{fixture_id}:market:btts"),
                ],
                [
                    InlineKeyboardButton(text="返回", callback_data=return_to),
                ],
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="主胜", callback_data="bet_placeholder"),
                InlineKeyboardButton(text="平局", callback_data="bet_placeholder"),
                InlineKeyboardButton(text="客胜", callback_data="bet_placeholder"),
            ],
            [InlineKeyboardButton(text="订阅本场", callback_data="bet_placeholder")],
            [InlineKeyboardButton(text="返回赛事列表", callback_data=return_to)],
        ]
    )


def odds_market_keyboard(
    fixture_id: int,
    market_key: str,
    outcomes: list,
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    rows = []
    if market_key == "match_winner":
        row = []
        for idx, outcome in enumerate(outcomes[:3]):
            row.append(
                InlineKeyboardButton(
                    text=f"{_outcome_button_label(outcome)} {outcome.odds}",
                    callback_data=f"bet:{fixture_id}:{market_key}:{page}:{idx}",
                )
            )
        if row:
            rows.append(row)
    else:
        row = []
        for idx, outcome in enumerate(outcomes[:20]):
            row.append(
                InlineKeyboardButton(
                    text=f"{_outcome_button_label(outcome)} {outcome.odds}"[:32],
                    callback_data=f"bet:{fixture_id}:{market_key}:{page}:{idx}",
                )
            )
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="上一页", callback_data=f"odds:fixture:{fixture_id}:market:{market_key}:page:{page - 1}"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton(text="下一页", callback_data=f"odds:fixture:{fixture_id}:market:{market_key}:page:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="返回比赛详情", callback_data=f"fixture:{fixture_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bet_placeholder_keyboard(fixture_id: int, market_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="返回赔率", callback_data=f"odds:fixture:{fixture_id}:market:{market_key}")],
            [InlineKeyboardButton(text="返回首页", callback_data="home")],
        ]
    )


def bet_confirm_keyboard(fixture_id: int, market_key: str, page: int, outcome_index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="确认模拟投注", callback_data=f"bet_confirm:{fixture_id}:{market_key}:{page}:{outcome_index}")],
            [InlineKeyboardButton(text="修改金额", callback_data="bet_amount_placeholder")],
            [InlineKeyboardButton(text="返回赔率", callback_data=f"odds:fixture:{fixture_id}:market:{market_key}:page:{page}")],
        ]
    )


def my_bets_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="待结算", callback_data="bets:pending"),
                InlineKeyboardButton(text="已结算", callback_data="bets:settled"),
            ],
            [InlineKeyboardButton(text="返回首页", callback_data="home")],
        ]
    )


def _outcome_button_label(outcome: object) -> str:
    label = getattr(outcome, "label", "-")
    group = getattr(outcome, "group", None)
    if group == "home" and str(label).lower() in {"home", "1"}:
        return "主胜"
    if group == "draw" and str(label).lower() in {"draw", "x"}:
        return "平局"
    if group == "away" and str(label).lower() in {"away", "2"}:
        return "客胜"
    return str(label)


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=LANGUAGE_LABELS[lang], callback_data=f"lang:{lang}")]
            for lang in SUPPORTED_LANGUAGES
        ]
    )


# M10 overrides: keep these definitions at the end so older garbled labels above
# remain harmless while the bot exposes the upgraded lifecycle controls.
def main_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎯 可投注赛事"), KeyboardButton(text="📊 我的注单")],
            [KeyboardButton(text="💰 钱包"), KeyboardButton(text="👥 推广")],
            [KeyboardButton(text="🏆 世界杯"), KeyboardButton(text="🌐 语言")],
            [KeyboardButton(text="设置"), KeyboardButton(text="帮助")],
        ],
        resize_keyboard=True,
        input_field_placeholder=t(lang, "start_title"),
    )


def bet_confirm_keyboard(fixture_id: int, market_key: str, page: int, outcome_index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="确认下注", callback_data=f"bet_confirm:{fixture_id}:{market_key}:{page}:{outcome_index}:2")],
            [InlineKeyboardButton(text="修改金额", callback_data=f"bet_amount:{fixture_id}:{market_key}:{page}:{outcome_index}")],
            [InlineKeyboardButton(text="取消", callback_data=f"odds:fixture:{fixture_id}:market:{market_key}:page:{page}")],
        ]
    )


def bet_amount_keyboard(fixture_id: int, market_key: str, page: int, outcome_index: int) -> InlineKeyboardMarkup:
    rows = []
    for left, right in (("2", "5"), ("10", "20"), ("50", "custom")):
        rows.append(
            [
                InlineKeyboardButton(
                    text=("自定义金额" if value == "custom" else f"{value} USDT"),
                    callback_data=f"bet_amount_set:{fixture_id}:{market_key}:{page}:{outcome_index}:{value}",
                )
                for value in (left, right)
            ]
        )
    rows.append([InlineKeyboardButton(text="返回", callback_data=f"bet:{fixture_id}:{market_key}:{page}:{outcome_index}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_bets_keyboard(
    bets: list[dict] | None = None,
    status_group: str = "pending",
    page: int = 0,
    has_prev: bool = False,
    has_next: bool = False,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="待结算", callback_data="bets:pending:0"),
            InlineKeyboardButton(text="已结算", callback_data="bets:settled:0"),
        ]
    ]
    for bet in bets or []:
        bet_key = str(bet.get("bet_no") or bet.get("id"))
        rows.append([InlineKeyboardButton(text=f"注单 {bet_key}", callback_data=f"bet_detail:{bet_key}:{status_group}:{page}")])
    nav = []
    if has_prev:
        nav.append(InlineKeyboardButton(text="上一页", callback_data=f"bets:{status_group}:{page - 1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="下一页", callback_data=f"bets:{status_group}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="返回首页", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bet_created_keyboard(bet_id_or_no: str, fixture_id: int | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="查看本单", callback_data=f"bet_detail:{bet_id_or_no}:pending:0")],
        [InlineKeyboardButton(text="删除本单", callback_data=f"bet_cancel:{bet_id_or_no}")],
        [InlineKeyboardButton(text="返回赛事", callback_data=f"fixture:{fixture_id}" if fixture_id else "today_featured")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bet_detail_keyboard(bet_id_or_no: str, status: str, status_group: str = "pending", page: int = 0) -> InlineKeyboardMarkup:
    rows = []
    if status == "pending":
        rows.append([InlineKeyboardButton(text="去结算", callback_data=f"bet_settle:{bet_id_or_no}")])
        rows.append([InlineKeyboardButton(text="删除本单", callback_data=f"bet_cancel:{bet_id_or_no}")])
    rows.append([InlineKeyboardButton(text="返回我的注单", callback_data=f"bets:{status_group}:{page}")])
    rows.append([InlineKeyboardButton(text="返回首页", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
def bet_detail_keyboard(
    bet_id_or_no: str,
    status: str,
    status_group: str = "pending",
    page: int = 0,
    *,
    fixture_id: int | None = None,
) -> InlineKeyboardMarkup:
    rows = []
    if status == "pending":
        rows.append([InlineKeyboardButton(text="去结算", callback_data=f"bet_settle:{bet_id_or_no}")])
        rows.append([InlineKeyboardButton(text="删除本单", callback_data=f"bet_cancel:{bet_id_or_no}")])
    if fixture_id is not None:
        rows.append([InlineKeyboardButton(text="返回赛事", callback_data=f"fixture:{fixture_id}")])
    else:
        rows.append([InlineKeyboardButton(text="返回我的注单", callback_data=f"bets:{status_group}:{page}")])
    rows.append([InlineKeyboardButton(text="返回首页", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# M11-Fix-2 override: expose stable ReplyKeyboard labels that match handlers.
def main_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎯 可投注赛事"), KeyboardButton(text="📊 我的注单")],
            [KeyboardButton(text="💰 钱包"), KeyboardButton(text="👥 推广")],
            [KeyboardButton(text="🏆 世界杯"), KeyboardButton(text="🌐 语言")],
            [KeyboardButton(text="设置"), KeyboardButton(text="帮助")],
        ],
        resize_keyboard=True,
        input_field_placeholder=t(lang, "start_title"),
    )

# M11-Fix-3 overrides: stable menu labels and draw/payout wording.
def main_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎯 可投注赛事"), KeyboardButton(text="📊 我的注单")],
            [KeyboardButton(text="💰 钱包"), KeyboardButton(text="👥 推广")],
            [KeyboardButton(text="🏆 世界杯"), KeyboardButton(text="🌐 语言")],
            [KeyboardButton(text="设置"), KeyboardButton(text="帮助")],
        ],
        resize_keyboard=True,
        input_field_placeholder=t(lang, "start_title"),
    )


def my_bets_keyboard(
    bets: list[dict] | None = None,
    status_group: str = "pending",
    page: int = 0,
    has_prev: bool = False,
    has_next: bool = False,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="待开奖", callback_data="bets:pending:0"),
            InlineKeyboardButton(text="已开奖", callback_data="bets:settled:0"),
        ]
    ]
    for bet in bets or []:
        bet_key = str(bet.get("bet_no") or bet.get("id"))
        rows.append([InlineKeyboardButton(text=f"注单 {bet_key}", callback_data=f"bet_detail:{bet_key}:{status_group}:{page}")])
    nav = []
    if has_prev:
        nav.append(InlineKeyboardButton(text="上一页", callback_data=f"bets:{status_group}:{page - 1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="下一页", callback_data=f"bets:{status_group}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="返回首页", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bet_detail_keyboard(
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
        rows.append([InlineKeyboardButton(text="删除本单", callback_data=f"bet_cancel:{bet_id_or_no}")])
    if fixture_id is not None:
        rows.append([InlineKeyboardButton(text="返回赛事", callback_data=f"fixture:{fixture_id}")])
    else:
        rows.append([InlineKeyboardButton(text="返回我的注单", callback_data=f"bets:{status_group}:{page}")])
    rows.append([InlineKeyboardButton(text="返回首页", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bet_created_keyboard(bet_id_or_no: str, fixture_id: int | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="查看开奖", callback_data=f"bet_detail:{bet_id_or_no}:pending:0")],
            [InlineKeyboardButton(text="申请退单/联系客服", callback_data=f"bet_cancel:{bet_id_or_no}")],
            [InlineKeyboardButton(text="返回赛事", callback_data=f"fixture:{fixture_id}" if fixture_id else "today_featured")],
            [InlineKeyboardButton(text="返回首页", callback_data="home")],
        ]
    )


def bet_detail_keyboard(
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
        rows.append([InlineKeyboardButton(text="申请退单/联系客服", callback_data=f"bet_cancel:{bet_id_or_no}")])
    if fixture_id is not None:
        rows.append([InlineKeyboardButton(text="返回赛事", callback_data=f"fixture:{fixture_id}")])
    else:
        rows.append([InlineKeyboardButton(text="返回我的注单", callback_data=f"bets:{status_group}:{page}")])
    rows.append([InlineKeyboardButton(text="返回首页", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
