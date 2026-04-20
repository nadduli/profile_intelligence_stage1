import uuid
from datetime import datetime

import uuid_extensions
from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from .config import get_settings

settings = get_settings()


def _build_engine_url(url: str):
    """Strip libpq-only params asyncpg doesn't support; map sslmode to connect_args."""
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    ssl_required = params.pop("sslmode", [""])[0] in (
        "require",
        "verify-ca",
        "verify-full",
    )
    params.pop("channel_binding", None)
    clean_query = urlencode({k: v[0] for k, v in params.items()})
    clean_url = urlunparse(parsed._replace(query=clean_query))
    connect_args = {"ssl": ssl_required} if ssl_required else {}
    return clean_url, connect_args


_db_url, _connect_args = _build_engine_url(settings.database_url)
engine = create_async_engine(_db_url, echo=settings.debug, connect_args=_connect_args)

SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all database models."""

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return cls.__name__.lower() + "s"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid_extensions.uuid7
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


async def get_db():
    """Get a database session."""
    async with SessionLocal() as db:
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise
