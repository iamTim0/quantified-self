from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.config import settings

# Use NullPool for asyncpg engine to ensure every request/test gets its own isolated connection
connect_args = {
    "ssl": False,
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
