from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool
from app.core.config import settings
from sqlalchemy import Table, Column
from sqlalchemy.dialects.postgresql import UUID as PGUUID

class Base(DeclarativeBase):
    pass

engine = create_async_engine(
    settings.database_url,
    poolclass=NullPool,  # Supavisor already pools connections, don't stack a second pool on top
    connect_args={"statement_cache_size": 0},  # required: asyncpg's prepared statements don't work through the transaction-mode pooler
)

async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

async def get_db():
    async with async_session_maker() as session:
        yield session



auth_users = Table(
    "users",
    Base.metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    schema="auth",
)