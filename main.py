import asyncio
import logging
import os
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from dotenv import load_dotenv
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from prometheus_client import Gauge, Counter, Histogram, start_http_server
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ContentType, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, \
    FSInputFile
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from collections import defaultdict

# Configuration import
from config import Config

# Imports for text file processing
try:
    from processors import process_clean, process_dedup, process_smart_clean

    TEXT_PROCESSING_AVAILABLE = True
except ImportError:
    TEXT_PROCESSING_AVAILABLE = False
    print("⚠️ Processor modules not found. Text file processing is unavailable.")

# Load environment variables
load_dotenv()

# Logging setup
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format=Config.LOG_FORMAT
)
logger = logging.getLogger(__name__)

# Create directories
os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)

# File handler for logging
file_handler = logging.FileHandler(f"{Config.LOGS_DIR}/bot_{datetime.now().strftime('%Y-%m-%d')}.log")
file_handler.setFormatter(logging.Formatter(Config.LOG_FORMAT))
logger.addHandler(file_handler)

# Bot initialization
if not Config.BOT_TOKEN:
    Config.BOT_TOKEN = input("Enter your bot token: ")

bot = Bot(token=Config.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


# FSM states
class IDStates(StatesGroup):
    waiting_for_forward = State()


class AddWallet(StatesGroup):
    choosing_coin = State()
    entering_address = State()


# Global variables
user_states: Dict[int, Dict[str, Any]] = {}
user_stats: Dict[int, Dict[str, int]] = defaultdict(lambda: {"texts": 0, "errors": 0})
bot_stats = {"total_texts": 0, "total_users": 0, "start_time": datetime.now().isoformat()}

# Prometheus metrics
total_users_gauge = Gauge('telegram_bot_total_users', 'Total number of users')
total_texts_gauge = Gauge('telegram_bot_total_texts', 'Total number of texts processed')
total_errors_gauge = Gauge('telegram_bot_total_errors', 'Total number of errors')

# Counters
command_starts = Counter('telegram_bot_command_starts_total', 'Total /start commands')
messages_received = Counter('telegram_bot_messages_received_total', 'Total messages received from users')
bot_errors_sent = Counter('telegram_bot_bot_errors_sent_total', 'Total error messages sent by bot')

# Histograms
file_processing_time = Histogram('telegram_bot_file_processing_seconds', 'Time spent processing files')

# Counters for successful operations
successful_operations = Counter('telegram_bot_successful_operations_total', 'Total successful operations')

# Crypto monitoring globals
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TONAPI_TOKEN = os.getenv('TONAPI_TOKEN')
ETHERSCAN_TOKEN = os.getenv('ETHERSCAN_TOKEN')

# File for storing wallets
WALLETS_FILE = 'wallets.json'

# Storage for last transactions
last_transactions = {}

def update_metrics():
    total_users = len(user_stats)
    total_texts = sum(stats.get('texts', 0) for stats in user_stats.values())
    total_errors = sum(stats.get('errors', 0) for stats in user_stats.values())
    total_users_gauge.set(total_users)
    total_texts_gauge.set(total_texts)
    total_errors_gauge.set(total_errors)

# Load statistics
def load_stats():
    try:
        if os.path.exists(Config.STATS_FILE):
            with open(Config.STATS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                global user_stats, bot_stats
                user_stats = defaultdict(lambda: {"texts": 0, "errors": 0}, data.get("user_stats", {}))
                bot_stats = data.get("bot_stats", bot_stats)
        update_metrics()
    except Exception as e:
        logger.error(f"Failed to load statistics: {e}")


# Save statistics
def save_stats():
    try:
        with open(Config.STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                "user_stats": dict(user_stats),
                "bot_stats": bot_stats
            }, f, ensure_ascii=False, indent=2)
        update_metrics()
    except Exception as e:
        logger.error(f"Failed to save statistics: {e}")


# Crypto functions
def load_wallets():
    """Загрузка кошельков из файла"""
    if os.path.exists(WALLETS_FILE):
        with open(WALLETS_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_wallets(wallets):
    """Сохранение кошельков в файл"""
    with open(WALLETS_FILE, 'w') as f:
        json.dump(wallets, f, indent=2)


async def get_ton_balance(address):
    """Получение баланса TON"""
    url = f"https://tonapi.io/v2/accounts/{address}"
    headers = {"Authorization": f"Bearer {TONAPI_TOKEN}"}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                balance = int(data.get('balance', 0)) / 1e9
                return balance
            return None


async def get_btc_balance(address):
    """Получение баланса Bitcoin через blockchain.info API"""
    url = f"https://blockchain.info/q/addressbalance/{address}"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    balance_satoshi = await response.text()
                    balance = int(balance_satoshi) / 1e8  # Конвертация из satoshi в BTC
                    return balance
        except:
            pass
    return None


async def get_eth_balance(address):
    """Получение баланса Ethereum"""
    url = f"https://api.etherscan.io/api"
    params = {
        "module": "account",
        "action": "balance",
        "address": address,
        "tag": "latest",
        "apikey": ETHERSCAN_TOKEN
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                if data.get('status') == '1':
                    balance = int(data.get('result', 0)) / 1e18
                    return balance
    return None


async def get_usdt_balance(address):
    """Получение баланса USDT (ERC-20)"""
    # USDT Contract Address на Ethereum
    usdt_contract = "0xdac17f958d2ee523a2206206994597c13d831ec7"

    url = f"https://api.etherscan.io/api"
    params = {
        "module": "account",
        "action": "tokenbalance",
        "contractaddress": usdt_contract,
        "address": address,
        "tag": "latest",
        "apikey": ETHERSCAN_TOKEN
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                if data.get('status') == '1':
                    balance = int(data.get('result', 0)) / 1e6  # USDT имеет 6 decimals
                    return balance
    return None


async def get_ton_transactions(address):
    """Получение последних транзакций TON"""
    url = f"https://tonapi.io/v2/accounts/{address}/events"
    headers = {"Authorization": f"Bearer {TONAPI_TOKEN}"}
    params = {"limit": 5}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as response:
            if response.status == 200:
                data = await response.json()
                return data.get('events', [])
    return []


async def get_btc_transactions(address):
    """Получение последних транзакций Bitcoin"""
    url = f"https://blockchain.info/rawaddr/{address}?limit=5"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('txs', [])
        except:
            pass
    return []


async def get_eth_transactions(address):
    """Получение последних транзакций Ethereum"""
    url = f"https://api.etherscan.io/api"
    params = {
        "module": "account",
        "action": "txlist",
        "address": address,
        "startblock": 0,
        "endblock": 99999999,
        "page": 1,
        "offset": 5,
        "sort": "desc",
        "apikey": ETHERSCAN_TOKEN
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                if data.get('status') == '1':
                    return data.get('result', [])
    return []


async def get_usdt_transactions(address):
    """Получение последних транзакций USDT"""
    usdt_contract = "0xdac17f958d2ee523a2206206994597c13d831ec7"

    url = f"https://api.etherscan.io/api"
    params = {
        "module": "account",
        "action": "tokentx",
        "contractaddress": usdt_contract,
        "address": address,
        "page": 1,
        "offset": 5,
        "sort": "desc",
        "apikey": ETHERSCAN_TOKEN
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                if data.get('status') == '1':
                    return data.get('result', [])
    return []


async def format_ton_transaction(event, wallet_address):
    """Форматирование транзакции TON"""
    actions = event.get('actions', [])
    if not actions:
        return None

    action = actions[0]
    action_type = action.get('type', 'unknown')

    timestamp = datetime.fromtimestamp(event.get('timestamp', 0))
    msg = f"🔔 <b>TON - Новая транзакция!</b>\n\n"
    msg += f"📅 {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"

    if action_type == 'TonTransfer':
        ton_transfer = action.get('TonTransfer', {})
        amount = int(ton_transfer.get('amount', 0)) / 1e9
        sender = ton_transfer.get('sender', {}).get('address', 'Unknown')
        recipient = ton_transfer.get('recipient', {}).get('address', 'Unknown')

        if recipient == wallet_address:
            msg += f"📥 <b>Входящий: +{amount:.4f} TON</b>\n"
            msg += f"От: <code>{sender[:8]}...{sender[-8:]}</code>\n"
        else:
            msg += f"📤 <b>Исходящий: -{amount:.4f} TON</b>\n"
            msg += f"Кому: <code>{recipient[:8]}...{recipient[-8:]}</code>\n"

    return msg


async def format_btc_transaction(tx, wallet_address):
    """Форматирование транзакции Bitcoin"""
    timestamp = datetime.fromtimestamp(tx.get('time', 0))
    msg = f"🔔 <b>BTC - Новая транзакция!</b>\n\n"
    msg += f"📅 {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"

    # Определяем направление транзакции
    inputs = tx.get('inputs', [])
    outputs = tx.get('out', [])

    is_incoming = False
    amount = 0

    for output in outputs:
        if output.get('addr') == wallet_address:
            is_incoming = True
            amount += output.get('value', 0)

    amount_btc = amount / 1e8

    if is_incoming:
        msg += f"📥 <b>Входящий: +{amount_btc:.8f} BTC</b>\n"
    else:
        msg += f"📤 <b>Исходящий: -{amount_btc:.8f} BTC</b>\n"

    tx_hash = tx.get('hash', '')
    msg += f"🔗 <code>{tx_hash[:16]}...</code>\n"

    return msg


async def format_eth_transaction(tx, wallet_address):
    """Форматирование транзакции Ethereum"""
    timestamp = datetime.fromtimestamp(int(tx.get('timeStamp', 0)))
    msg = f"🔔 <b>ETH - Новая транзакция!</b>\n\n"
    msg += f"📅 {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"

    amount = int(tx.get('value', 0)) / 1e18
    from_addr = tx.get('from', '').lower()
    to_addr = tx.get('to', '').lower()

    if to_addr == wallet_address.lower():
        msg += f"📥 <b>Входящий: +{amount:.6f} ETH</b>\n"
        msg += f"От: <code>{from_addr[:8]}...{from_addr[-8:]}</code>\n"
    else:
        msg += f"📤 <b>Исходящий: -{amount:.6f} ETH</b>\n"
        msg += f"Кому: <code>{to_addr[:8]}...{to_addr[-8:]}</code>\n"

    return msg


async def format_usdt_transaction(tx, wallet_address):
    """Форматирование транзакции USDT"""
    timestamp = datetime.fromtimestamp(int(tx.get('timeStamp', 0)))
    msg = f"🔔 <b>USDT - Новая транзакция!</b>\n\n"
    msg += f"📅 {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"

    amount = int(tx.get('value', 0)) / 1e6
    from_addr = tx.get('from', '').lower()
    to_addr = tx.get('to', '').lower()

    if to_addr == wallet_address.lower():
        msg += f"📥 <b>Входящий: +{amount:.2f} USDT</b>\n"
        msg += f"От: <code>{from_addr[:8]}...{from_addr[-8:]}</code>\n"
    else:
        msg += f"📤 <b>Исходящий: -{amount:.2f} USDT</b>\n"
        msg += f"Кому: <code>{to_addr[:8]}...{to_addr[-8:]}</code>\n"

    return msg


async def check_wallet_transactions(chat_id, wallet_address, coin):
    """Проверка новых транзакций для кошелька"""
    wallet_key = f"{chat_id}_{coin}_{wallet_address}"

    try:
        if coin == "TON":
            transactions = await get_ton_transactions(wallet_address)
            if transactions:
                latest_tx_id = transactions[0].get('event_id')

                if wallet_key not in last_transactions:
                    last_transactions[wallet_key] = latest_tx_id
                    return

                if last_transactions[wallet_key] != latest_tx_id:
                    # Есть новые транзакции
                    new_txs = []
                    for tx in transactions:
                        if tx.get('event_id') == last_transactions[wallet_key]:
                            break
                        new_txs.append(tx)

                    for tx in reversed(new_txs):
                        msg = await format_ton_transaction(tx, wallet_address)
                        if msg:
                            await bot.send_message(chat_id, msg, parse_mode='HTML')

                    last_transactions[wallet_key] = latest_tx_id

        elif coin == "BTC":
            transactions = await get_btc_transactions(wallet_address)
            if transactions:
                latest_tx_hash = transactions[0].get('hash')

                if wallet_key not in last_transactions:
                    last_transactions[wallet_key] = latest_tx_hash
                    return

                if last_transactions[wallet_key] != latest_tx_hash:
                    new_txs = []
                    for tx in transactions:
                        if tx.get('hash') == last_transactions[wallet_key]:
                            break
                        new_txs.append(tx)

                    for tx in reversed(new_txs):
                        msg = await format_btc_transaction(tx, wallet_address)
                        if msg:
                            await bot.send_message(chat_id, msg, parse_mode='HTML')

                    last_transactions[wallet_key] = latest_tx_hash

        elif coin == "ETH":
            transactions = await get_eth_transactions(wallet_address)
            if transactions:
                latest_tx_hash = transactions[0].get('hash')

                if wallet_key not in last_transactions:
                    last_transactions[wallet_key] = latest_tx_hash
                    return

                if last_transactions[wallet_key] != latest_tx_hash:
                    new_txs = []
                    for tx in transactions:
                        if tx.get('hash') == last_transactions[wallet_key]:
                            break
                        new_txs.append(tx)

                    for tx in reversed(new_txs):
                        msg = await format_eth_transaction(tx, wallet_address)
                        if msg:
                            await bot.send_message(chat_id, msg, parse_mode='HTML')

                    last_transactions[wallet_key] = latest_tx_hash

        elif coin == "USDT":
            transactions = await get_usdt_transactions(wallet_address)
            if transactions:
                latest_tx_hash = transactions[0].get('hash')

                if wallet_key not in last_transactions:
                    last_transactions[wallet_key] = latest_tx_hash
                    return

                if last_transactions[wallet_key] != latest_tx_hash:
                    new_txs = []
                    for tx in transactions:
                        if tx.get('hash') == last_transactions[wallet_key]:
                            break
                        new_txs.append(tx)

                    for tx in reversed(new_txs):
                        msg = await format_usdt_transaction(tx, wallet_address)
                        if msg:
                            await bot.send_message(chat_id, msg, parse_mode='HTML')

                    last_transactions[wallet_key] = latest_tx_hash

    except Exception as e:
        print(f"Ошибка проверки транзакций {coin} {wallet_address}: {e}")


async def monitor_all_wallets():
    """Мониторинг всех кошельков"""
    while True:
        try:
            wallets = load_wallets()

            for chat_id, user_wallets in wallets.items():
                for wallet in user_wallets:
                    await check_wallet_transactions(
                        int(chat_id),
                        wallet['address'],
                        wallet['coin']
                    )

            await asyncio.sleep(30)  # Проверка каждые 30 секунд

        except Exception as e:
            print(f"Ошибка мониторинга: {e}")
            await asyncio.sleep(30)


# Keyboards
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


# Command handlers

@dp.message(F.text == '/start')
async def send_welcome(message: types.Message):
    messages_received.inc()
    command_starts.inc()
    user_id = message.from_user.id
    user_states[user_id] = {'mode': None}

    # Update statistics
    if user_id not in user_stats:
        bot_stats["total_users"] += 1

    welcome_text = (
        f"🤖 *Universal Bot* 🤖\n\n"
        f"Hi, {message.from_user.first_name}! I can:\n\n"
        f"📝 *Process text files* (clean/dedup)\n"
        f"🆔 *Show IDs* (by username, forwarded message, sticker)\n\n"
        f"Choose a function from the menu below:"
    )

    await message.answer(welcome_text, parse_mode="Markdown", reply_markup=get_main_menu())


@dp.message(F.command == "help")
async def send_help(message: types.Message):
    messages_received.inc()
    help_text = (
        "📋 *Bot Help*\n\n"
        "📝 *Text Processing:*\n"
        "• Clean: clean and format text\n"
        "• Smart Clean: smart domain grouping with counts\n"
        "• Dedup: remove duplicate lines\n"
        "• Only .txt files are supported\n\n"
        "🆔 *ID Tools:*\n"
        "• '🆔 Get ID' button — menu with different methods:\n"
        "  ├ *My ID* — your User ID and Chat ID\n"
        "  └ *From Forward* — forward a message to get the author's ID\n"
        "• Commands: `/chatid`, `/userid` (or `/id`)\n"
        "• Send a sticker — the bot will return its Sticker ID\n\n"
        "🔄 Use the main menu to switch modes"
    )
    await message.reply(help_text, parse_mode="Markdown")


@dp.message(F.command == "stats")
async def show_stats(message: types.Message):
    await message.reply("Statistics are disabled.", parse_mode="Markdown")


# ===== Identifiers (Chat ID / User ID) and Stickers =====

@dp.message(F.command == "chatid")
async def chatid_handler(message: types.Message):
    messages_received.inc()
    await message.reply(f"Chat ID: {message.chat.id}")


@dp.message(F.command == "userid")
@dp.message(F.command == "id")
async def userid_handler(message: types.Message):
    """
    Sends user ID.
    If the command is a reply to a message — returns the original author's ID.
    Otherwise, returns your own ID.
    """
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    await message.reply(f"User ID: {target.id}")


@dp.message(F.content_type == ContentType.STICKER)
async def sticker_handler(message: types.Message):
    """Sends sticker file_id"""
    sticker_id = message.sticker.file_id
    await message.reply(f"Sticker ID: {sticker_id}")


# Menu button handlers

@dp.message(F.text == "📝 Process Text")
async def set_text_mode(message: types.Message):
    user_id = message.from_user.id

    if not TEXT_PROCESSING_AVAILABLE:
        await message.reply("❌ Text file processing is unavailable. Modules are not installed.")
        return

    user_states[user_id] = {'mode': 'text'}

    text_text = (
        "📝 *Text processing mode activated*\n\n"
        "🧹 *Clean:* clean and format text\n"
        "🧹 *Smart Clean:* smart domain grouping with counts\n"
        "🔄 *Dedup:* remove duplicate lines\n\n"
        "Choose an operation:"
    )

    await message.reply(text_text, parse_mode="Markdown", reply_markup=get_text_menu())


@dp.message(F.text == "🆔 Get ID")
async def id_menu_handler(message: types.Message):
    """Displays ID retrieval menu"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 My ID", callback_data="get_my_id")],
        [InlineKeyboardButton(text="📨 From Forward", callback_data="get_by_forward")]
    ])

    text = (
        "🆔 *Get ID*\n\n"
        "Choose a method:\n"
        "• *My ID* — show your User ID and Chat ID\n"
        "• *From Forward* — forward a message to get the sender's ID"
    )
    await message.reply(text, parse_mode="Markdown", reply_markup=keyboard)


# Callback handlers for ID menu
@dp.callback_query(F.data == "get_my_id")
async def callback_get_my_id(callback: types.CallbackQuery):
    """Shows user ID"""
    uid = callback.from_user.id
    cid = callback.message.chat.id
    text = (
        f"🆔 *Your IDs:*\n\n"
        f"👤 User ID: `{uid}`\n"
        f"💬 Chat ID: `{cid}`\n\n"
        f"_Tip: Tap the ID to copy_"
    )
    await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer("✅ ID retrieved")


@dp.callback_query(F.data == "get_by_forward")
async def callback_get_by_forward(callback: types.CallbackQuery, state: FSMContext):
    """Activates ID retrieval from forwarded message"""
    await state.set_state(IDStates.waiting_for_forward)

    text = (
        "📨 *Get ID from forwarded message*\n\n"
        "Forward me any message from the user\n"
        "whose ID you want to know.\n\n"
        "_Send /cancel to abort_"
    )

    # Create cancel keyboard
    cancel_keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Cancel")]],
        resize_keyboard=True
    )

    await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.message.answer("Waiting for a forwarded message...", reply_markup=cancel_keyboard)
    await callback.answer()


# Handler for ID from forwarded message
@dp.message(IDStates.waiting_for_forward)
async def process_forward(message: types.Message, state: FSMContext):
    """Processes forwarded message and returns author ID"""
    if message.text in ["❌ Cancel", "/cancel"]:
        await state.clear()
        await message.answer("❌ Operation cancelled", reply_markup=get_main_menu())
        return

    # Check if message is forwarded
    if not message.forward_from and not message.forward_from_chat and not message.forward_sender_name:
        await message.reply(
            "❌ This is not a forwarded message!\n\n"
            "Please forward a message from the user\n"
            "whose ID you want to know."
        )
        return

    try:
        if message.forward_from:
            # Forwarded from user
            user = message.forward_from
            text = (
                f"✅ *ID retrieved from forwarded message!*\n\n"
                f"👤 Name: {user.first_name}"
            )
            if user.last_name:
                text += f" {user.last_name}"
            text += f"\n🆔 User ID: `{user.id}`\n"

            if user.username:
                text += f"📱 Username: @{user.username}\n"

            if user.is_bot:
                text += f"🤖 This is a bot\n"

            text += "\n_Tap the ID to copy_"

            await message.reply(text, parse_mode="Markdown")

        elif message.forward_from_chat:
            # Forwarded from channel/group
            chat = message.forward_from_chat
            text = (
                f"✅ *ID retrieved from forwarded message!*\n\n"
                f"📢 Title: {chat.title}\n"
                f"🆔 Chat ID: `{chat.id}`\n"
            )

            if chat.username:
                text += f"📱 Username: @{chat.username}\n"

            chat_type = {
                "channel": "Channel",
                "group": "Group",
                "supergroup": "Supergroup"
            }.get(chat.type, chat.type)
            text += f"ℹ️ Type: {chat_type}\n"

            text += "\n_Tap the ID to copy_"

            await message.reply(text, parse_mode="Markdown")

        elif message.forward_sender_name:
            # Forwarded from user with hidden info
            await message.reply(
                f"⚠️ *Message forwarded from user*\n\n"
                f"📝 Sender name: {message.forward_sender_name}\n\n"
                f"❌ Unfortunately, this user has hidden their\n"
                f"identity in privacy settings.\n"
                f"ID cannot be retrieved.",
                parse_mode="Markdown"
            )

        await state.clear()
        await message.answer("Choose an action from the menu:", reply_markup=get_main_menu())

    except Exception as e:
        logger.error(f"Error processing forwarded message: {e}")
        await message.reply("❌ An error occurred while processing the message.")
        await state.clear()
        await message.answer("Choose an action from the menu:", reply_markup=get_main_menu())


@dp.message(F.text.in_(["🧹 Smart Clean", "🔄 Dedup"]))
async def set_text_command(message: types.Message):
    user_id = message.from_user.id

    if user_states.get(user_id, {}).get('mode') != 'text':
        await message.reply("First select text processing mode from the main menu.")
        return

    if message.text == "🧹 Smart Clean":
        command = 'smart_clean'
    else:
        command = 'dedup'

    user_states[user_id]['text_command'] = command

    await message.reply(f"✅ Selected operation: *{message.text}*\n\nNow send a .txt file for processing.",
                        parse_mode="Markdown")


@dp.message(F.text.in_(["◀️ Back", "◀️ Main Menu"]))
async def back_to_menu(message: types.Message):
    user_id = message.from_user.id
    current_mode = user_states.get(user_id, {}).get('mode')

    if current_mode == 'text':
        user_states[user_id] = {'mode': None}
        await message.reply("🏠 Main menu:", reply_markup=get_main_menu())
    else:
        await send_welcome(message)


@dp.message(F.text == "❓ Help")
async def help_handler(message: types.Message):
    await send_help(message)


@dp.message(F.text == "💰 Мониторинг кошельков")
async def crypto_monitoring_start(message: types.Message):
    """Начало режима мониторинга кошельков"""
    msg = "💰 <b>Crypto Monitor Bot</b>\n\n"
    msg += "🔍 Я помогу вам отслеживать транзакции на ваших криптокошельках\n\n"
    msg += "📊 Поддерживаемые монеты:\n"
    msg += "• TON\n• Bitcoin\n• Ethereum\n• USDT (ERC-20)\n\n"
    msg += "Используйте меню ниже 👇"
    
    await message.answer(msg, parse_mode='HTML', reply_markup=get_crypto_main_keyboard())


@dp.message(F.text == "➕ Добавить кошелек")
async def add_wallet_start(message: types.Message, state: FSMContext):
    """Начало добавления кошелька"""
    await message.answer(
        "Выберите криптовалюту:",
        reply_markup=get_coin_keyboard()
    )
    await state.set_state(AddWallet.choosing_coin)


@dp.callback_query(F.data.startswith("coin_"))
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


@dp.message(AddWallet.entering_address)
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


@dp.message(F.text == "💰 Баланс")
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


@dp.message(F.text == "📊 Статус")
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


@dp.message(F.text == "🗑 Удалить кошелек")
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


@dp.callback_query(F.data.startswith("delete_"))
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


@dp.message(F.text == "◀️ Главное меню")
async def back_to_main_menu(message: types.Message):
    """Возврат в главное меню"""
    await send_welcome(message)


# Document (text file) handler
@dp.message(F.content_type == ContentType.DOCUMENT)
async def handle_document(message: types.Message):
    user_id = message.from_user.id
    user_state = user_states.get(user_id, {})

    if user_state.get('mode') != 'text':
        await message.reply("To process files, first select '📝 Process Text' from the main menu.")
        return

    if not TEXT_PROCESSING_AVAILABLE:
        await message.reply("❌ Text file processing is unavailable.")
        return

    file = message.document
    if not file.file_name.endswith('.txt'):
        await message.reply("❌ Please send a .txt file.")
        return

    if file.file_size > Config.MAX_FILE_SIZE:
        await message.reply("❌ File is too large. Maximum size is 10 MB.")
        return

    command = user_state.get('text_command')
    if not command:
        await message.reply("❌ First select an operation: 🧹 Smart Clean or 🔄 Dedup.")
        return

    try:
        processing_msg = await message.reply("⚙️ Processing file...")

        file_path = f"temp_{file.file_id}.txt"
        new_path = f"processed_{file.file_id}.txt"

        file_info = await bot.get_file(file.file_id)
        await bot.download_file(file_info.file_path, file_path)

        if command == 'smart_clean':
            await process_smart_clean(file_path, new_path)
            operation_name = "Smart Clean"
        elif command == 'dedup':
            await process_dedup(file_path, new_path)
            operation_name = "Dedup"

        processed_file = FSInputFile(new_path)
        await bot.send_document(
            chat_id=message.chat.id,
            document=processed_file,
            caption=f"✅ Operation {operation_name} completed!"
        )

        # Delete temp files after successful send
        try:
            os.remove(file_path)
        except Exception as e:
            logger.warning(f"Failed to delete file {file_path}: {e}")

        try:
            os.remove(new_path)
        except Exception as e:
            logger.warning(f"Failed to delete file {new_path}: {e}")

        # Update statistics
        user_stats[user_id]["texts"] += 1
        bot_stats["total_texts"] += 1
        save_stats()

        # Reset command after processing
        user_states[user_id]['text_command'] = None

    except Exception as e:
        logger.error(f"Error processing file from {user_id}: {e}")
        user_stats[user_id]["errors"] += 1
        save_stats()
        await message.reply("❌ An error occurred during file processing. Please try again.")


# This handler must be at the very end!
@dp.message(F.content_type == ContentType.TEXT)
async def handle_unsupported_content(message: types.Message):
    user_id = message.from_user.id
    user_mode = user_states.get(user_id, {}).get('mode')

    content_type_translations = {
        "photo": "photo",
        "audio": "audio",
        "voice": "voice message",
        "sticker": "sticker",
        "animation": "GIF",
        "text": "text message",
    }

    content_type = message.content_type
    translated_type = content_type_translations.get(content_type, content_type)

    if user_mode == 'text':
        await message.reply(f"In text processing mode, I only accept .txt files. You sent: {translated_type}.")
    else:
        await message.reply(f"Please select a mode from the main menu first. You sent: {translated_type}.")


# Error handler
@dp.errors()
async def errors_handler(event, exception=None):
    # Compatibility with different aiogram v3 signatures
    if exception is None:
        exception = getattr(event, "exception", None)
    update = getattr(event, "update", None)

    if isinstance(exception, TelegramAPIError):
        logger.error(f"Telegram API Error: {exception}")
    else:
        logger.error(f"Unexpected error: {exception}")

    try:
        msg = None
        if update and getattr(update, "message", None):
            msg = update.message
        elif update and getattr(update, "callback_query", None) and update.callback_query.message:
            msg = update.callback_query.message

        if msg:
            user_id = msg.from_user.id
            user_stats[user_id]["errors"] += 1
            save_stats()
            await msg.reply("❌ An error occurred. Please try again later.")
    except Exception:
        pass
    return True


# Bot initialization
async def init_bot():
    """Initialize bot and all required components"""
    try:
        load_stats()

        if TEXT_PROCESSING_AVAILABLE:
            logger.info("✅ Text processing modules loaded")

        logger.info("🤖 Universal bot started successfully")
        logger.info(f"📝 Text processing: {'available' if TEXT_PROCESSING_AVAILABLE else 'unavailable'}")
        logger.info("🆔 ID features: available")

    except Exception as e:
        logger.error(f"Initialization error: {e}")


async def main():
    """Main launch function"""
    # Start Prometheus metrics server
    start_http_server(8000)

    # Start background tasks
    asyncio.create_task(init_bot())
    asyncio.create_task(monitor_all_wallets())

    # Start bot polling
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
