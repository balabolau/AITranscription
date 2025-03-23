import logging
import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
import yaml
from jobs import enqueue_transcription

# Set up logging for the bot.
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)
logging.getLogger("telegram.request").setLevel(logging.WARNING)
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)

# Load configuration from YAML.
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

# Get Telegram token, bot username, and allowed chat IDs from config.
TELEGRAM_TOKEN = config.get("telegram", {}).get("token", "YOUR_BOT_TOKEN_HERE")
BOT_USERNAME = config.get("telegram", {}).get("bot_username", "YourBotUsername")
ALLOWED_CHAT_IDS = config.get("allowed_chat_ids") or []

# Define directory paths using configuration.
BASE_DIR = os.path.expanduser(config.get("directories", {}).get("base", "~/Documents/WhisperProcessor"))
DOWNLOADS_DIR = os.path.join(BASE_DIR, config.get("directories", {}).get("downloads", "downloads"))
OUTPUT_DIR = os.path.join(BASE_DIR, config.get("directories", {}).get("transcripts", "transcripts"))

# Ensure the downloads directory exists.
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# /landing command: Public landing page for the channel.
async def landing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    landing_text = (
        "Welcome to the Whisper Transcription Bot!\n\n"
        "This bot transcribes audio files using OpenAI's Whisper model. "
        "Simply upload an audio file, select your desired transcription language, "
        "and provide any additional prompt you wish to include. "
        "The bot will process your file in the background, update you on progress, "
        "and return the transcript as a .txt file.\n\n"
        "Accepted file formats: WAV, MP3, M4A, OGG, FLAC, and MP4.\n\n"
        "Click the button below to start a private chat with the bot and begin transcribing."
    )
    button = InlineKeyboardButton("Start Private Chat", url=f"https://t.me/{BOT_USERNAME}?start=private")
    reply_markup = InlineKeyboardMarkup([[button]])
    await update.message.reply_text(landing_text, reply_markup=reply_markup)

# /start command: Used in the private chat.
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.id not in ALLOWED_CHAT_IDS:
        await update.message.reply_text("Access Denied.\nPlease request access with /myid.")
        return
    await update.message.reply_text("Welcome! Please send me an audio file to transcribe.")

# /myid command: Returns the chat ID and logs the access request.
async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    logger.info(f"{username} requested access in chat {chat_id}")
    await update.message.reply_text(f"Your chat ID is: {chat_id}")

# Handler for receiving audio files.
async def audio_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.id not in ALLOWED_CHAT_IDS:
        await update.message.reply_text("Access Denied.")
        return

    file_obj = None
    original_filename = None
    if update.message.audio:
        file_obj = update.message.audio
    elif update.message.voice:
        file_obj = update.message.voice
    elif update.message.document:
        file_obj = update.message.document

    if not file_obj:
        await update.message.reply_text("No audio file detected. Please send an audio file.")
        return

    await update.message.reply_text("Audio file received. Downloading...")
    file_id = file_obj.file_id
    new_file = await context.bot.get_file(file_id)

    if hasattr(file_obj, "file_name") and file_obj.file_name:
        original_filename = file_obj.file_name
    else:
        original_filename = f"{file_obj.file_unique_id}.wav"

    file_path = os.path.join(DOWNLOADS_DIR, original_filename)
    await new_file.download_to_drive(custom_path=file_path)
    
    context.user_data["file_path"] = file_path
    context.user_data["original_filename"] = original_filename

    # Send inline keyboard for language selection.
    keyboard = [
        [
            InlineKeyboardButton("English", callback_data="lang_en"),
            InlineKeyboardButton("French", callback_data="lang_fr"),
            InlineKeyboardButton("Auto-detect", callback_data="lang_auto"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Please select a transcription language:", reply_markup=reply_markup)

# Callback handler for language selection.
async def language_selection_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.id not in ALLOWED_CHAT_IDS:
        await update.callback_query.answer("Access Denied.", show_alert=True)
        return

    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "lang_en":
        language_override = "en"
        lang_text = "English"
    elif data == "lang_fr":
        language_override = "fr"
        lang_text = "French"
    else:
        language_override = ""
        lang_text = "Auto-detect"
    context.user_data["language_override"] = language_override
    await query.edit_message_text(text=f"Language set to {lang_text}. Now please send your transcription prompt.")

# Handler for receiving the transcription prompt.
async def prompt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.id not in ALLOWED_CHAT_IDS:
        await update.message.reply_text("Access Denied.")
        return

    if "file_path" not in context.user_data or "original_filename" not in context.user_data:
        await update.message.reply_text("Please send an audio file first.")
        return

    if "language_override" not in context.user_data:
        context.user_data["language_override"] = ""

    user_prompt = update.message.text
    file_path = context.user_data.pop("file_path")
    original_filename = context.user_data.pop("original_filename")
    language_override = context.user_data.pop("language_override", "")

    await update.message.reply_text("Your transcription job is being enqueued. Please check the dashboard later for updates.")
    from jobs import enqueue_transcription
    try:
        job_id = enqueue_transcription(file_path, OUTPUT_DIR, prompt_override=user_prompt, language_override=language_override)
        logger.info(f"Job {job_id} enqueued for file {original_filename}")
        await update.message.reply_text(f"Job enqueued with ID: {job_id}")
    except Exception as e:
        logger.error("Failed to enqueue job: " + str(e))
        await update.message.reply_text("Failed to enqueue job. Please try again later.")
    # Note: Future enhancements might include automatically notifying the user when the job is complete.

def main() -> None:
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Register handlers.
    application.add_handler(CommandHandler("landing", landing))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("myid", myid))
    application.add_handler(MessageHandler(filters.AUDIO | filters.VOICE | filters.Document.ALL, audio_handler))
    application.add_handler(CallbackQueryHandler(language_selection_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, prompt_handler))
    application.add_error_handler(lambda update, context: logger.error("Error:", exc_info=context.error))

    application.run_polling()

if __name__ == "__main__":
    main()
