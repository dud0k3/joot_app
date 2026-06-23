from collections.abc import Generator
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()


def normalized_database_url(value: str) -> str:
    value = value.strip()
    if value.startswith("sqlite:///data/"):
        return "sqlite:////data/" + value.removeprefix("sqlite:///data/")
    return value


def sqlite_file_path(value: str) -> Path | None:
    if value.startswith("sqlite:////"):
        return Path("/" + value.removeprefix("sqlite:////"))
    if value.startswith("sqlite:///"):
        return Path(value.removeprefix("sqlite:///"))
    return None


database_url = normalized_database_url(settings.database_url)
sqlite_path = sqlite_file_path(database_url)
if sqlite_path:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(
    database_url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models
    Base.metadata.create_all(engine)
    return None

