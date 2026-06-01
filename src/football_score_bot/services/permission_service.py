from __future__ import annotations

from football_score_bot.config import Settings
from football_score_bot.database import Database

Role = str


class PermissionService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self._database = database
        self._settings = settings

    async def get_user_role(self, user_id: int | None) -> Role:
        if not user_id:
            return "user"
        if user_id in self._settings.super_admin_user_ids:
            return "super_admin"
        if user_id in self._settings.admin_user_ids:
            return "admin"
        if user_id in self._settings.agent_user_ids:
            return "agent"
        row = await self._database.get_user_role_row(user_id)
        if not row:
            row = await self._database.pool.fetchrow(
                "SELECT role FROM admin_profiles WHERE user_id = $1",
                user_id,
            )
        if not row:
            return "user"
        role = str(row.get("role") or "user")
        if role in {"super_admin", "admin", "agent"}:
            return role
        return "user"

    async def is_super_admin(self, user_id: int | None) -> bool:
        return await self.get_user_role(user_id) == "super_admin"

    async def is_admin(self, user_id: int | None) -> bool:
        return await self.get_user_role(user_id) in {"super_admin", "admin"}

    async def is_agent(self, user_id: int | None) -> bool:
        return await self.get_user_role(user_id) in {"super_admin", "admin", "agent"}

    async def can_manage_user(self, operator_id: int | None, target_user_id: int) -> bool:
        role = await self.get_user_role(operator_id)
        if role == "super_admin":
            return True
        if not operator_id:
            return False
        if role in {"admin", "agent"}:
            parent = await self._database.pool.fetchval(
                "SELECT parent_user_id FROM referral_relations WHERE user_id = $1",
                target_user_id,
            )
            return int(parent or 0) == operator_id
        return operator_id == target_user_id

    async def can_settle_bets(self, operator_id: int | None) -> bool:
        return await self.is_super_admin(operator_id)

    async def can_review_withdrawals(self, operator_id: int | None) -> bool:
        return await self.is_super_admin(operator_id)

    async def can_review_deposits(self, operator_id: int | None) -> bool:
        return await self.is_super_admin(operator_id)

    async def can_manage_rebates(self, operator_id: int | None) -> bool:
        return await self.get_user_role(operator_id) in {"super_admin", "admin", "agent"}

    async def can_modify_odds(self, operator_id: int | None) -> bool:
        return await self.is_super_admin(operator_id)

    async def can_invite_admin(self, operator_id: int | None) -> bool:
        return await self.is_super_admin(operator_id)

    async def can_reopen_settled_bet(self, operator_id: int | None) -> bool:
        return await self.is_super_admin(operator_id)

    async def can_manage_money(self, operator_id: int | None) -> bool:
        return await self.is_super_admin(operator_id)

    async def can_review_cancel_requests(self, operator_id: int | None) -> bool:
        return await self.is_super_admin(operator_id)
