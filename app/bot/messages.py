from html import escape

from aiogram.types import InlineKeyboardMarkup, Message, ReplyKeyboardMarkup

from .. import models
from .keyboards import access_keyboard, telegram_safe_url

TELEGRAM_TEXT_LIMIT = 4096
SAFE_MESSAGE_LIMIT = 3600


def public_error(error: Exception, *, show_details: bool = False) -> str:
    detail = str(error).strip() or type(error).__name__
    if show_details:
        return detail[:3500]
    return "Сервис выдачи VPN временно недоступен. Попробуйте позже или напишите в поддержку."


def _access_label(access_url: str | None) -> tuple[str, str]:
    if not access_url:
        return "Ссылка пока не получена.", ""
    if "\n" in access_url:
        return "Ваши конфиги для подключения:", "\n\nСкопируйте нужный конфиг и добавьте его в Happ/Hiddify."
    if telegram_safe_url(access_url):
        return "Ваша ссылка для подключения:", "\n\nСкопируйте ссылку вручную или через Mini App."
    scheme = access_url.split(":", 1)[0].lower() if ":" in access_url else "vpn"
    return (
        "Ваша ссылка для подключения:",
        f"\n\nЭто ссылка формата <b>{escape(scheme)}</b>. Telegram не разрешает открывать такие ссылки кнопкой, поэтому скопируйте её из блока выше и вставьте в Happ/Hiddify.",
    )


def subscription_text(sub: models.Subscription, include_access: bool = True) -> str:
    traffic = "безлимит" if not sub.traffic_gb else f"{sub.traffic_gb} ГБ"
    label, note = _access_label(sub.access_url)
    text = (
        "<b>JOOT VPN</b>\n\n"
        "✅ Подписка активна\n"
        f"📱 Устройства: до {sub.devices}\n"
        f"📦 Трафик: {traffic}\n\n"
        f"{label}"
    )
    if include_access and sub.access_url:
        text += f"\n\n<code>{escape(sub.access_url)}</code>"
    text += note
    return text


def split_plain_text(value: str, chunk_size: int = SAFE_MESSAGE_LIMIT) -> list[str]:
    value = value or ""
    if len(value) <= chunk_size:
        return [value]
    chunks: list[str] = []
    current = ""
    for line in value.splitlines(keepends=True):
        if len(current) + len(line) <= chunk_size:
            current += line
            continue
        if current:
            chunks.append(current)
            current = ""
        while len(line) > chunk_size:
            chunks.append(line[:chunk_size])
            line = line[chunk_size:]
        current = line
    if current:
        chunks.append(current)
    return chunks


async def send_or_edit(msg: Message, text: str, *, edit: bool, reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | None = None) -> None:
    if edit:
        try:
            await msg.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
            return
        except Exception:
            pass
    await msg.answer(text, parse_mode="HTML", reply_markup=reply_markup)


async def send_subscription_message(msg: Message, sub: models.Subscription, *, edit: bool = False) -> None:
    access_url = sub.access_url or ""
    full_text = subscription_text(sub, include_access=True)
    keyboard = access_keyboard(access_url, bool(sub.external_subscription_id))

    if len(full_text) <= TELEGRAM_TEXT_LIMIT:
        await send_or_edit(msg, full_text, edit=edit, reply_markup=keyboard)
        return

    await send_or_edit(msg, subscription_text(sub, include_access=False), edit=edit, reply_markup=keyboard)
    for index, chunk in enumerate(split_plain_text(access_url), start=1):
        suffix = f"\n\nЧасть {index}" if len(access_url) > SAFE_MESSAGE_LIMIT else ""
        await msg.answer(f"<code>{escape(chunk)}</code>{suffix}", parse_mode="HTML")
