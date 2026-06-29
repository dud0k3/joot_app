from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


SQLITE_MISSING_COLUMNS: dict[str, dict[str, str]] = {
    "users": {
        "username": "TEXT",
        "first_name": "TEXT",
        "is_blocked": "BOOLEAN NOT NULL DEFAULT 0",
        "last_seen_at": "DATETIME",
    },
    "subscriptions": {
        "status": "VARCHAR(32) NOT NULL DEFAULT 'active'",
        "provider": "VARCHAR(64) NOT NULL DEFAULT 'stealthsurf'",
        "external_username": "VARCHAR(128)",
        "external_subscription_id": "VARCHAR(128)",
        "external_config_ids": "TEXT",
        "access_url": "TEXT",
        "traffic_gb": "INTEGER NOT NULL DEFAULT 0",
        "devices": "INTEGER NOT NULL DEFAULT 3",
        "starts_at": "DATETIME",
        "expires_at": "DATETIME",
    },
    "audit_logs": {
        "actor_telegram_id": "INTEGER",
        "action": "VARCHAR(128) NOT NULL DEFAULT 'unknown'",
        "details": "TEXT",
        "created_at": "DATETIME DEFAULT CURRENT_TIMESTAMP",
    },
}


def _sqlite_db_path() -> Path | None:
    if not settings.database_url.startswith("sqlite"):
        return None
    if settings.database_url.startswith("sqlite:////"):
        return Path(settings.database_url.replace("sqlite:///", "", 1))
    if settings.database_url.startswith("sqlite:///"):
        return Path(settings.database_url.replace("sqlite:///", "", 1))
    return None


def _ensure_sqlite_parent_dir() -> None:
    db_path = _sqlite_db_path()
    if db_path:
        db_path.parent.mkdir(parents=True, exist_ok=True)


def _upgrade_sqlite_schema(db_engine: Engine) -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    with db_engine.begin() as connection:
        inspector = inspect(connection)
        for table_name, columns in SQLITE_MISSING_COLUMNS.items():
            if not inspector.has_table(table_name):
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, ddl in columns.items():
                if column_name in existing:
                    continue
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))


def init_db() -> None:
    _ensure_sqlite_parent_dir()
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _upgrade_sqlite_schema(engine)


def get_db():
    # Extra safety for Dockhost: if an old /data/joot.db is mounted, make sure
    # schema is upgraded before every API request. This is cheap and idempotent.
    init_db()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
