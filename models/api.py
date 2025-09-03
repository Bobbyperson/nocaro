from sqlalchemy import Boolean, Column, String

from . import Base


class Api(Base):
    __tablename__ = "api_keys"

    api_key = Column(String, primary_key=True)
    can_write = Column(Boolean, nullable=False)
