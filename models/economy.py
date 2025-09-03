from sqlalchemy import Boolean, Column, Integer, String

from . import Base


class Main(Base):
    __tablename__ = "main"

    num = Column(Integer, nullable=False, primary_key=True, autoincrement=True)
    balance = Column(String, nullable=False, default=0)
    bananas = Column(Integer, nullable=False, default=0)
    user_ID = Column(Integer, nullable=False, unique=True, index=True)
    immunity = Column(Integer, nullable=False, default=0)
    level = Column(Integer, nullable=False, default=0)
    inventory = Column(String)
    winloss = Column(String)
    invested = Column(String, nullable=False, default=0)
    api_consent = Column(Boolean, nullable=False, default=False)


class Prestiege(Base):
    __tablename__ = "prestiege"

    num = Column(Integer, nullable=False, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, unique=True, index=True)
    pres1 = Column(Integer, default=0)
    pres2 = Column(Integer, default=0)
    pres3 = Column(Integer, default=0)
    pres4 = Column(Integer, default=0)
    pres5 = Column(Integer, default=0)


class History(Base):
    __tablename__ = "history"

    num = Column(Integer, nullable=False, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    amount = Column(String, nullable=False)
    reason = Column(String, nullable=False)
    time = Column(Integer, nullable=False)
