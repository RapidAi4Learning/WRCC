"""Alembic environment — async engine, autogenerate-aware metadata."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db import models  # noqa: F401 - ensure models register on Base.metadata
from app.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# An explicitly supplied URL wins over the environment. `alembic.ini` sets none,
# so in normal use this is always the configured database; a caller that has
# already set one (the migration test, or `-x`) means it.
if not config.get_main_option("sqlalchemy.url", ""):
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


def run_migrations_sync() -> None:
    """The same revisions over a synchronous driver.

    Production is asyncpg, so the async path above is the normal one. A sync
    URL reaches here from the migration test, which runs the revisions against
    SQLite — the only way to assert an upgrade *and* its downgrade without
    standing up Postgres.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )
    with connectable.connect() as connection:
        _do_run_migrations(connection)
    connectable.dispose()


def _is_async_url(url: str) -> bool:
    scheme = url.split("://", 1)[0]
    return "+" in scheme and scheme.split("+", 1)[1] in {
        "asyncpg",
        "aiosqlite",
        "aiomysql",
        "asyncmy",
    }


if context.is_offline_mode():
    run_migrations_offline()
elif _is_async_url(config.get_main_option("sqlalchemy.url", "")):
    asyncio.run(run_migrations_online())
else:
    run_migrations_sync()
