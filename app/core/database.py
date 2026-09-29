from sqlalchemy import Table, Column
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.database_url,
    poolclass=NullPool,  # Supavisor already pools connections, don't stack a second pool on top
    connect_args={"statement_cache_size": 0},  # asyncpg prepared statements break through the transaction-mode pooler
    echo=False,
)

async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


async def get_db():
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            # Without this a failed request leaves the transaction open and
            # the connection unusable for the next checkout.
            await session.rollback()
            raise


auth_users = Table(
    "users",
    Base.metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    schema="auth",
)
