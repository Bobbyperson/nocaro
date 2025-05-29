from sqlalchemy import Column, Integer, String

from . import Base


class VoteMultipliers(Base):
    __tablename__ = "vote_multipliers"

    user_id = Column(Integer, primary_key=True)
    multiplier = Column(Integer, nullable=False)


class PollState(Base):
    __tablename__ = "poll_state"

    message_id = Column(Integer, primary_key=True)
    options = Column(String, nullable=False)
