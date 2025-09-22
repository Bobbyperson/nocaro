from sqlalchemy import Column, PickleType, String

from . import Base


class Config(Base):
    __tablename__ = "runtime_config"

    key = Column(String, nullable=False, primary_key=True)
    value = Column(PickleType, nullable=False)
