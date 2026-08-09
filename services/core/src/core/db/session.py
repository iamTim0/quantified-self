from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings

# SECURITY M1: SSL is configurable — defaults to False for local dev but should
# be True in production. Set DATABASE_SSL=true env var for encrypted DB traffic.
_db_ssl = getattr(settings, "DATABASE_SSL", False)
connect_args = {
    "ssl": _db_ssl,
}

# Pooled, not `NullPool`.
#
# `NullPool` opens a fresh TCP connection — and, with DATABASE_SSL=true, a fresh
# TLS handshake — for every session, and the ingest consumer opens one session
# **per data point** (`core/events/consumer.py`). An Apple Health batch of fifty
# thousand readings therefore paid fifty thousand connection setups, which cost
# far more than the INSERT they carried. That is the single largest reason a large
# import took minutes.
#
# The pool is sized for the two processes that use it (the API and the consumer)
# rather than for a crowd: a handful of concurrent statements each, with room to
# overflow under a burst. `pool_pre_ping` costs one cheap round trip per checkout
# and is what stops a connection killed by a restart or an idle timeout from
# surfacing as a failed request.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_POOL_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=settings.DATABASE_POOL_RECYCLE_SECONDS,
    connect_args=connect_args,
)

async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
