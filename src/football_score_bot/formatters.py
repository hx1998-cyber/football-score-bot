from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from football_score_bot.betting import BettableStatus, reason_label
from football_score_bot.i18n_football import format_match_title, zh_league_name, zh_team_name
from football_score_bot.odds_normalizer import NormalizedFixtureOdds, OddsMarket, OddsOutcome
from football_score_bot.time_utils import now_hhmm


def format_featured_matches(
    fixtures: list[dict[str, Any]],
    odds_by_fixture: dict[str, dict[str, Any]] | dict[int, dict[str, Any]],
    last_update: str,
    title: str,
    empty_text: str,
    limit: int = 20,
) -> str:
    if not fixtures:
        return empty_text

    lines = [title, f"更新：{last_update}", f"显示：{min(len(fixtures), limit)} 场"]
    current_league = None
    for item in fixtures[:limit]:
        fixture_id = _fixture_id(item)
        league = item.get("league", {})
        teams = item.get("teams", {})
        league_name = zh_league_name(league.get("name")) if league.get("name") else "赛事"
        if league_name != current_league:
            lines.append(f"\n【{league_name}】")
            current_league = league_name

        kickoff = _fixture_time(item)
        home = zh_team_name(teams.get("home", {}).get("name"))
        away = zh_team_name(teams.get("away", {}).get("name"))
        odds = _odds_for(odds_by_fixture, fixture_id)
        lines.append(f"{kickoff} {format_match_title(item)}")
        lines.append(
            f"主 {_odd_value(odds, 'home_odds')} ｜ 和 {_odd_value(odds, 'draw_odds')} ｜ 客 {_odd_value(odds, 'away_odds')}"
        )
    return "\n".join(lines)


def format_bettable_matches(
    fixtures: list[dict[str, Any]],
    odds_by_fixture: dict[str, dict[str, Any]] | dict[int, dict[str, Any]],
    last_update: str,
    cutoff_minutes: int,
    limit: int = 30,
    lang: str = "zh",
) -> str:
    if not fixtures:
        if lang == "en":
            return "No bettable matches right now.\nYou can view all fixtures or try again later."
        return "当前暂无可投注赛事。\n你可以查看全部赛程或稍后再试。"

    if lang == "en":
        lines = ["🎯 Bettable Matches", f"Updated: {last_update}", f"Showing: {min(len(fixtures), limit)} matches"]
    else:
        lines = ["🎯 可投注赛事", f"更新：{last_update}", f"显示：{min(len(fixtures), limit)} 场"]
    current_day = None
    current_league = None
    for item in fixtures[:limit]:
        day_label = format_date_label(_fixture_datetime(item), lang)
        if day_label != current_day:
            lines.append(f"\n【{day_label}】")
            current_day = day_label
            current_league = None

        raw_league = (item.get("league") or {}).get("name")
        if lang == "en":
            league_name = raw_league or "League"
        else:
            league_name = zh_league_name(raw_league) if raw_league else "赛事"
        if league_name != current_league:
            lines.append(f"【{league_name}】")
            current_league = league_name

        fixture_id = _fixture_id(item)
        odds = _odds_for(odds_by_fixture, fixture_id)
        match_title = _match_title_by_lang(item, lang)
        lines.append(f"{_fixture_time(item)} {match_title}")
        labels = _odds_labels(lang)
        lines.append(
            f"{labels['home']} {_odd_value(odds, 'home_odds')} | "
            f"{labels['draw']} {_odd_value(odds, 'draw_odds')} | "
            f"{labels['away']} {_odd_value(odds, 'away_odds')}"
        )
        if lang == "en":
            lines.append(f"Bet closes: {cutoff_minutes} minutes before kickoff")
        else:
            lines.append(f"封盘：开赛前 {cutoff_minutes} 分钟")
    return "\n".join(lines)


def format_all_fixtures(
    fixtures: list[dict[str, Any]],
    last_update: str,
    title: str = "📋 全部赛程",
    empty_text: str = "今日暂无赛程。",
    limit: int = 20,
) -> str:
    if not fixtures:
        return empty_text

    lines = [title, f"更新：{last_update}", f"显示：{min(len(fixtures), limit)} 场"]
    current_league = None
    for item in fixtures[:limit]:
        league = item.get("league", {})
        teams = item.get("teams", {})
        league_name = zh_league_name(league.get("name")) if league.get("name") else "赛事"
        if league_name != current_league:
            lines.append(f"\n【{league_name}】")
            current_league = league_name
        kickoff = _fixture_time(item)
        home = zh_team_name(teams.get("home", {}).get("name"))
        away = zh_team_name(teams.get("away", {}).get("name"))
        lines.append(f"{kickoff} {format_match_title(item)}")
        lines.append("赔率：暂未开放")
    return "\n".join(lines)


