import sys
sys.path.append('/app')

from aiogram import types, F
from aiogram.fsm.context import FSMContext
from datetime import datetime

from bot.keyboards.crypto import get_crypto_main_keyboard, get_coin_keyboard
from bot.keyboards.base import get_main_menu
from bot.states.states import AddWallet
from bot.services.crypto_service import (
    load_wallets, save_wallets, get_ton_balance, get_btc_balance,
    get_eth_balance, get_usdt_balance, last_transactions
)
from bot.handlers.base import send_welcome


async def crypto_monitoring_start(message: types.Message):
    """Начало режима мониторинга кошельков"""
    msg = "💰 <b>Crypto Monitor Bot</b>\n\n"
    msg += "🔍 Я помогу вам отслеживать транзакции на ваших криптокошельках\n\n"
    msg += "📊 Поддерживаемые монеты:\n"
    msg += "• TON\n• Bitcoin\n• Ethereum\n• USDT (ERC-20)\n\n"
    msg += "Используйте меню ниже 👇"

    await message.answer(msg, parse_mode='HTML', reply_markup=get_crypto_main_keyboard())


async def add_wallet_start(message: types.Message, state: FSMContext):
    """Начало добавления кошелька"""
    await message.answer(
        "Выберите криптовалюту:",
        reply_markup=get_coin_keyboard()
    )
    await state.set_state(AddWallet.choosing_coin)


async def coin_selected(callback: types.CallbackQuery, state: FSMContext):
    """Выбор монеты"""
    await callback.answer()

    coin = callback.data.split("_")[1]

    if coin == "back":
        await callback.message.delete()
        await state.clear()
        return

    await state.update_data(coin=coin)

    coin_names = {
        "TON": "TON (The Open Network)",
        "BTC": "Bitcoin",
        "ETH": "Ethereum",
        "USDT": "USDT (ERC-20)"
    }

    await callback.message.edit_text(
        f"💎 Вы выбрали: <b>{coin_names[coin]}</b>\n\n"
        f"Отправьте адрес кошелька:",
        parse_mode='HTML'
    )
    await state.set_state(AddWallet.entering_address)


async def wallet_address_entered(message: types.Message, state: FSMContext):
    """Адрес кошелька введен"""
    address = message.text.strip()
    data = await state.get_data()
    coin = data['coin']

    # Загружаем кошельки
    wallets = load_wallets()
    chat_id = str(message.chat.id)

    if chat_id not in wallets:
        wallets[chat_id] = []

    # Проверяем, не добавлен ли уже этот кошелек
    for wallet in wallets[chat_id]:
        if wallet['address'] == address and wallet['coin'] == coin:
            await message.answer(
                "⚠️ Этот кошелек уже добавлен!",
                reply_markup=get_crypto_main_keyboard()
            )
            await state.clear()
            return

    # Добавляем новый кошелек
    wallets[chat_id].append({
        'coin': coin,
        'address': address,
        'added_at': datetime.now().isoformat()
    })

    save_wallets(wallets)

    coin_emoji = {"TON": "💎", "BTC": "₿", "ETH": "Ξ", "USDT": "💵"}

    await message.answer(
        f"✅ Кошелек добавлен!\n\n"
        f"{coin_emoji[coin]} <b>{coin}</b>\n"
        f"📝 <code>{address}</code>\n\n"
        f"Мониторинг запущен!",
        parse_mode='HTML',
        reply_markup=get_crypto_main_keyboard()
    )

    await state.clear()


async def show_balances(message: types.Message):
    """Показать балансы всех кошельков"""
    wallets = load_wallets()
    chat_id = str(message.chat.id)

    if chat_id not in wallets or not wallets[chat_id]:
        await message.answer(
            "У вас нет добавленных кошельков\n\n"
            "Используйте кнопку <b>➕ Добавить кошелек</b>",
            parse_mode='HTML'
        )
        return

    msg = "💰 <b>Балансы ваших кошельков:</b>\n\n"

    for wallet in wallets[chat_id]:
        coin = wallet['coin']
        address = wallet['address']

        balance = None

        if coin == "TON":
            balance = await get_ton_balance(address)
            symbol = "TON"
        elif coin == "BTC":
            balance = await get_btc_balance(address)
            symbol = "BTC"
        elif coin == "ETH":
            balance = await get_eth_balance(address)
            symbol = "ETH"
        elif coin == "USDT":
            balance = await get_usdt_balance(address)
            symbol = "USDT"

        coin_emoji = {"TON": "💎", "BTC": "₿", "ETH": "Ξ", "USDT": "💵"}

        msg += f"{coin_emoji[coin]} <b>{coin}</b>\n"
        msg += f"<code>{address[:12]}...{address[-8:]}</code>\n"

        if balance is not None:
            if coin == "BTC":
                msg += f"💵 {balance:.8f} {symbol}\n\n"
            elif coin == "USDT":
                msg += f"💵 {balance:.2f} {symbol}\n\n"
            else:
                msg += f"💵 {balance:.4f} {symbol}\n\n"
        else:
            msg += f"⚠️ Ошибка получения баланса\n\n"

    await message.answer(msg, parse_mode='HTML')


