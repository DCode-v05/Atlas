"""Async SQLAlchemy engine + session factory — opt-in Postgres persistence.

Enabled only when ``ATLAS_DATABASE_URL`` is set; otherwise Atlas runs fully
in-memory as before (so the existing test suite and the no-DB demo are unchanged).
Production target is **Postgres** (``asyncpg``); tests use **SQLite** (``aiosqlite``).
The schema is created with ``metadata.create_all`` on first boot — no migration
tool by design (this is an opt-in demo store, not a versioned production schema).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def normalize_url(url: str) -> str:
    """Map common URL forms onto the async drivers Atlas uses."""
    if url.startswith(("postgresql+asyncpg://", "sqlite+aiosqlite://")):
        return url
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    if url.startswith("sqlite://"):
        return "sqlite+aiosqlite://" + url[len("sqlite://"):]
    return url


class Database:
    """A thin handle over an async engine + session factory.

    Constructing it is cheap and does NOT connect — the engine connects lazily on
    first use (``create_all`` / a query), so an inert ``Database`` is safe to build
    in tests that never run the lifespan.
    """

    def __init__(self, url: str) -> None:
        self.url = normalize_url(url)
        kwargs: dict = {}
        if self.url.startswith("sqlite"):
            # one shared connection so an in-memory/file SQLite DB stays coherent across the loop
            from sqlalchemy.pool import StaticPool

            kwargs = {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
        self.engine: AsyncEngine = create_async_engine(self.url, future=True, **kwargs)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_all(self) -> None:
        from atlas.db import models  # noqa: F401 — register models on Base.metadata

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    def session(self) -> AsyncSession:
        return self.sessionmaker()

    async def dispose(self) -> None:
        await self.engine.dispose()