def format_all_schedule(
    fixtures: list[dict[str, Any]],
    status_by_fixture: dict[int, BettableStatus],
    last_update: str,
    limit: int = 40,
) -> str:
    if not fixtures:
        return "暂无赛程。"

    lines = ["📋 全部赛程", f"更新：{last_update}", f"显示：{min(len(fixtures), limit)} 场"]
    current_day = None
    current_league = None
    for item in fixtures[:limit]:
        day_label = _fixture_day_label(item)
        if day_label != current_day:
            lines.append(f"\n【{day_label}】")
            current_day = day_label
            current_league = None

        league_name = zh_league_name((item.get("league") or {}).get("name")) if (item.get("league") or {}).get("name") else "赛事"
        if league_name != current_league:
            lines.append(f"【{league_name}】")
            current_league = league_name

        fixture_id = _fixture_id(item)
        teams = item.get("teams", {})
        goals = item.get("goals", {})
        home = zh_team_name(teams.get("home", {}).get("name"))
        away = zh_team_name(teams.get("away", {}).get("name"))
        bet_status = status_by_fixture.get(fixture_id, BettableStatus(False, "no_odds"))
        lines.append(f"{_fixture_time(item)} {format_match_title(item)}")
        if _is_finished(item):
            lines.append(f"比分：{_score_value(goals.get('home'))}-{_score_value(goals.get('away'))}")
        lines.append(f"状态：{_fixture_status_label(item)}")
        lines.append(f"投注：{reason_label(bet_status.reason)}")
    return "\n".join(lines)


def format_live_matches(
    fixtures: list[dict[str, Any]],
    odds_by_fixture: dict[str, dict[str, Any]] | dict[int, dict[str, Any]],
    last_update: str,
    title: str,
    empty_text: str,
    limit: int = 20,
) -> str:
    if not fixtures:
        return empty_text

    lines = [title, f"更新：{last_update}", f"显示：{min(len(fixtures), limit)} 场"]
    current_league = None
    for item in fixtures[:limit]:
        fixture_id = _fixture_id(item)
        league = item.get("league", {})
        teams = item.get("teams", {})
        goals = item.get("goals", {})
        status = item.get("fixture", {}).get("status", {})
        league_name = zh_league_name(league.get("name")) if league.get("name") else "赛事"
        if league_name != current_league:
            lines.append(f"\n【{league_name}】")
            current_league = league_name
        elapsed = status.get("elapsed")
        minute = f"{elapsed}'" if elapsed is not None else (status.get("short") or "-")
        home = zh_team_name(teams.get("home", {}).get("name"))
        away = zh_team_name(teams.get("away", {}).get("name"))
        odds = _odds_for(odds_by_fixture, fixture_id)
        lines.append(
            f"{minute} {home} {_score_value(goals.get('home'))}-{_score_value(goals.get('away'))} {away}"
        )
        lines.append(
            f"主 {_odd_value(odds, 'home_odds')} ｜ 和 {_odd_value(odds, 'draw_odds')} ｜ 客 {_odd_value(odds, 'away_odds')}"
        )
    return "\n".join(lines)


def format_match_detail(
    fixture: dict[str, Any],
    odds: dict[str, Any] | None,
    events: list[dict[str, Any]],
) -> str:
    league = fixture.get("league", {})
    teams = fixture.get("teams", {})
    goals = fixture.get("goals", {})
    fixture_info = fixture.get("fixture", {})
    status = fixture_info.get("status", {})
    home = zh_team_name(teams.get("home", {}).get("name"))
    away = zh_team_name(teams.get("away", {}).get("name"))
    elapsed = status.get("elapsed")
    status_text = status.get("long") or status.get("short") or "-"
    if elapsed is not None:
        status_text = f"{status_text} {elapsed}'"

    lines = [
        f"联赛：{zh_league_name(league.get('name')) if league.get('name') else '-'}",
        f"时间：{_fixture_time(fixture)}",
        f"比赛：{home} vs {away}",
        f"比分/状态：{_score_value(goals.get('home'))}-{_score_value(goals.get('away'))} / {status_text}",
        f"1X2：主 {_odd_value(odds, 'home_odds')} ｜ 和 {_odd_value(odds, 'draw_odds')} ｜ 客 {_odd_value(odds, 'away_odds')}",
    ]
    recent_events = _recent_events(events)
    if recent_events:
        lines.append("\n最近事件：")
        lines.extend(recent_events)
    return "\n".join(lines)


