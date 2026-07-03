from sqlalchemy import Boolean, Column, Integer, String

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


class Nominations(Base):
    __tablename__ = "nominations"

    num = Column(Integer, nullable=False, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False)
    question = Column(String, nullable=False)
    answer = Column(String, nullable=False)
    half = Column(Boolean, nullable=False, default=False)
