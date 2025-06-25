import os
import uuid
import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.exceptions import TelegramForbiddenError
from yt_dlp import YoutubeDL
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

API_TOKEN = os.getenv("BOT_TOKEN")
DOMAIN = os.getenv("WEBHOOK_URL")
if not API_TOKEN or not DOMAIN:
    raise RuntimeError("BOT_TOKEN or WEBHOOK_URL environment variables not set")

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = DOMAIN + WEBHOOK_PATH

bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

user_lang = {}

translations = {
    "choose": {
        "en": "Please choose your language:",
        "hy": "Խնդրում եմ ընտրեք լեզուն՝",
        "ru": "Пожалуйста, выберите язык:",
    },
    "send": {
        "en": "Send a YouTube link.",
        "hy": "Ուղարկեք YouTube հղումը։",
        "ru": "Отправьте ссылку на YouTube.",
    },
    "downloading": {
        "en": "⏳ Downloading...",
        "hy": "⏳ Ներբեռնում...",
        "ru": "⏳ Загрузка...",
    },
    "done": {
        "en": "✅ Done.",
        "hy": "✅ Պատրաստ է։",
        "ru": "✅ Готово.",
    },
    "file_too_big": {
        "en": "❌ File is too big for Telegram.",
        "hy": "❌ Ֆայլը չափից մեծ է Telegram-ի համար։",
        "ru": "❌ Файл слишком большой для Telegram.",
    },
    "error": {
        "en": "❌ Error: {}",
        "hy": "❌ Սխալ՝ {}",
        "ru": "❌ Ошибка: {}",
    },
}

COOKIES_PATH = "cookies.txt"

async def safe_send(message: types.Message, text=None, **kwargs):
    try:
        if text:
            await message.answer(text, **kwargs)
        else:
            await message.answer(**kwargs)
    except TelegramForbiddenError:
        logging.warning(f"User {message.from_user.id} blocked the bot.")
    except Exception as e:
        logging.exception(f"Failed to send message to {message.from_user.id}: {e}")

@dp.message(Command(commands=["start"]))
async def start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🇦🇲 Հայ", callback_data="lang_hy"),
        InlineKeyboardButton(text="🇷🇺 Рус", callback_data="lang_ru"),
        InlineKeyboardButton(text="🇬🇧 Eng", callback_data="lang_en"),
    ]])
    await safe_send(message, text=translations["choose"]["en"], reply_markup=kb)

@dp.callback_query(F.data.startswith("lang_"))
async def set_language(callback: types.CallbackQuery):
    lang = callback.data.split("_")[1]
    user_lang[callback.from_user.id] = lang
    try:
        await callback.message.edit_reply_markup()
        await safe_send(callback.message, text=translations["send"][lang])
        await callback.answer()
    except TelegramForbiddenError:
        logging.warning(f"User {callback.from_user.id} blocked the bot.")

@dp.message()
async def process_link(message: types.Message):
    uid = message.from_user.id
    lang = user_lang.get(uid, "en")
    url = message.text.strip()

    if not url.startswith("http") or ("youtube.com" not in url and "youtu.be" not in url):
        await safe_send(message, text="❌ This bot supports only YouTube links.")
        return

    await safe_send(message, text=translations["downloading"][lang])

    try:
        mp3_path, title, performer, duration = await download_audio(url)

        if os.path.getsize(mp3_path) > 50 * 1024 * 1024:
            await safe_send(message, text=translations["file_too_big"][lang])
            os.remove(mp3_path)
            return

        audio = FSInputFile(mp3_path)
        try:
            await message.answer_audio(
                audio=audio,
                title=title,
                performer=performer,
                duration=duration,
            )
            await safe_send(message, text=translations["done"][lang])
        except TelegramForbiddenError:
            logging.warning(f"User {message.from_user.id} blocked the bot during audio send.")
        os.remove(mp3_path)
    except Exception as e:
        logging.exception("Download error")
        await safe_send(message, text=translations["error"][lang].format(str(e)))

async def download_audio(url: str):
    if not os.path.exists(COOKIES_PATH):
        raise FileNotFoundError(f"cookies.txt not found at path: {COOKIES_PATH}")

    uid = str(uuid.uuid4())
    download_dir = os.path.join("downloads", uid)
    os.makedirs(download_dir, exist_ok=True)

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(download_dir, "%(title)s.%(ext)s"),
        "quiet": True,
        "noplaylist": True,
        "cookies": COOKIES_PATH,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "128",
        }],
    }

    def run_ydl():
        with YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=True)

    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(None, run_ydl)

    mp3_path = os.path.splitext(ydl_opts["outtmpl"] % info)[0] + ".mp3"
    title = info.get("title", "Audio")
    performer = info.get("uploader", "")
    duration = info.get("duration", 0)

    return mp3_path, title, performer, duration

# Webhook setup
async def on_startup(app):
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(WEBHOOK_URL)

async def on_shutdown(app):
    await bot.delete_webhook()

app = web.Application()
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
setup_application(app, dp, bot=bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    web.run_app(app, port=int(os.getenv("PORT", 8000)))
