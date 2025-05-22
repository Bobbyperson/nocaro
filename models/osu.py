from sqlalchemy import Column, Integer, String

from . import Base


class Osu(Base):
    __tablename__ = "osu"

    num = Column(Integer, nullable=False, primary_key=True)
    user_id = Column(Integer, nullable=False)
    score = Column(Integer, nullable=False)
    timestamp = Column(Integer, nullable=False)
    amount = Column(Integer, nullable=False)
    osu_user = Column(Integer, nullable=False)


class OsuUsers(Base):
    __tablename__ = "osu_users"

    num = Column(Integer, nullable=False, primary_key=True)
    osu_username = Column(String, nullable=False)
    osu_id = Column(Integer, nullable=False)
