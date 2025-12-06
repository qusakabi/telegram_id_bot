from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton


def get_crypto_main_keyboard():
    """Главное меню крипто-бота"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить кошелек"), KeyboardButton(text="💰 Баланс")],
            [KeyboardButton(text="📊 Статус"), KeyboardButton(text="🗑 Удалить кошелек")],
            [KeyboardButton(text="◀️ Главное меню")]
        ],
        resize_keyboard=True
    )
    return keyboard


def get_coin_keyboard():
    """Клавиатура выбора монеты"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 TON", callback_data="coin_TON")],
            [InlineKeyboardButton(text="₿ Bitcoin", callback_data="coin_BTC")],
            [InlineKeyboardButton(text="Ξ Ethereum", callback_data="coin_ETH")],
            [InlineKeyboardButton(text="💵 USDT (ERC-20)", callback_data="coin_USDT")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="coin_back")]
        ]
    )
    return keyboard
