from __future__ import annotations

import json
import logging
import re
from decimal import Decimal
from typing import Any

from football_score_bot.database import Database
from football_score_bot.services.wallet_service import WalletService

logger = logging.getLogger(__name__)

FINAL_STATUSES = {"FT", "AET", "PEN"}
VOID_STATUSES = {"CANC", "PST", "ABD", "SUSP"}


class SettlementService:
    def __init__(
        self,
        database: Database,
        wallet_service: WalletService,
        *,
        real_betting_enabled: bool,
    ) -> None:
        self._database = database
        self._wallet_service = wallet_service
        self._real_betting_enabled = real_betting_enabled

    async def settle_bet_from_fixture(
        self,
        bet: dict[str, Any],
        fixture: dict[str, Any] | None,
        *,
        source: str = "auto",
        admin_user_id: int = 0,
    ) -> dict[str, Any]:
        if not fixture:
            return {"settled": False, "reason": "fixture_unavailable"}
        status = str(((fixture.get("fixture") or {}).get("status") or {}).get("short") or "").upper()
        if status in VOID_STATUSES:
            result_score = _score_text(fixture)
            result = await self._settle_bet(bet, "void", source, admin_user_id, result_score, f"fixture status {status}", fixture)
            return {"settled": bool(result), "status": "void", "reason": status, "result": result}
        if status not in FINAL_STATUSES:
            return {"settled": False, "reason": "not_final", "fixture_status": status}

        score = _final_score(fixture)
        if score is None:
            return {"settled": False, "reason": "score_unavailable"}
        home_goals, away_goals = score
        outcome = evaluate_market(
            str(bet.get("market_key") or ""),
            str(bet.get("selection") or ""),
            home_goals,
            away_goals,
            home_team=str(bet.get("home_team") or ""),
            away_team=str(bet.get("away_team") or ""),
        )
        result_score = f"{home_goals}:{away_goals}"
        if outcome == "manual_required":
            await self._mark_manual_required(bet, result_score, fixture)
            return {"settled": False, "status": "manual_required", "reason": "unsupported_market"}
        result = await self._settle_bet(
            bet,
            "won" if outcome == "won" else "lost",
            source,
            admin_user_id,
            result_score,
            "auto final score settlement",
            fixture,
        )
        return {"settled": bool(result), "status": "won" if outcome == "won" else "lost", "result": result}

    async def _settle_bet(
        self,
        bet: dict[str, Any],
        outcome: str,
        source: str,
        admin_user_id: int,
        result_score: str | None,
        note: str,
        fixture: dict[str, Any],
    ) -> dict | None:
        bet_id = int(bet["id"])
        if not self._real_betting_enabled or bool(bet.get("is_simulated")):
            async with self._database.pool.acquire() as conn:
                async with conn.transaction():
                    locked = await conn.fetchrow("SELECT * FROM bets WHERE id = $1 FOR UPDATE", bet_id)
                    if not locked or locked["status"] not in {"pending", "manual_required"}:
                        return None
                    payout = Decimal(str(locked["potential_payout"] or 0)) if outcome == "won" else Decimal("0")
                    if outcome == "void":
                        payout = Decimal(str(locked["stake"] or 0))
                    row = await conn.fetchrow(
                        """
                        UPDATE bets
                        SET status = $2,
                            payout = $3,
                            result_score = $4,
                            settlement_source = $5,
                            settlement_note = $6,
                            settled_by_admin_id = NULLIF($7, 0),
                            settled_at = NOW(),
                            updated_at = NOW()
                        WHERE id = $1 AND status IN ('pending', 'manual_required')
                        RETURNING *
                        """,
                        bet_id,
                        outcome,
                        payout,
                        result_score,
                        source,
                        note,
                        admin_user_id,
                    )
                    if row:
                        await conn.execute(
                            """
                            INSERT INTO settlement_logs (
                                bet_id, fixture_id, previous_status, new_status, result_score, payout, source, raw_fixture_json
                            )
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                            """,
                            bet_id,
                            locked["fixture_id"],
                            locked["status"],
                            outcome,
                            result_score,
                            payout,
                            source,
                            json.dumps(fixture),
                        )
                    return dict(row) if row else None
        return await self._wallet_service.settle_bet(
            bet_id,
            admin_user_id,
            outcome,
            source=source,
            result_score=result_score,
            note=note,
        )

    async def _mark_manual_required(
        self,
        bet: dict[str, Any],
        result_score: str,
        fixture: dict[str, Any],
    ) -> None:
        async with self._database.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow("SELECT * FROM bets WHERE id = $1 FOR UPDATE", int(bet["id"]))
                if not row or row["status"] != "pending":
                    return
                await conn.execute(
                    """
                    UPDATE bets
                    SET status = 'manual_required',
                        result_score = $2,
                        settlement_source = 'auto',
                        settlement_note = '该玩法需要人工结算',
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                    int(bet["id"]),
                    result_score,
                )
                await conn.execute(
                    """
                    INSERT INTO settlement_logs (
                        bet_id, fixture_id, previous_status, new_status, result_score, source, raw_fixture_json
                    )
                    VALUES ($1, $2, $3, 'manual_required', $4, 'auto', $5::jsonb)
                    """,
                    int(bet["id"]),
                    row["fixture_id"],
                    row["status"],
                    result_score,
                    json.dumps(fixture),
                )


def evaluate_market(
    market_key: str,
    selection: str,
    home_goals: int,
    away_goals: int,
    *,
    home_team: str = "",
    away_team: str = "",
) -> str:
    key = market_key.lower()
    text = selection.strip().lower()
    if key == "match_winner":
        actual = "draw"
        if home_goals > away_goals:
            actual = "home"
        elif home_goals < away_goals:
            actual = "away"
        selected = None
        if text in {"home", "1", "主胜", "主勝"} or (home_team and text == home_team.lower()):
            selected = "home"
        elif text in {"draw", "x", "平局", "平"}:
            selected = "draw"
        elif text in {"away", "2", "客胜", "客勝"} or (away_team and text == away_team.lower()):
            selected = "away"
        return "won" if selected == actual else "lost" if selected else "manual_required"
    if key == "correct_score":
        match = re.search(r"(\d+)\s*[:\-]\s*(\d+)", selection)
        if not match:
            return "manual_required"
        return "won" if (int(match.group(1)), int(match.group(2))) == (home_goals, away_goals) else "lost"
    if key == "over_under":
        match = re.search(r"(over|under|大|小)\s*([0-9]+(?:\.[0-9]+)?)", text)
        if not match:
            return "manual_required"
        side = "over" if match.group(1) in {"over", "大"} else "under"
        line = Decimal(match.group(2))
        total = Decimal(home_goals + away_goals)
        if total == line:
            return "manual_required"
        return "won" if (side == "over" and total > line) or (side == "under" and total < line) else "lost"
    if key == "btts":
        yes = text in {"yes", "是", "双方进球", "雙方進球"}
        no = text in {"no", "否"}
        if not yes and not no:
            return "manual_required"
        actual_yes = home_goals > 0 and away_goals > 0
        return "won" if yes == actual_yes else "lost"
    return "manual_required"


def _final_score(fixture: dict[str, Any]) -> tuple[int, int] | None:
    score = fixture.get("score") or {}
    fulltime = score.get("fulltime") or {}
    home = fulltime.get("home")
    away = fulltime.get("away")
    if home is None or away is None:
        goals = fixture.get("goals") or {}
        home = goals.get("home")
        away = goals.get("away")
    if home is None or away is None:
        return None
    return int(home), int(away)


def _score_text(fixture: dict[str, Any]) -> str | None:
    score = _final_score(fixture)
    return f"{score[0]}:{score[1]}" if score else None
