from sqlalchemy.orm import declarative_base

Base = declarative_base()

from . import achievements, database, economy, fire, osu, poll, stocks

__all__ = ["achievements", "database", "economy", "fire", "osu", "poll", "stocks"]
