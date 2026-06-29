import hashlib
import hmac
import time
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException, Request

from .config import get_settings


def _secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def parse_and_validate_init_data(init_data: str) -> dict:
    settings = get_settings()
    if settings.dev_mode and not init_data:
        return {"id": 861098409, "first_name": "Dev", "username": "dev"}
    if not settings.bot_token:
        raise HTTPException(500, "BOT_TOKEN is not configured")
    if not init_data:
        raise HTTPException(401, "Telegram initData is required")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", "")
    if not received_hash:
        raise HTTPException(401, "Telegram initData hash is missing")

    data_check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    calculated = hmac.new(_secret_key(settings.bot_token), data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        raise HTTPException(401, "Telegram initData hash is invalid")

    auth_date = int(pairs.get("auth_date") or 0)
    max_age = int(settings.telegram_initdata_max_age_seconds or 0)
    if max_age > 0 and auth_date and time.time() - auth_date > max_age:
        raise HTTPException(401, "Telegram initData is expired")

    import json
    raw_user = pairs.get("user") or "{}"
    try:
        user = json.loads(raw_user)
    except json.JSONDecodeError as error:
        raise HTTPException(401, "Telegram user payload is invalid") from error
    if not user.get("id"):
        raise HTTPException(401, "Telegram user id is missing")
    return user


async def telegram_user(
    request: Request,
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
    authorization: str | None = Header(default=None),
) -> dict:
    init_data = x_telegram_init_data or ""
    if not init_data and authorization and authorization.lower().startswith("tma "):
        init_data = authorization[4:].strip()
    if not init_data:
        init_data = request.query_params.get("initData", "")
    return parse_and_validate_init_data(init_data)
