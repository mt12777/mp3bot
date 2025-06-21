import os
import uuid
import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from yt_dlp import YoutubeDL
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

API_TOKEN = os.getenv("BOT_TOKEN")
DOMAIN = os.getenv("WEBHOOK_URL")
if not API_TOKEN or not DOMAIN:
    raise RuntimeError("BOT_TOKEN or WEBHOOK_URL not set")

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = DOMAIN + WEBHOOK_PATH

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

user_lang = {}

translations = {
    "choose": {
        "en": "Please choose your language:",
        "hy": "Ընտրեք լեզուն՝",
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
    "sent": {
        "en": "✅ Done.",
        "hy": "✅ Պատրաստ է։",
        "ru": "✅ Готово.",
    },
    "big": {
        "en": "❌ File too big for Telegram.",
        "hy": "❌ Ֆայլը չափից մեծ է Telegram-ի համար։",
        "ru": "❌ Файл слишком большой для Telegram.",
    },
    "error": {
        "en": "❌ Error: {}",
        "hy": "❌ Սխալ՝ {}",
        "ru": "❌ Ошибка: {}",
    },
}

@dp.message(commands=["start"])
async def start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🇦🇲 Հայ", callback_data="lang_hy"),
        InlineKeyboardButton(text="🇷🇺 Рус", callback_data="lang_ru"),
        InlineKeyboardButton(text="🇬🇧 Eng", callback_data="lang_en"),
    ]])
    await message.answer(translations["choose"]["en"], reply_markup=kb)

@dp.callback_query()
async def set_lang(callback: types.CallbackQuery):
    lang = callback.data.split("_")[1]
    user_lang[callback.from_user.id] = lang
    await callback.message.edit_reply_markup()
    await callback.message.answer(translations["send"][lang])
    await callback.answer()

@dp.message()
async def download_audio(message: types.Message):
    uid = message.from_user.id
    lang = user_lang.get(uid, "en")
    url = message.text.strip()

    if not url.startswith("http"):
        await message.answer("❌ Invalid link.")
        return

    await message.answer(translations["downloading"][lang])

    try:
        path = await ytdlp_download(url)
        if os.path.getsize(path) > 50 * 1024 * 1024:
            await message.answer(translations["big"][lang])
            os.remove(path)
            return

        audio = FSInputFile(path)
        await message.answer_audio(audio)
        await message.answer(translations["sent"][lang])
        os.remove(path)
    except Exception as e:
        logging.exception("Download error")
        await message.answer(translations["error"][lang].format(str(e)))

async def ytdlp_download(url):
    uid = str(uuid.uuid4())
    download_dir = os.path.join("downloads", uid)
    os.makedirs(download_dir, exist_ok=True)

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(download_dir, "%(title)s.%(ext)s"),
        "quiet": True,
        "noplaylist": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "128"
        }],
    }

    loop = asyncio.get_event_loop()
    with YoutubeDL(ydl_opts) as ydl:
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
    mp3_path = os.path.splitext(ydl.prepare_filename(info))[0] + ".mp3"
    return mp3_path

# Webhook
async def on_startup(app):
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
