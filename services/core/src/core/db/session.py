from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.config import settings

# SECURITY M1: SSL is configurable — defaults to False for local dev but should
# be True in production. Set DATABASE_SSL=true env var for encrypted DB traffic.
_db_ssl = getattr(settings, "DATABASE_SSL", False)
connect_args = {
    "ssl": _db_ssl,
}

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    poolclass=NullPool,
    connect_args=connect_args,
)

async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
