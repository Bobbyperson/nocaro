import asyncio
from logging.config import fileConfig

from sqlalchemy.engine import Connection

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from models import Base

# this is the base we work with
# changs made to it will be compared to the actual database
target_metadata = Base.metadata

from bot import engine


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    global engine

    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await engine.dispose()


async def bla() -> None:
    async with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


run_migrations_online()
