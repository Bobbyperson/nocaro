import discord
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String

from . import Base


class EventEntry(Base):
    __tablename__ = "event_entry"

    entry_id = Column(Integer, primary_key=True, autoincrement=True)

    name = Column(String, nullable=False, unique=True)
    weight_value = Column("weight", Float, nullable=False, default=1.0)

    @staticmethod
    def __clamp_weight(weight: float) -> float:
        return max(0.6, min(1.0, weight))

    @property
    def weight(self) -> float:
        return self.__clamp_weight(self.weight_value)

    @weight.setter
    def weight(self, value: float) -> None:
        self.weight_value = self.__clamp_weight(value)


class EventPollState(Base):
    __tablename__ = "event_poll_state"

    message_id = Column(Integer, primary_key=True)
    end_timestamp = Column(DateTime, nullable=False)
    warn_timestamp = Column(DateTime)

    async def get_message(self, channel: discord.abc.Messageable) -> discord.Message:
        return await channel.fetch_message(self.message_id)


class EventMultipliers(Base):
    __tablename__ = "event_multipliers"

    # per-event table
    user_id = Column(Integer, primary_key=True)
    event_id = Column(Integer, primary_key=True)
    attended = Column(Boolean, nullable=False)
    voted_for_winner = Column(Boolean, nullable=False)
    timestamp = Column(DateTime, nullable=False)


class EventBonus(Base):
    __tablename__ = "event_bonus"

    user_id = Column(Integer, primary_key=True)
    bonus = Column(Float, nullable=False, default=0)
