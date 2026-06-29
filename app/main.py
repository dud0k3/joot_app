import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .bot import bot, dp
from .config import get_settings
from .db import init_db

settings = get_settings()
polling_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global polling_task
    init_db()
    if bot and settings.bot_mode.lower() == "polling":
        with suppress(Exception):
            await bot.set_my_commands([
                BotCommand(command="start", description="🚀 Запустить бота"),
                BotCommand(command="connect", description="🔐 Подключить VPN"),
                BotCommand(command="subscriptions", description="🌍 Подписка"),
                BotCommand(command="profile", description="👤 Профиль"),
                BotCommand(command="help", description="❓ Помощь"),
                BotCommand(command="refresh", description="🔄 Обновить подписку"),
                BotCommand(command="version", description="🧩 Версия"),
            ])
            if settings.app_url.startswith("https://"):
                await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="JOOT VPN", web_app=WebAppInfo(url=settings.app_url)))
        await bot.delete_webhook(drop_pending_updates=False)
        polling_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
    yield
    if polling_task:
        polling_task.cancel()
        with suppress(asyncio.CancelledError):
            await polling_task
    if bot:
        await bot.session.close()


app = FastAPI(title="JOOT VPN", docs_url=None, redoc_url=None, lifespan=lifespan)
app.include_router(router)

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    return response


@app.get("/health")
def health():
    return {"status": "ok", "service": "joot-vpn", "version": settings.build_version}


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    requested = static_dir / path
    if path and requested.exists() and requested.is_file() and static_dir in requested.resolve().parents:
        return FileResponse(requested)
    return FileResponse(static_dir / "index.html")
