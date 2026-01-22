from sqlalchemy.orm import declarative_base

Base = declarative_base()

from . import (
    achievements,
    api,
    betting,
    config,
    database,
    economy,
    event,
    fire,
    osu,
    stocks,
)

__all__ = [
    "achievements",
    "api",
    "betting",
    "config",
    "database",
    "economy",
    "event",
    "fire",
    "osu",
    "stocks",
]