async def show_status(message: types.Message):
    """Показать статус отслеживаемых кошельков"""
    wallets = load_wallets()
    chat_id = str(message.chat.id)

    if chat_id not in wallets or not wallets[chat_id]:
        await message.answer(
            "У вас нет добавленных кошельков\n\n"
            "Используйте кнопку <b>➕ Добавить кошелек</b>",
            parse_mode='HTML'
        )
        return

    msg = "📊 <b>Статус мониторинга:</b>\n\n"
    msg += f"👀 Отслеживается кошельков: <b>{len(wallets[chat_id])}</b>\n\n"

    for i, wallet in enumerate(wallets[chat_id], 1):
        coin = wallet['coin']
        address = wallet['address']
        added_at = datetime.fromisoformat(wallet['added_at'])

        coin_emoji = {"TON": "💎", "BTC": "₿", "ETH": "Ξ", "USDT": "💵"}

        msg += f"{i}. {coin_emoji[coin]} <b>{coin}</b>\n"
        msg += f"   📝 <code>{address[:12]}...{address[-8:]}</code>\n"
        msg += f"   📅 Добавлен: {added_at.strftime('%Y-%m-%d %H:%M')}\n"
        msg += f"   ✅ Мониторинг активен\n\n"

    await message.answer(msg, parse_mode='HTML')


async def delete_wallet_menu(message: types.Message):
    """Меню удаления кошелька"""
    wallets = load_wallets()
    chat_id = str(message.chat.id)

    if chat_id not in wallets or not wallets[chat_id]:
        await message.answer(
            "У вас нет добавленных кошельков",
            parse_mode='HTML'
        )
        return

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = []

    for i, wallet in enumerate(wallets[chat_id]):
        coin = wallet['coin']
        address = wallet['address']
        coin_emoji = {"TON": "💎", "BTC": "₿", "ETH": "Ξ", "USDT": "💵"}

        button_text = f"{coin_emoji[coin]} {coin}: {address[:8]}...{address[-6:]}"
        keyboard.append([InlineKeyboardButton(
            text=button_text,
            callback_data=f"delete_{i}"
        )])

    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="delete_back")])

    await message.answer(
        "Выберите кошелек для удаления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


async def delete_wallet_confirm(callback: types.CallbackQuery):
    """Удаление кошелька"""
    await callback.answer()

    action = callback.data.split("_")[1]

    if action == "back":
        await callback.message.delete()
        return

    wallet_index = int(action)
    wallets = load_wallets()
    chat_id = str(callback.message.chat.id)

    if chat_id in wallets and wallet_index < len(wallets[chat_id]):
        deleted_wallet = wallets[chat_id].pop(wallet_index)

        if not wallets[chat_id]:
            del wallets[chat_id]

        save_wallets(wallets)

        # Удаляем из кэша последних транзакций
        wallet_key = f"{chat_id}_{deleted_wallet['coin']}_{deleted_wallet['address']}"
        if wallet_key in last_transactions:
            del last_transactions[wallet_key]

        coin_emoji = {"TON": "💎", "BTC": "₿", "ETH": "Ξ", "USDT": "💵"}

        await callback.message.edit_text(
            f"✅ Кошелек удален!\n\n"
            f"{coin_emoji[deleted_wallet['coin']]} <b>{deleted_wallet['coin']}</b>\n"
            f"<code>{deleted_wallet['address']}</code>",
            parse_mode='HTML'
        )
    else:
        await callback.message.edit_text("❌ Ошибка удаления кошелька")


async def back_to_main_menu(message: types.Message):
    """Возврат в главное меню"""
    await send_welcome(message)
