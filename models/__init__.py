from sqlalchemy.orm import declarative_base

Base = declarative_base()

from . import achievements, api, config, database, economy, fire, osu, stocks

__all__ = [
    "achievements",
    "api",
    "config",
    "database",
    "economy",
    "fire",
    "osu",
    "stocks",
]
