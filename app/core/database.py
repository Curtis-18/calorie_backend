import logging

from sqlalchemy import Table, Column
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import settings

log = logging.getLogger("calorie_backend")


class Base(DeclarativeBase):
    pass


def engine_options(mode: str, pool_size: int = 3) -> dict:
    """How connections are made, by the DB_POOL setting.

    "null" (default): a new connection for every request (NullPool). Supabase's
    pooler (Supavisor, transaction mode, port 6543) pools for us; each request
    pays about 1 s to connect, measured on the live server.

    "queue": a few connections kept open per worker and reused, which saves
    that second. Safe behind a transaction-mode pooler because no prepared
    statement outlives its transaction: with asyncpg's statement cache off,
    asyncpg uses unnamed statements, and SQLAlchemy's own statement cache is
    off too. pre_ping replaces a connection that died while Render slept;
    recycle drops old ones. Some routes hold their connection while waiting
    on Gemini, so a burst gets up to 10 extra connections that close after
    use (as with NullPool) instead of queueing: at most 13 per worker, 26
    for Render's 2 workers.

    Tested 28 Nov 2026 against a local Postgres 16 behind PgBouncer 1.26 in
    transaction mode (prepared-statement tracking off, round-robin, 2 server
    connections, 2 processes, 600 requests 20 at a time, every answer
    checked): no errors or wrong answers, and it recovered after the pooler
    restarted. DON'T add `prepared_statement_name_func` (SQLAlchemy's
    PgBouncer tip): named statements were left behind on the database's
    connections, about 160 each after 600 requests and growing. Unnamed left 0.

    Anything else means "null", so a typo can never take the server down.
    """
    connect_args = {"statement_cache_size": 0}  # asyncpg: no cache, so unnamed statements
    if mode == "queue":
        return {
            "pool_size": max(1, min(pool_size, 10)),
            "max_overflow": 10,
            "pool_pre_ping": True,
            "pool_recycle": 300,
            "pool_timeout": 30,
            "connect_args": {**connect_args, "prepared_statement_cache_size": 0},  # SQLAlchemy's cache
        }
    return {"poolclass": NullPool, "connect_args": connect_args}


def pool_mode(value: str | None) -> str:
    """The DB_POOL setting, read forgivingly: only "queue" turns reuse on."""
    mode = (value or "null").strip().lower()
    if mode not in ("null", "queue"):
        log.warning("DB_POOL=%r is not a known value; using null", value)
        return "null"
    return mode


_mode = pool_mode(settings.db_pool)
log.info("database connections: %s", _mode)

engine = create_async_engine(settings.database_url, echo=False, **engine_options(_mode, settings.db_pool_size))

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
