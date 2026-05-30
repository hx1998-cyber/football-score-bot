from __future__ import annotations

from decimal import Decimal
from typing import Any


INVALID_BET_LOOKUPS = {"bet_id", "bet_no", "注单号或ID", "freeze_id"}


def clean_command_token(value: str) -> str:
    token = " ".join(str(value or "").strip().split())
    if token.startswith("<") and token.endswith(">") and len(token) >= 2:
        token = token[1:-1].strip()
    return token


def parse_command_name(text: str | None) -> str | None:
    if not text:
        return None
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    command = stripped.split(maxsplit=1)[0][1:]
    return command.split("@", 1)[0].lower() or None


def command_route_name(text: str | None) -> str | None:
    command = parse_command_name(text)
    if command == "admin_mark_deposit_paid":
        return "deposit"
    if command and command.startswith("admin_rebate"):
        return "rebate"
    return command


def parse_admin_adjust_args(args: str | None) -> tuple[int, Decimal, str]:
    parts = (args or "").strip().split(maxsplit=2)
    if len(parts) != 3:
        raise ValueError("usage")
    try:
        target_user_id = int(clean_command_token(parts[0]))
        amount = Decimal(parts[1])
    except Exception as exc:
        raise ValueError("invalid_args") from exc
    reason = parts[2].strip()
    if not reason:
        raise ValueError("usage")
    return target_user_id, amount, reason


async def resolve_bet_by_id_or_no(db: Any, raw: str) -> dict | None:
    token = clean_command_token(raw)
    if not token or token in INVALID_BET_LOOKUPS:
        raise ValueError("注单号或ID无效。")
    if token.isdigit():
        bet = await db.get_bet(int(token))
        if bet:
            return bet
        return await db.get_bet_by_no(token)
    return await db.get_bet_by_no(token)
