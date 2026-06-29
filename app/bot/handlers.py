from html import escape
from contextlib import suppress

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from ..config import get_settings
from ..db import SessionLocal
from ..services import (
    active_subscription,
    provision_default_subscription,
    refresh_active_subscription,
    refresh_subscription_link_in_place,
    reset_active_subscription_link,
    should_refresh_existing_link,
    upsert_user,
)
from .keyboards import CONNECT_TEXT, HELP_TEXT, PROFILE_TEXT, SUBSCRIPTION_TEXT, main_keyboard, menu_keyboard
from .messages import public_error, send_subscription_message

settings = get_settings()
bot = Bot(settings.bot_token) if settings.bot_token else None
dp = Dispatcher()
router = Router()
dp.include_router(router)


def _is_admin(telegram_id: int | None) -> bool:
    return bool(telegram_id and telegram_id in settings.admins)


async def progress_message(target: Message | CallbackQuery, text: str) -> Message:
    msg = target.message if isinstance(target, CallbackQuery) else target
    if isinstance(target, CallbackQuery):
        with suppress(Exception):
            await target.answer("Готовлю доступ…", show_alert=False)
    return await msg.answer(text)


async def send_connect(target: Message | CallbackQuery) -> None:
    progress = await progress_message(target, "Создаю VPN-доступ. Обычно это занимает 10–30 секунд…")
    with SessionLocal() as db:
        user = upsert_user(db, target.from_user.model_dump())
        if user.is_blocked:
            await progress.edit_text("Ваш аккаунт заблокирован.")
            return
        try:
            sub = await provision_default_subscription(db, user)
        except Exception as error:
            db.rollback()
            await progress.edit_text(f"Не удалось создать VPN-доступ.\n\n{public_error(error, show_details=_is_admin(user.telegram_id) or settings.public_error_details)}")
            return
    await send_subscription_message(progress, sub, edit=True)


async def send_subscription(target: Message | CallbackQuery) -> None:
    msg = target.message if isinstance(target, CallbackQuery) else target
    with SessionLocal() as db:
        user = upsert_user(db, target.from_user.model_dump())
        sub = active_subscription(db, user.id)
        if sub and should_refresh_existing_link(sub):
            try:
                sub = await refresh_subscription_link_in_place(db, user, sub)
            except Exception as error:
                db.rollback()
                await msg.answer(f"Не удалось обновить ссылку подписки.\n\n{public_error(error, show_details=_is_admin(user.telegram_id) or settings.public_error_details)}", reply_markup=menu_keyboard())
                if isinstance(target, CallbackQuery):
                    await target.answer()
                return
    if not sub:
        await msg.answer("Активной подписки пока нет. Нажмите «Подключить VPN».", reply_markup=menu_keyboard())
        if isinstance(target, CallbackQuery):
            await target.answer()
        return
    await send_subscription_message(msg, sub, edit=False)
    if isinstance(target, CallbackQuery):
        await target.answer()


async def send_profile(target: Message | CallbackQuery) -> None:
    msg = target.message if isinstance(target, CallbackQuery) else target
    with SessionLocal() as db:
        user = upsert_user(db, target.from_user.model_dump())
        sub = active_subscription(db, user.id)
    status = "активна" if sub else "нет активной подписки"
    devices = sub.devices if sub else settings.default_subscription_devices
    text = (
        "<b>Профиль JOOT</b>\n\n"
        f"Telegram ID: <code>{user.telegram_id}</code>\n"
        f"Статус: {status}\n"
        f"Устройства: до {devices}\n"
    )
    await msg.answer(text, parse_mode="HTML", reply_markup=menu_keyboard())
    if isinstance(target, CallbackQuery):
        await target.answer()


async def send_help(target: Message | CallbackQuery) -> None:
    msg = target.message if isinstance(target, CallbackQuery) else target
    text = (
        "<b>Как подключиться</b>\n\n"
        "1. Нажмите «Подключить VPN».\n"
        "2. Скопируйте ссылку подписки из сообщения.\n"
        "3. Откройте Happ или Hiddify.\n"
        "4. Добавьте подписку из буфера обмена.\n\n"
        "Одна подписка содержит несколько протоколов и работает максимум на 3 устройствах.\n\n"
        "Бот выдаёт обычную ссылку StealthSurf вида <code>https://connect.stealthsurf.net/to/...</code>. Её нужно скопировать и добавить в Happ/Hiddify как URL подписки."
    )
    await msg.answer(text, parse_mode="HTML", reply_markup=menu_keyboard())
    if isinstance(target, CallbackQuery):
        await target.answer()


