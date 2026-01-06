from sqlalchemy import Column, Integer, String

from . import Base


class AwardUsers(Base):
    __tablename__ = "award_users"

    user_id = Column(String, primary_key=True)


class Votes(Base):
    __tablename__ = "voting"

    num = Column(Integer, nullable=False, primary_key=True, autoincrement=True)
    user_id = Column(String)
    question = Column(String)
    answer = Column(Integer)
