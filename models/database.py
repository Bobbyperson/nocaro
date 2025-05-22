from sqlalchemy import Column, Integer

from . import Base


class Messages(Base):
    __tablename__ = "messages"

    num = Column(Integer, nullable=False, primary_key=True)
    messageID = Column(Integer, nullable=False)
    channelID = Column(Integer, nullable=False)
    guildID = Column(Integer, nullable=False)


class Ignore(Base):
    __tablename__ = "ignore"

    num = Column(Integer, nullable=False, primary_key=True)
    channelID = Column(Integer, nullable=False)
    guildID = Column(Integer, nullable=False)


class Blacklist(Base):
    __tablename__ = "blacklist"

    num = Column(Integer, nullable=False, primary_key=True)
    user_id = Column(Integer, nullable=False)
    timestamp = Column(Integer, nullable=False)
