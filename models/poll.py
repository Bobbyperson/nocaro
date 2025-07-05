from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String

from . import Base


class VoteMultipliers(Base):
    __tablename__ = "vote_multipliers"

    # per-event table
    user_id = Column(Integer, primary_key=True)
    event_id = Column(Integer, primary_key=True)
    attended = Column(Boolean, nullable=False)
    voted_for_winner = Column(Boolean, nullable=False)
    timestamp = Column(DateTime, nullable=False)


class PollState(Base):
    __tablename__ = "poll_state"

    message_id = Column(Integer, primary_key=True)
    options = Column(String, nullable=False)


class Bonuses(Base):
    __tablename__ = "bonuses"

    user_id = Column(Integer, primary_key=True)
    bonus = Column(Float, nullable=False)
