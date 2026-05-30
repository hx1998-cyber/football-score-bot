from __future__ import annotations

import asyncio

from football_score_bot.command_routing import (
    clean_command_token,
    command_route_name,
    parse_admin_adjust_args,
    resolve_bet_by_id_or_no,
)


class FakeBetDb:
    async def get_bet(self, bet_id: int) -> dict | None:
        if bet_id == 1:
            return {"id": 1, "bet_no": "BPR8XOZMGGNO", "status": "pending"}
        return None

    async def get_bet_by_no(self, bet_no: str) -> dict | None:
        if clean_command_token(bet_no).upper() == "BPR8XOZMGGNO":
            return {"id": 1, "bet_no": "BPR8XOZMGGNO", "status": "pending"}
        return None


async def main() -> None:
    target_user_id, amount, reason = parse_admin_adjust_args("8004679555 -5 test_deduct")
    assert target_user_id == 8004679555
    assert str(amount) == "-5"
    assert reason == "test_deduct"

    route = command_route_name("/admin_mark_deposit_paid D1 2 tx reason")
    assert route == "deposit", route
    assert route != "rebate"

    db = FakeBetDb()
    for raw in ("BPR8XOZMGGNO", "<BPR8XOZMGGNO>", "1"):
        bet = await resolve_bet_by_id_or_no(db, raw)
        assert bet and bet["id"] == 1, raw

    print("command_routing_check: ok")


if __name__ == "__main__":
    asyncio.run(main())
