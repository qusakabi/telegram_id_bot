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


# Keyboards
def get_main_menu():
    keyboard = [
        [KeyboardButton(text="📝 Process Text")],
        [KeyboardButton(text="🆔 Get ID"), KeyboardButton(text="❓ Help")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_text_menu():
    keyboard = [
        [KeyboardButton(text="🧹 Smart Clean")],
        [KeyboardButton(text="🔄 Dedup")],
        [KeyboardButton(text="◀️ Back")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


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

    # Start bot polling
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
