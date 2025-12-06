import asyncio
import logging
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from prometheus_client import start_http_server
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramAPIError

# Core imports
from core.config import Config
from core.metrics import (
    load_stats, init_bot_components, messages_received, command_starts,
    user_stats, bot_stats, save_stats
)

# Bot components
from bot.states.states import IDStates, AddWallet
from bot.keyboards.base import get_main_menu
from bot.keyboards.crypto import get_crypto_main_keyboard, get_coin_keyboard

# Handlers
from bot.handlers.base import (
    send_welcome, send_help, show_stats, chatid_handler, userid_handler,
    sticker_handler, set_text_mode, id_menu_handler, callback_get_my_id,
    callback_get_by_forward, process_forward, set_text_command,
    back_to_menu, help_handler, handle_document, handle_unsupported_content
)
from bot.handlers.crypto import (
    crypto_monitoring_start, add_wallet_start, coin_selected,
    wallet_address_entered, show_balances, show_status,
    delete_wallet_menu, delete_wallet_confirm, back_to_main_menu
)

# Services
from bot.services.crypto_service import monitor_all_wallets

# Load environment variables
load_dotenv()

# Validate configuration
if not Config.validate_config():
    exit(1)

# Bot initialization
bot = Bot(token=Config.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Setup logging
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format=Config.LOG_FORMAT
)
logger = logging.getLogger(__name__)

# Create directories
os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)

# File handler for logging
file_handler = logging.FileHandler(f"{Config.LOGS_DIR}/bot_{__import__('datetime').datetime.now().strftime('%Y-%m-%d')}.log")
file_handler.setFormatter(logging.Formatter(Config.LOG_FORMAT))
logger.addHandler(file_handler)

# Initialize bot components in metrics
init_bot_components(bot, logger)


# Register handlers

# Command handlers
@dp.message(F.text == '/start')
async def start_handler(message: types.Message):
    await send_welcome(message)

@dp.message(F.command == "help")
async def help_cmd_handler(message: types.Message):
    await send_help(message)

@dp.message(F.command == "stats")
async def stats_handler(message: types.Message):
    await show_stats(message)

@dp.message(F.command == "chatid")
async def chatid_cmd_handler(message: types.Message):
    await chatid_handler(message)

@dp.message(F.command == "userid")
@dp.message(F.command == "id")
async def userid_cmd_handler(message: types.Message):
    await userid_handler(message)

@dp.message(F.content_type == types.ContentType.STICKER)
async def sticker_cmd_handler(message: types.Message):
    await sticker_handler(message)


# Menu button handlers
@dp.message(F.text == "📝 Process Text")
async def process_text_handler(message: types.Message):
    await set_text_mode(message)

@dp.message(F.text == "🆔 Get ID")
async def get_id_handler(message: types.Message):
    await id_menu_handler(message)

@dp.message(F.text == "❓ Help")
async def help_btn_handler(message: types.Message):
    await help_handler(message)

@dp.message(F.text == "💰 Мониторинг кошельков")
async def crypto_monitor_handler(message: types.Message):
    await crypto_monitoring_start(message)


# Callback handlers for ID menu
@dp.callback_query(F.data == "get_my_id")
async def get_my_id_callback(callback: types.CallbackQuery):
    await callback_get_my_id(callback)

@dp.callback_query(F.data == "get_by_forward")
async def get_by_forward_callback(callback: types.CallbackQuery, state):
    await callback_get_by_forward(callback, state)


# FSM handlers
@dp.message(IDStates.waiting_for_forward)
async def forward_state_handler(message: types.Message, state):
    await process_forward(message, state)


# Text processing handlers
@dp.message(F.text.in_(["🧹 Smart Clean", "🔄 Dedup"]))
async def text_command_handler(message: types.Message):
    await set_text_command(message)

@dp.message(F.text.in_(["◀️ Back", "◀️ Main Menu"]))
async def back_menu_handler(message: types.Message):
    await back_to_menu(message)


# Document handler
@dp.message(F.content_type == types.ContentType.DOCUMENT)
async def document_handler(message: types.Message):
    await handle_document(message)


# Crypto handlers
@dp.message(F.text == "➕ Добавить кошелек")
async def add_wallet_handler(message: types.Message, state):
    await add_wallet_start(message, state)

@dp.callback_query(F.data.startswith("coin_"))
async def coin_select_callback(callback: types.CallbackQuery, state):
    await coin_selected(callback, state)

@dp.message(AddWallet.entering_address)
async def wallet_address_handler(message: types.Message, state):
    await wallet_address_entered(message, state)

@dp.message(F.text == "💰 Баланс")
async def balance_handler(message: types.Message):
    await show_balances(message)

@dp.message(F.text == "📊 Статус")
async def status_handler(message: types.Message):
    await show_status(message)

@dp.message(F.text == "🗑 Удалить кошелек")
async def delete_wallet_handler(message: types.Message):
    await delete_wallet_menu(message)

@dp.callback_query(F.data.startswith("delete_"))
async def delete_wallet_callback(callback: types.CallbackQuery):
    await delete_wallet_confirm(callback)

@dp.message(F.text == "◀️ Главное меню")
async def back_main_handler(message: types.Message):
    await back_to_main_menu(message)


# Fallback handler (must be last)
@dp.message(F.content_type == types.ContentType.TEXT)
async def unsupported_handler(message: types.Message):
    await handle_unsupported_content(message)


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


async def init_bot():
    """Initialize bot and all required components"""
    try:
        load_stats()
        logger.info("🤖 Universal bot started successfully")
        logger.info(f"📝 Text processing: {'available' if hasattr(__import__('core.metrics'), 'TEXT_PROCESSING_AVAILABLE') and __import__('core.metrics').TEXT_PROCESSING_AVAILABLE else 'unavailable'}")
        logger.info("🆔 ID features: available")
        logger.info("💰 Crypto monitoring: available")

    except Exception as e:
        logger.error(f"Initialization error: {e}")


async def main():
    """Main launch function"""
    # Start Prometheus metrics server
    start_http_server(8000)

    # Start background tasks
    asyncio.create_task(init_bot())
    asyncio.create_task(monitor_all_wallets(bot))

    # Start bot polling
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