def format_odds_match_detail(
    fixture: dict[str, Any],
    normalized_odds: NormalizedFixtureOdds | None,
    last_update: str,
    bettable_status: BettableStatus | None = None,
    cutoff_minutes: int = 5,
    events: list[dict[str, Any]] | None = None,
    events_unavailable: bool = False,
) -> str:
    league = fixture.get("league", {})
    teams = fixture.get("teams", {})
    goals = fixture.get("goals", {})
    fixture_info = fixture.get("fixture", {})
    status = fixture_info.get("status", {})
    home = zh_team_name(teams.get("home", {}).get("name"))
    away = zh_team_name(teams.get("away", {}).get("name"))
    market = normalized_odds.markets.get("match_winner") if normalized_odds else None
    home_odds = _market_group_odds(market, "home")
    draw_odds = _market_group_odds(market, "draw")
    away_odds = _market_group_odds(market, "away")
    lines = [
        "比赛详情",
        f"【{zh_league_name(league.get('name')) if league.get('name') else '-'}】",
        f"{home} vs {away}",
        f"时间：{_fixture_month_day_time(fixture)}",
        f"状态：{_fixture_status_label(fixture)}",
        f"比分：{_score_value(goals.get('home'))}-{_score_value(goals.get('away'))}",
        "",
        "主要赔率：",
        f"主 {home_odds} ｜ 和 {draw_odds} ｜ 客 {away_odds}",
        f"封盘时间：{_cutoff_time(fixture, cutoff_minutes)}",
        f"投注状态：{reason_label(bettable_status.reason) if bettable_status else '-'}",
        f"赔率来源：{normalized_odds.bookmaker if normalized_odds else '-'}",
        f"更新：{last_update}",
        "",
        "最近事件：",
    ]
    if events_unavailable:
        lines.append("事件数据暂不可用。")
    else:
        event_lines = _recent_events(events or [])
        lines.extend(event_lines if event_lines else ["暂无关键事件。"])
    return "\n".join(lines)