async def refresh_subscription(target: Message | CallbackQuery) -> None:
    progress = await progress_message(target, "Обновляю ссылку подписки…")
    with SessionLocal() as db:
        user = upsert_user(db, target.from_user.model_dump())
        try:
            sub = await refresh_active_subscription(db, user)
        except Exception as error:
            db.rollback()
            await progress.edit_text(f"Не удалось обновить подписку.\n\n{public_error(error, show_details=_is_admin(user.telegram_id) or settings.public_error_details)}")
            return
    await send_subscription_message(progress, sub, edit=True)


async def reset_link(target: CallbackQuery) -> None:
    progress = await progress_message(target, "Переиздаю ссылку подписки…")
    with SessionLocal() as db:
        user = upsert_user(db, target.from_user.model_dump())
        try:
            sub = await reset_active_subscription_link(db, user)
        except Exception as error:
            db.rollback()
            await progress.edit_text(f"Не удалось сбросить ссылку.\n\n{public_error(error, show_details=_is_admin(user.telegram_id) or settings.public_error_details)}")
            return
    await send_subscription_message(progress, sub, edit=True)


@router.message(CommandStart())
async def start(message: Message) -> None:
    with SessionLocal() as db:
        upsert_user(db, message.from_user.model_dump())
    await message.answer(
        "<b>JOOT VPN</b>\n\nОдна подписка. Несколько протоколов. До 3 устройств.\n\nВыберите действие на панели ниже.",
        parse_mode="HTML",
        reply_markup=menu_keyboard(),
    )


@router.message(Command("connect"))
async def connect_cmd(message: Message) -> None:
    await send_connect(message)


@router.message(Command("subscriptions"))
@router.message(Command("link"))
async def subscriptions_cmd(message: Message) -> None:
    await send_subscription(message)


@router.message(Command("profile"))
async def profile_cmd(message: Message) -> None:
    await send_profile(message)


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await send_help(message)


@router.message(Command("refresh"))
async def refresh_cmd(message: Message) -> None:
    await refresh_subscription(message)


@router.message(Command("version"))
async def version_cmd(message: Message) -> None:
    await message.answer(f"JOOT build: <code>{escape(settings.build_version)}</code>", parse_mode="HTML", reply_markup=menu_keyboard())


@router.message(F.text == CONNECT_TEXT)
async def connect_button(message: Message) -> None:
    await send_connect(message)


@router.message(F.text == SUBSCRIPTION_TEXT)
async def subscription_button(message: Message) -> None:
    await send_subscription(message)


@router.message(F.text == PROFILE_TEXT)
async def profile_button(message: Message) -> None:
    await send_profile(message)


@router.message(F.text == HELP_TEXT)
async def help_button(message: Message) -> None:
    await send_help(message)


@router.message(F.text)
async def fallback_text(message: Message) -> None:
    await message.answer("Выберите действие на панели ниже.", reply_markup=menu_keyboard())


@router.callback_query(F.data == "connect")
async def connect_callback(callback: CallbackQuery) -> None:
    await send_connect(callback)


@router.callback_query(F.data == "subscription")
async def subscription_callback(callback: CallbackQuery) -> None:
    await send_subscription(callback)


@router.callback_query(F.data == "profile")
async def profile_callback(callback: CallbackQuery) -> None:
    await send_profile(callback)


@router.callback_query(F.data == "help")
async def help_callback(callback: CallbackQuery) -> None:
    await send_help(callback)


@router.callback_query(F.data == "refresh_subscription")
async def refresh_callback(callback: CallbackQuery) -> None:
    await refresh_subscription(callback)


@router.callback_query(F.data == "reset_link")
async def reset_callback(callback: CallbackQuery) -> None:
    await reset_link(callback)


@router.callback_query(F.data == "copy_hint")
async def copy_hint_callback(callback: CallbackQuery) -> None:
    await callback.answer("Скопируйте ссылку из сообщения выше и вставьте её в Happ/Hiddify.", show_alert=True)
