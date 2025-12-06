import os
from aiogram import types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import ContentType, FSInputFile

# Import from core modules
import sys
sys.path.append('/app')
from core.config import Config
from core.metrics import (
    messages_received, command_starts, user_states, user_stats,
    bot_stats, save_stats, TEXT_PROCESSING_AVAILABLE, bot, logger
)

# Import from bot modules
from bot.keyboards.base import get_main_menu, get_text_menu
from bot.states.states import IDStates

# Try to import processors
try:
    from processors import process_clean, process_dedup, process_smart_clean
except ImportError:
    pass


async def send_welcome(message: types.Message):
    """Обработчик команды /start"""
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


async def send_help(message: types.Message):
    """Обработчик команды /help"""
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


async def show_stats(message: types.Message):
    """Обработчик команды /stats"""
    await message.reply("Statistics are disabled.", parse_mode="Markdown")


async def chatid_handler(message: types.Message):
    """Обработчик команды /chatid"""
    messages_received.inc()
    await message.reply(f"Chat ID: {message.chat.id}")


async def userid_handler(message: types.Message):
    """Обработчик команд /userid и /id"""
    messages_received.inc()
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    await message.reply(f"User ID: {target.id}")


async def sticker_handler(message: types.Message):
    """Обработчик стикеров"""
    sticker_id = message.sticker.file_id
    await message.reply(f"Sticker ID: {sticker_id}")


async def set_text_mode(message: types.Message):
    """Обработчик кнопки '📝 Process Text'"""
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


async def id_menu_handler(message: types.Message):
    """Обработчик кнопки '🆔 Get ID'"""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

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


async def callback_get_my_id(callback: types.CallbackQuery):
    """Обработчик кнопки '👤 My ID'"""
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


async def callback_get_by_forward(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик кнопки '📨 From Forward'"""
    await state.set_state(IDStates.waiting_for_forward)

    text = (
        "📨 *Get ID from forwarded message*\n\n"
        "Forward me any message from the user\n"
        "whose ID you want to know.\n\n"
        "_Send /cancel to abort_"
    )

    from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

    # Create cancel keyboard
    cancel_keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Cancel")]],
        resize_keyboard=True
    )

    await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.message.answer("Waiting for a forwarded message...", reply_markup=cancel_keyboard)
    await callback.answer()


async def process_forward(message: types.Message, state: FSMContext):
    """Обработчик пересланного сообщения"""
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


async def set_text_command(message: types.Message):
    """Обработчик команд для обработки текста"""
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


async def back_to_menu(message: types.Message):
    """Обработчик кнопки '◀️ Back'"""
    user_id = message.from_user.id
    current_mode = user_states.get(user_id, {}).get('mode')

    if current_mode == 'text':
        user_states[user_id] = {'mode': None}
        await message.reply("🏠 Main menu:", reply_markup=get_main_menu())
    else:
        await send_welcome(message)


async def help_handler(message: types.Message):
    """Обработчик кнопки '❓ Help'"""
    await send_help(message)


async def handle_document(message: types.Message):
    """Обработчик документов (текстовых файлов)"""
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


async def handle_unsupported_content(message: types.Message):
    """Обработчик неподдерживаемого контента"""
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
