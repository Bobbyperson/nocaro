from sqlalchemy import Column, Integer, String

from . import Base


class Stocks(Base):
    __tablename__ = "stocks"

    num = Column(Integer, nullable=False, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, unique=True, index=True)
    ticker = Column(String, nullable=False)
    amount = Column(String, nullable=False)
    purchase_price = Column(Integer, nullable=False, default=0)
