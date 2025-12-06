from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def get_main_menu():
    keyboard = [
        [KeyboardButton(text="📝 Process Text")],
        [KeyboardButton(text="🆔 Get ID"), KeyboardButton(text="❓ Help")],
        [KeyboardButton(text="💰 Мониторинг кошельков")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_text_menu():
    keyboard = [
        [KeyboardButton(text="🧹 Smart Clean")],
        [KeyboardButton(text="🔄 Dedup")],
        [KeyboardButton(text="◀️ Back")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
