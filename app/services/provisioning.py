import asyncio
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .. import models
from ..config import get_settings
from ..providers import get_vpn_provider
from ..providers.base import VpnAccess

_provision_locks: dict[int, asyncio.Lock] = {}


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _lock_for_user(telegram_id: int) -> asyncio.Lock:
    lock = _provision_locks.get(telegram_id)
    if lock is None:
        lock = asyncio.Lock()
        _provision_locks[telegram_id] = lock
    return lock


def upsert_user(db: Session, tg: dict) -> models.User:
    telegram_id = int(tg.get("id") or tg.get("telegram_id"))
    user = db.query(models.User).filter_by(telegram_id=telegram_id).first()
    if not user:
        user = models.User(telegram_id=telegram_id)
        db.add(user)
    user.username = tg.get("username")
    user.first_name = (tg.get("first_name") or "")[:128]
    user.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user




def is_stealthsurf_plain_subscription_url(value: str | None) -> bool:
    value = (value or "").strip().lower()
    return value.startswith(("https://connect.stealthsurf.net/to/", "http://connect.stealthsurf.net/to/"))


def is_stealthsurf_custom_scheme(value: str | None) -> bool:
    value = (value or "").strip().lower()
    return value.startswith(("happ://", "hiddify://", "vless://", "trojan://", "ss://", "hysteria2://"))


def should_refresh_existing_link(subscription: models.Subscription) -> bool:
    provider = (subscription.provider or get_settings().vpn_provider or "").lower().replace("-", "").replace("_", "")
    if provider not in {"stealthsurf", "stealsurf", "stealth"}:
        return False
    if not subscription.external_subscription_id:
        return False
    if not subscription.access_url:
        return True
    # Old builds stored happ://crypt5/...; Happ rejects it as a subscription URL.
    # Force-refresh to the normal console URL: https://connect.stealthsurf.net/to/<token>.
    return not is_stealthsurf_plain_subscription_url(subscription.access_url)


async def refresh_subscription_link_in_place(db: Session, user: models.User, subscription: models.Subscription) -> models.Subscription:
    provider = get_vpn_provider()
    subscription.access_url = await provider.get_subscription_link(str(subscription.external_subscription_id))
    subscription.provider = "stealthsurf"
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription


def subscription_config_ids(subscription: models.Subscription) -> list[int]:
    raw = subscription.external_config_ids or ""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        data = []
    if not isinstance(data, list):
        return []
    result: list[int] = []
    for item in data:
        if isinstance(item, int):
            result.append(item)
        elif str(item).isdigit():
            result.append(int(item))
    return result


def should_rebuild_existing_subscription(subscription: models.Subscription) -> bool:
    settings = get_settings()
    provider = (subscription.provider or settings.vpn_provider or "").lower().replace("-", "").replace("_", "")
    if provider not in {"stealthsurf", "stealsurf", "stealth"}:
        return False
    if not settings.stealthsurf_use_joot_bundle:
        return False
    return len(subscription_config_ids(subscription)) < int(settings.stealthsurf_expected_config_count or 8)


async def rebuild_subscription_in_place(db: Session, user: models.User, subscription: models.Subscription) -> models.Subscription:
    settings = get_settings()
    vpn = await get_vpn_provider().create_or_extend(
        username=subscription.external_username or f"tg_{user.telegram_id}",
        expires_at=aware(subscription.expires_at),
        traffic_gb=subscription.traffic_gb or settings.default_subscription_traffic_gb,
        devices=subscription.devices or settings.default_subscription_devices or settings.stealthsurf_device_limit or 3,
    )
    _apply_vpn_access(subscription, vpn)
    subscription.status = "active"
    subscription.devices = subscription.devices or settings.default_subscription_devices or settings.stealthsurf_device_limit or 3
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription

def active_subscription(db: Session, user_id: int) -> models.Subscription | None:
    now = datetime.now(timezone.utc)
    return (
        db.query(models.Subscription)
        .filter(
            models.Subscription.user_id == user_id,
            models.Subscription.status == "active",
            models.Subscription.expires_at > now,
        )
        .order_by(models.Subscription.expires_at.desc())
        .first()
    )


def _apply_vpn_access(subscription: models.Subscription, vpn: VpnAccess) -> None:
    subscription.external_username = vpn.username
    subscription.access_url = vpn.access_url
    subscription.provider = vpn.provider or get_settings().vpn_provider
    if vpn.external_subscription_id:
        subscription.external_subscription_id = str(vpn.external_subscription_id)
    if vpn.external_config_ids is not None:
        subscription.external_config_ids = json.dumps(vpn.external_config_ids)


async def _create_new_subscription(db: Session, user: models.User) -> models.Subscription:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=settings.default_subscription_days)
    devices = settings.default_subscription_devices or settings.stealthsurf_device_limit or 3
    username = f"tg_{user.telegram_id}"

    vpn = await get_vpn_provider().create_or_extend(
        username=username,
        expires_at=expires,
        traffic_gb=settings.default_subscription_traffic_gb,
        devices=devices,
    )

    subscription = models.Subscription(
        user_id=user.id,
        status="active",
        provider=vpn.provider or settings.vpn_provider,
        external_username=vpn.username,
        access_url=vpn.access_url,
        traffic_gb=settings.default_subscription_traffic_gb,
        devices=devices,
        starts_at=now,
        expires_at=expires,
    )
    _apply_vpn_access(subscription, vpn)
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription


async def provision_default_subscription(db: Session, user: models.User) -> models.Subscription:
    async with _lock_for_user(user.telegram_id):
        existing = active_subscription(db, user.id)
        if existing:
            if should_rebuild_existing_subscription(existing):
                return await rebuild_subscription_in_place(db, user, existing)
            if should_refresh_existing_link(existing):
                return await refresh_subscription_link_in_place(db, user, existing)
            if existing.access_url:
                return existing
        return await _create_new_subscription(db, user)


async def refresh_active_subscription(db: Session, user: models.User) -> models.Subscription:
    subscription = active_subscription(db, user.id)
    if not subscription:
        raise ValueError("No active subscription")

    provider = get_vpn_provider()
    if should_rebuild_existing_subscription(subscription):
        return await rebuild_subscription_in_place(db, user, subscription)

    if subscription.external_subscription_id:
        try:
            subscription.access_url = await provider.get_subscription_link(str(subscription.external_subscription_id))
            if is_stealthsurf_custom_scheme(subscription.access_url):
                raise RuntimeError("StealthSurf returned encrypted happ:// link instead of normal connect.stealthsurf.net subscription URL")
            db.add(subscription)
            db.commit()
            db.refresh(subscription)
            return subscription
        except NotImplementedError:
            pass

    vpn = await provider.create_or_extend(
        username=subscription.external_username or f"tg_{user.telegram_id}",
        expires_at=aware(subscription.expires_at),
        traffic_gb=subscription.traffic_gb,
        devices=subscription.devices,
    )
    _apply_vpn_access(subscription, vpn)
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription


async def reset_active_subscription_link(db: Session, user: models.User) -> models.Subscription:
    subscription = active_subscription(db, user.id)
    if not subscription:
        raise ValueError("No active subscription")
    if not subscription.external_subscription_id:
        raise ValueError("Subscription link reset is available only for custom subscriptions")

    subscription.access_url = await get_vpn_provider().reset_subscription_link(str(subscription.external_subscription_id))
    if is_stealthsurf_custom_scheme(subscription.access_url):
        raise RuntimeError("StealthSurf returned encrypted happ:// link instead of normal connect.stealthsurf.net subscription URL")
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription
