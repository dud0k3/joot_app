from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..auth import telegram_user
from ..config import get_settings
from ..db import get_db
from ..services import (
    active_subscription,
    aware,
    provision_default_subscription,
    refresh_active_subscription,
    reset_active_subscription_link,
    upsert_user,
)

router = APIRouter(prefix="/api")
settings = get_settings()


def current_user(tg: dict = Depends(telegram_user), db: Session = Depends(get_db)) -> models.User:
    user = upsert_user(db, tg)
    if user.is_blocked:
        raise HTTPException(403, "Account is blocked")
    return user


def admin_user(tg: dict = Depends(telegram_user), db: Session = Depends(get_db)) -> models.User:
    user = upsert_user(db, tg)
    if user.telegram_id not in settings.admins:
        raise HTTPException(403, "Admin access required")
    return user


def iso(value):
    return aware(value).isoformat() if value else None


def subscription_json(sub: models.Subscription | None) -> dict | None:
    if not sub:
        return None
    now = datetime.now(timezone.utc)
    active = sub.status == "active" and aware(sub.expires_at) > now
    return {
        "id": sub.id,
        "status": "active" if active else "expired",
        "access_url": sub.access_url,
        "starts_at": iso(sub.starts_at),
        "expires_at": iso(sub.expires_at),
        "traffic_gb": sub.traffic_gb,
        "devices": sub.devices,
        "provider": sub.provider,
        "external_subscription_id": sub.external_subscription_id,
        "days_left": max(0, (aware(sub.expires_at) - now).days),
    }


def provisioning_error(error: Exception, user: models.User) -> str:
    detail = str(error).strip() or type(error).__name__
    if settings.dev_mode or settings.public_error_details or user.telegram_id in settings.admins:
        return detail[:3000]
    return "VPN service is temporarily unavailable"


@router.get("/version")
def version():
    return {"service": "joot-vpn", "version": settings.build_version}


@router.get("/bootstrap")
def bootstrap(user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    sub = active_subscription(db, user.id)
    return {
        "brand": "JOOT VPN",
        "user": {"telegram_id": user.telegram_id, "first_name": user.first_name, "username": user.username},
        "is_admin": user.telegram_id in settings.admins,
        "subscription": subscription_json(sub),
        "support_username": settings.support_contact,
        "vpn_provider": settings.vpn_provider,
        "default_devices": settings.default_subscription_devices,
        "default_days": settings.default_subscription_days,
    }


@router.post("/connect")
async def connect(user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        sub = await provision_default_subscription(db, user)
    except Exception as error:
        raise HTTPException(502, provisioning_error(error, user))
    return subscription_json(sub)


@router.post("/subscription/refresh")
async def refresh(user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        sub = await refresh_active_subscription(db, user)
    except ValueError as error:
        raise HTTPException(404, str(error))
    except Exception as error:
        raise HTTPException(502, provisioning_error(error, user))
    return subscription_json(sub)


@router.post("/subscription/reset-link")
async def reset_link(user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        sub = await reset_active_subscription_link(db, user)
    except ValueError as error:
        raise HTTPException(400, str(error))
    except Exception as error:
        raise HTTPException(502, provisioning_error(error, user))
    return subscription_json(sub)


@router.get("/admin/stats")
def admin_stats(admin: models.User = Depends(admin_user), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    users = db.query(func.count(models.User.id)).scalar() or 0
    active = db.query(func.count(models.Subscription.id)).filter(
        models.Subscription.status == "active",
        models.Subscription.expires_at > now,
    ).scalar() or 0
    return {"users": users, "active_subscriptions": active, "admin": admin.telegram_id}
