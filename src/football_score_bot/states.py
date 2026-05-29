from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class RechargeStates(StatesGroup):
    choosing_amount = State()
    waiting_custom_amount = State()
    confirming_recharge = State()


class BetStates(StatesGroup):
    waiting_custom_stake = State()
    confirming_bet = State()


class WithdrawStates(StatesGroup):
    waiting_amount = State()
    waiting_network = State()
    waiting_address = State()
    confirming_withdraw = State()


class RebateStates(StatesGroup):
    waiting_note = State()
    confirming_request = State()


class AgentApplicationStates(StatesGroup):
    waiting_note = State()
    confirming_application = State()


class AdminAdjustStates(StatesGroup):
    waiting_user = State()
    waiting_amount = State()
    waiting_reason = State()
    confirming_adjustment = State()
