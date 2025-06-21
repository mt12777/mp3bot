import os
import time
import uuid
import logging
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from yt_dlp import YoutubeDL

API_TOKEN = os.getenv("BOT_TOKEN")
DOMAIN = os.getenv("WEBHOOK_URL")  # Render dashboard → Environment → WEBHOOK_URL=https://xxx.onrender.com

if not API_TOKEN or not DOMAIN:
    raise RuntimeError("BOT_TOKEN or WEBHOOK_URL not set in environment!")

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = DOMAIN + WEBHOOK_PATH

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

class States(StatesGroup):
    choosing_language = State()
    ready = State()

translations = {
    "choose_language": {
        "en": "Please choose your language.",
        "hy": "Խնդրում եմ ընտրեք լեզուն։",
        "ru": "Пожалуйста, выберите язык.",
    },
    "send_link": {
        "en": "Send a YouTube link.",
        "hy": "Ուղարկեք YouTube հղումը։",
        "ru": "Отправьте ссылку на YouTube.",
    },
    "downloading": {
        "en": "⏳ Downloading and processing...",
        "hy": "⏳ Ներբեռնում և մշակում...",
        "ru": "⏳ Загрузка и обработка...",
    },
    "finished": {
        "en": "✅ Download finished.",
        "hy": "✅ Ներբեռնումը ավարտված է։",
        "ru": "✅ Загрузка завершена.",
    },
    "error": {
        "en": "❌ Error: {}",
        "hy": "❌ Սխալ՝ {}",
        "ru": "❌ Ошибка: {}",
    },
    "file_too_big": {
        "en": "❌ File too big for Telegram (~50MB limit).",
        "hy": "❌ Ֆայլը մեծ է Telegram-ի համար (~50ՄԲ սահման)։",
        "ru": "❌ Файл слишком большой для Telegram (~50MB лимит).",
    }
}

@dp.message(CommandStart())
async def start(message: types.Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Հայ 🇦🇲", callback_data="lang_hy"),
        InlineKeyboardButton(text="Рус 🇷🇺", callback_data="lang_ru"),
        InlineKeyboardButton(text="Eng 🇬🇧", callback_data="lang_en"),
    ]])
    await state.set_state(States.choosing_language)
    await message.answer(translations["choose_language"]["en"], reply_markup=kb)

@dp.callback_query(F.data.startswith("lang_"))
async def set_language(callback: CallbackQuery, state: FSMContext):
    lang = callback.data.split("_")[1]
    await state.update_data(lang=lang)
    await state.set_state(States.ready)
    await callback.message.edit_reply_markup()
    await callback.message.answer(translations["send_link"][lang])
    await callback.answer()

@dp.message(States.ready)
async def process_link(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "en")
    url = message.text.strip()

    if not url.startswith("http"):
        await message.answer("Invalid link.")
        return

    progress_msg = await message.answer(translations["downloading"][lang])

    try:
        await download_and_send_mp3(message, url, lang, progress_msg)
        await message.answer(translations["finished"][lang])
    except FileTooBigError:
        await message.answer(translations["file_too_big"][lang])
    except Exception as e:
        logging.exception("Download error")
        await message.answer(translations["error"][lang].format(str(e)))

class FileTooBigError(Exception):
    pass

def make_progress_hook(msg: types.Message):
    last = {"time": time.time()}

    async def update_progress(text: str):
        try:
            await msg.edit_text(text)
        except:
            pass

    def hook(d):
        if d['status'] != 'downloading':
            return

        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        downloaded = d.get("downloaded_bytes", 0)

        if not total:
            return

        percent = int(downloaded / total * 100)
        blocks = int(percent / 20)
        bar = "⬛" * blocks + "⬜" * (5 - blocks)
        text = f"{bar} {percent}%"

        now = time.time()
        if now - last["time"] >= 1:
            last["time"] = now
            asyncio.create_task(update_progress(text))

    return hook

async def download_and_send_mp3(message: types.Message, url: str, lang: str, progress_msg: types.Message):
    base_dir = "downloads"
    uid = str(uuid.uuid4())
    download_dir = os.path.join(base_dir, uid)
    os.makedirs(download_dir, exist_ok=True)

    cookies_path = "cookies.txt"
    if not os.path.exists(cookies_path):
        raise Exception("cookies.txt not found!")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(download_dir, "%(title)s.%(ext)s"),
        "quiet": True,
        "noplaylist": True,
        "cookiefile": cookies_path,
        "writethumbnail": True,
        "cachedir": False,
        "progress_hooks": [make_progress_hook(progress_msg)],
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "postprocessor_args": [
            "-id3v2_version", "3",
            "-metadata:s:v", "title=Album cover",
            "-metadata:s:v", "comment=Cover (front)"
        ],
        "prefer_ffmpeg": True,
        "geo_bypass": True
    }

    loop = asyncio.get_event_loop()
    with YoutubeDL(ydl_opts) as ydl:
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))

    base_filename = ydl.prepare_filename(info)
    mp3_path = os.path.splitext(base_filename)[0] + ".mp3"
    thumb_path = os.path.splitext(base_filename)[0] + ".webp"

    if not os.path.exists(mp3_path):
        raise Exception("MP3 not found")

    if os.path.getsize(mp3_path) > 50 * 1024 * 1024:
        raise FileTooBigError()

    audio = FSInputFile(mp3_path)
    thumb = FSInputFile(thumb_path) if os.path.exists(thumb_path) else None

    await message.answer_audio(
        audio=audio,
        title=info.get("title", "Audio"),
        performer=info.get("uploader", ""),
        duration=info.get("duration"),
        thumbnail=thumb
    )

    try:
        os.remove(mp3_path)
        if os.path.exists(thumb_path):
            os.remove(thumb_path)
        os.rmdir(download_dir)
    except:
        pass

# --- Webhook Setup ---
async def on_startup(app): await bot.set_webhook(WEBHOOK_URL)
async def on_shutdown(app): await bot.delete_webhook()

app = web.Application()
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)
SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
setup_application(app, dp, bot=bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    web.run_app(app, port=int(os.getenv("PORT", 8000)))
