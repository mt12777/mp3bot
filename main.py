import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# Ստանում ենք անհրաժեշտ փոփոխականները միջավայրից
TOKEN = os.getenv("BOT_TOKEN")
DOMAIN = os.getenv("WEBHOOK_URL")

if not TOKEN or not DOMAIN:
    raise RuntimeError("BOT_TOKEN or WEBHOOK_URL environment variables not set")

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = DOMAIN + WEBHOOK_PATH  # Ավելացնում ենք վերջի /webhook

bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message()
async def handle_message(message: types.Message):
    await message.answer("✅ Webhook-ը աշխատում է!")

async def on_startup(app):
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(WEBHOOK_URL)  # Այստեղ WEBHOOK_URL-ը արդեն ամբողջական է

async def on_shutdown(app):
    await bot.delete_webhook()

# Աշխատեցնում ենք aiohttp սերվերը
app = web.Application()
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
setup_application(app, dp, bot=bot)

if __name__ == "__main__":
    web.run_app(app, port=int(os.getenv("PORT", 8000)))
