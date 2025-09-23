from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.config import Config


async def get_raw(session: AsyncSession, key: str) -> any:
    return (
        await session.scalars(select(Config).where(Config.key == key))
    ).one_or_none()

async def get(session: AsyncSession, key: str, default: Any = None) -> any:
    entry = await get_raw(session, key)
    if entry is not None:
        entry = entry.value
    else:
        entry = default
    return entry

async def set(session: AsyncSession, key: str, value: any) -> None:
    async with session.begin():
        entry = await get_raw(session, key)

        if value is None and entry is None:
            pass

        elif value is None:
            await session.delete(entry)

        elif entry is None:
            session.add(
                Config(
                    key=key,
                    value=value,
                )
            )

        else:
            entry.value = value
