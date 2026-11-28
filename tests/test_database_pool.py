"""DB_POOL: how database connections are made (app/core/database.py).

The default must stay exactly what ran in production until 28 Nov 2026
(NullPool, asyncpg's statement cache off), so nothing changes until the owner
sets DB_POOL=queue on Render. The reused-connection settings were load-tested
against Postgres behind PgBouncer in transaction mode (handover, 28 Nov 2026).
"""
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

from app.core.config import Settings
from app.core.database import engine_options, pool_mode

URL = "postgresql+asyncpg://user:pass@127.0.0.1:6543/postgres"


def test_by_default_every_request_gets_a_new_connection_as_before():
    assert Settings.model_fields["db_pool"].default == "null"
    assert engine_options("null") == {"poolclass": NullPool, "connect_args": {"statement_cache_size": 0}}


def test_only_queue_turns_reuse_on_and_anything_odd_means_off():
    assert pool_mode("queue") == "queue"
    assert pool_mode("  QUEUE ") == "queue"
    for odd in (None, "", "null", "yes", "true", "pool", "quuee"):
        assert pool_mode(odd) == "null", odd


def test_reused_connections_never_keep_a_statement_past_its_transaction():
    o = engine_options("queue")
    args = o["connect_args"]
    assert args["statement_cache_size"] == 0, "asyncpg's cache: with it off, statements are unnamed"
    assert args["prepared_statement_cache_size"] == 0, "SQLAlchemy's cache"
    # Named statements were left behind on the pooler's database connections
    # (about 160 each after 600 requests in the load test, and growing).
    assert "prepared_statement_name_func" not in args
    assert o["pool_pre_ping"] is True, "a connection that died while Render slept is replaced"
    assert o["pool_recycle"] <= 600


def test_the_pool_stays_small_and_a_burst_does_not_queue_for_long():
    o = engine_options("queue")
    assert o["pool_size"] == 3 and o["max_overflow"] == 10 and o["pool_timeout"] <= 30
    assert engine_options("queue", 0)["pool_size"] == 1
    assert engine_options("queue", 50)["pool_size"] == 10
    # Render runs 2 workers: never more than 2 x (10 + 10) connections at the pooler.
    assert 2 * (engine_options("queue", 99)["pool_size"] + o["max_overflow"]) <= 40


def test_sqlalchemy_accepts_both_sets_of_options_without_connecting():
    null = create_async_engine(URL, **engine_options("null"))
    queue = create_async_engine(URL, **engine_options("queue"))
    try:
        assert isinstance(null.sync_engine.pool, NullPool)
        assert isinstance(queue.sync_engine.pool, AsyncAdaptedQueuePool)
        assert queue.sync_engine.pool.size() == 3
    finally:
        null.sync_engine.dispose()
        queue.sync_engine.dispose()
