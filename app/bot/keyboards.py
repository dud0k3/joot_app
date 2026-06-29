from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from ..config import get_settings

CONNECT_TEXT = "🔐 Подключить VPN"
SUBSCRIPTION_TEXT = "🌍 Подписка"
PROFILE_TEXT = "👤 Профиль"
HELP_TEXT = "❓ Помощь"

TELEGRAM_ALLOWED_URL_PREFIXES = ("https://", "http://", "tg://")


def telegram_safe_url(url: str | None) -> str | None:
    value = (url or "").strip()
    if not value or "\n" in value or len(value) > 2048:
        return None
    if value.lower().startswith(TELEGRAM_ALLOWED_URL_PREFIXES):
        return value
    return None


def menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=CONNECT_TEXT), KeyboardButton(text=SUBSCRIPTION_TEXT)],
            [KeyboardButton(text=PROFILE_TEXT), KeyboardButton(text=HELP_TEXT)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def main_keyboard() -> InlineKeyboardMarkup:
    settings = get_settings()
    rows = [
        [InlineKeyboardButton(text=CONNECT_TEXT, callback_data="connect")],
        [InlineKeyboardButton(text=SUBSCRIPTION_TEXT, callback_data="subscription")],
        [InlineKeyboardButton(text=PROFILE_TEXT, callback_data="profile"), InlineKeyboardButton(text=HELP_TEXT, callback_data="help")],
    ]
    if settings.support_contact:
        rows.append([InlineKeyboardButton(text="Поддержка", url=f"https://t.me/{settings.support_contact}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def access_keyboard(url: str | None = None, allow_reset: bool = False) -> InlineKeyboardMarkup:
    # Telegram URL-кнопку для подписки намеренно не показываем.
    # Пользователь копирует ссылку из сообщения или Mini App; так меньше ошибок
    # с открытием клиентов и custom/deep-link схемами.
    rows = [
        [InlineKeyboardButton(text="🔄 Обновить подписку", callback_data="refresh_subscription")],
    ]
    if url and allow_reset:
        rows.append([InlineKeyboardButton(text="🔐 Сбросить ссылку", callback_data="reset_link")])
    rows.append([InlineKeyboardButton(text="❓ Инструкция", callback_data="help")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
