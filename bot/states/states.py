from aiogram.fsm.state import State, StatesGroup


class IDStates(StatesGroup):
    waiting_for_forward = State()


class AddWallet(StatesGroup):
    choosing_coin = State()
    entering_address = State()
