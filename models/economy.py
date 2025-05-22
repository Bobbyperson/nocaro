from sqlalchemy import Column, Integer, String

from . import Base


class Main(Base):
    __tablename__ = "main"

    num = Column(Integer, nullable=False, primary_key=True)
    balance = Column(String, nullable=False, default=0)
    bananas = Column(Integer, nullable=False, default=0)
    user_ID = Column(Integer, nullable=False)
    immunity = Column(Integer, nullable=False)
    level = Column(Integer, nullable=False)
    inventory = Column(String)
    winloss = Column(String)
    invested = Column(String, nullable=False, default=0)


class Prestiege(Base):
    __tablename__ = "prestiege"

    num = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    pres1 = Column(Integer, default=0)
    pres2 = Column(Integer, default=0)
    pres3 = Column(Integer, default=0)
    pres4 = Column(Integer, default=0)
    pres5 = Column(Integer, default=0)


class History(Base):
    __tablename__ = "history"

    num = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    amount = Column(Integer, nullable=False)
    reason = Column(String, nullable=False)
    time = Column(Integer, nullable=False)