def format_odds_market_page(
    fixture: dict[str, Any],
    market: OddsMarket | None,
    market_key: str,
    page: int,
    per_page: int = 20,
) -> str:
    teams = fixture.get("teams", {})
    home = zh_team_name(teams.get("home", {}).get("name"))
    away = zh_team_name(teams.get("away", {}).get("name"))
    title = _market_title(market_key)
    if not market or not market.outcomes:
        if market_key == "correct_score":
            return f"📊 波胆 / 正确比分\n{home} vs {away}\n\n该比赛暂未提供波胆赔率。"
        return f"📊 {title}\n{home} vs {away}\n\n该比赛暂未提供{title}赔率。"

    outcomes = market.outcomes[page * per_page : (page + 1) * per_page]
    lines = [f"📊 {title}", f"{home} vs {away}", f"更新：{now_hhmm()}"]
    if market_key == "correct_score":
        lines.extend(_format_correct_score(outcomes))
    elif market_key in {"over_under", "handicap", "asian_handicap", "ht_ft", "btts"}:
        lines.append("")
        lines.extend(_pair_outcomes(outcomes))
    else:
        lines.append("")
        lines.extend(f"{_display_label(outcome)} {outcome.odds}" for outcome in outcomes)
    total_pages = max((len(market.outcomes) - 1) // per_page + 1, 1)
    if total_pages > 1:
        lines.append(f"\n第 {page + 1}/{total_pages} 页")
    return "\n".join(lines)


def _format_correct_score(outcomes: list[OddsOutcome]) -> list[str]:
    labels = {"home": "主胜比分", "draw": "和局比分", "away": "客胜比分", None: "其他比分"}
    lines: list[str] = []
    for group in ("home", "draw", "away", None):
        grouped = [outcome for outcome in outcomes if outcome.group == group]
        if not grouped:
            continue
        lines.append(f"\n【{labels[group]}】")
        lines.extend(_pair_outcomes(grouped))
    return lines


def _pair_outcomes(outcomes: list[OddsOutcome]) -> list[str]:
    lines: list[str] = []
    pending: list[str] = []
    for outcome in outcomes:
        pending.append(f"{_display_label(outcome)} {outcome.odds}")
        if len(pending) == 2:
            lines.append(" ｜ ".join(pending))
            pending = []
    if pending:
        lines.append(" ｜ ".join(pending))
    return lines


def _display_label(outcome: OddsOutcome) -> str:
    label = outcome.label
    if outcome.group == "home" and label.lower() in {"home", "1"}:
        return "主胜"
    if outcome.group == "draw" and label.lower() in {"draw", "x"}:
        return "平局"
    if outcome.group == "away" and label.lower() in {"away", "2"}:
        return "客胜"
    if outcome.group == "over":
        return label.replace("Over", "大", 1)
    if outcome.group == "under":
        return label.replace("Under", "小", 1)
    return label


def _market_group_odds(market: OddsMarket | None, group: str) -> str:
    if not market:
        return "-"
    for outcome in market.outcomes:
        if outcome.group == group:
            return outcome.odds
    return "-"


def _market_title(market_key: str) -> str:
    return {
        "match_winner": "胜平负",
        "correct_score": "波胆 / 正确比分",
        "over_under": "大小球",
        "asian_handicap": "让球",
        "handicap": "让球",
        "ht_ft": "半场/全场",
        "btts": "双方进球",
    }.get(market_key, "赔率")


def format_bet_confirm(
    fixture: dict[str, Any],
    market_title: str,
    selection: str,
    odds: str,
    stake: str = "10",
) -> str:
    teams = fixture.get("teams", {})
    home = zh_team_name(teams.get("home", {}).get("name"))
    away = zh_team_name(teams.get("away", {}).get("name"))
    return "\n".join(
        [
            "🎯 确认投注",
            f"比赛：{home} vs {away}",
            f"玩法：{market_title}",
            f"选择：{selection}",
            f"赔率：{odds}",
            f"金额：${stake}",
            f"预计返还：${_potential_payout(stake, odds)}",
            "",
            "当前为模拟投注，不扣真实余额。",
        ]
    )


def format_bet_saved(bet_id: int) -> str:
    return f"模拟投注已提交。\n注单号：{bet_id}\n状态：待结算"


def format_my_bets(bets: list[dict[str, Any]], title: str = "📊 我的注单") -> str:
    if not bets:
        return f"{title}\n\n暂无注单。"

    lines = [title, "", "待结算："]
    for index, bet in enumerate(bets, start=1):
        status = "待人工结算" if bet.get("status") == "pending" else str(bet.get("status") or "-")
        lines.extend(
            [
                f"{index}. {bet.get('fixture_label') or '-'}",
                f"玩法：{bet.get('market_title') or '-'}",
                f"选择：{bet.get('selection') or '-'}",
                f"金额：${bet.get('stake') or '0'}",
                f"赔率：{bet.get('odds') or '-'}",
                f"预计返还：${bet.get('potential_payout') or '0'}",
                f"状态：{status}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def format_group_featured_live(fixtures: list[dict[str, Any]], last_update: str) -> str:
    lines = ["重点实时比分", f"更新：{last_update}"]
    for item in fixtures[:10]:
        league = item.get("league", {})
        teams = item.get("teams", {})
        goals = item.get("goals", {})
        status = item.get("fixture", {}).get("status", {})
        elapsed = status.get("elapsed")
        minute = f" {elapsed}'" if elapsed is not None else ""
        lines.append(
            "\n"
            f"【{league.get('name') or '赛事'}】\n"
            f"{teams.get('home', {}).get('name', '主队')} {_score_value(goals.get('home'))}-"
            f"{_score_value(goals.get('away'))} {teams.get('away', {}).get('name', '客队')}{minute}"
        )
    return "\n".join(lines)


def format_match_search(
    teams: list[dict[str, Any]],
    leagues: list[dict[str, Any]],
    keyword: str,
) -> str:
    if not teams and not leagues:
        return f"没有找到与「{keyword}」相关的球队或赛事。"

    lines = [f"搜索「{keyword}」结果："]
    if teams:
        lines.append("\n球队：")
        for item in teams[:8]:
            team = item.get("team", {})
            venue = item.get("venue", {})
            lines.append(
                f"- {team.get('name', '未知球队')} / {venue.get('city') or '未知城市'} / ID {team.get('id', '-')}"
            )

    if leagues:
        lines.append("\n赛事：")
        for item in leagues[:8]:
            league = item.get("league", {})
            country = item.get("country", {})
            lines.append(
                f"- {league.get('name', '未知赛事')} / {country.get('name', '未知地区')} / ID {league.get('id', '-')}"
            )

    return "\n".join(lines)


def _fixture_id(item: dict[str, Any]) -> int | None:
    try:
        return int(item.get("fixture", {}).get("id"))
    except (TypeError, ValueError):
        return None


def _fixture_time(item: dict[str, Any]) -> str:
    fixture = item.get("fixture", {})
    timestamp = fixture.get("timestamp")
    if timestamp:
        return datetime.fromtimestamp(timestamp).strftime("%H:%M")
    raw = fixture.get("date")
    if isinstance(raw, str) and "T" in raw:
        return raw.split("T", 1)[1][:5]
    return "--:--"


def _odds_for(
    odds_by_fixture: dict[str, dict[str, Any]] | dict[int, dict[str, Any]],
    fixture_id: int | None,
) -> dict[str, Any] | None:
    if fixture_id is None:
        return None
    return odds_by_fixture.get(fixture_id) or odds_by_fixture.get(str(fixture_id))


def _odd_value(odds: dict[str, Any] | None, key: str) -> str:
    value = odds.get(key) if odds else None
    return "-" if value in (None, "") else str(value)


def _score_value(value: Any) -> str:
    return "-" if value is None else str(value)


def _fixture_datetime(item: dict[str, Any]) -> datetime | None:
    fixture = item.get("fixture", {})
    timestamp = fixture.get("timestamp")
    if timestamp:
        try:
            return datetime.fromtimestamp(int(timestamp))
        except (TypeError, ValueError, OSError):
            return None
    raw = fixture.get("date")
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
        except ValueError:
            return None
    return None


def _fixture_day_label(item: dict[str, Any]) -> str:
    value = _fixture_datetime(item)
    return format_date_label(value, "zh")


def format_date_label(value: datetime | None, lang: str = "zh") -> str:
    if not value:
        return "--"
    if lang == "en":
        return value.strftime("%b %d %a")
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return f"{value:%m-%d} {weekdays[value.weekday()]}"


def _match_title_by_lang(item: dict[str, Any], lang: str = "zh") -> str:
    if lang != "en":
        return format_match_title(item)
    league_name = ((item.get("league") or {}).get("name")) or "League"
    teams = item.get("teams") or {}
    home = (teams.get("home") or {}).get("name") or "Home"
    away = (teams.get("away") or {}).get("name") or "Away"
    return f"【{league_name}】 {home} vs {away}"


def _odds_labels(lang: str = "zh") -> dict[str, str]:
    if lang == "en":
        return {"home": "Home", "draw": "Draw", "away": "Away"}
    return {"home": "主", "draw": "和", "away": "客"}


def _fixture_month_day_time(item: dict[str, Any]) -> str:
    value = _fixture_datetime(item)
    return value.strftime("%m-%d %H:%M") if value else _fixture_time(item)


def _cutoff_time(item: dict[str, Any], cutoff_minutes: int) -> str:
    value = _fixture_datetime(item)
    if not value:
        return "-"
    return (value - timedelta(minutes=cutoff_minutes)).strftime("%H:%M")


def _is_finished(item: dict[str, Any]) -> bool:
    status = str((item.get("fixture") or {}).get("status", {}).get("short") or "").upper()
    return status in {"FT", "AET", "PEN", "CANC", "PST", "SUSP", "ABD", "AWD", "WO"}


def _fixture_status_label(item: dict[str, Any]) -> str:
    status = (item.get("fixture") or {}).get("status", {})
    short = str(status.get("short") or "").upper()
    return {
        "NS": "未开赛",
        "TBD": "待定",
        "1H": "上半场",
        "2H": "下半场",
        "HT": "中场",
        "ET": "加时",
        "P": "点球",
        "FT": "已完场",
        "AET": "加时完场",
        "PEN": "点球完场",
        "CANC": "已取消",
        "PST": "已延期",
        "SUSP": "已暂停",
    }.get(short, status.get("long") or short or "-")


def _potential_payout(stake: str, odds: str) -> str:
    try:
        return f"{float(stake) * float(odds):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _recent_events(events: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    allowed = {"Goal", "Card"}
    for event in events[-8:]:
        event_type = event.get("type")
        detail = str(event.get("detail") or "")
        if event_type not in allowed:
            continue
        if event_type == "Card" and "Card" not in detail:
            continue
        team = event.get("team", {}).get("name") or "-"
        player = event.get("player", {}).get("name") or "-"
        elapsed = event.get("time", {}).get("elapsed")
        minute = f"{elapsed}'" if elapsed is not None else "-"
        icon = ""
        if "Red" in detail:
            icon = "🟥 "
        elif "Yellow" in detail:
            icon = "🟨 "
        lines.append(f"{minute} {icon}{player} {team}")
    return lines
