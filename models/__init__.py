from sqlalchemy.orm import declarative_base

Base = declarative_base()

from . import (
    achievements,
    api,
    awards,
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
    "awards",
    "config",
    "database",
    "economy",
    "event",
    "fire",
    "osu",
    "stocks",
]
