from sqlalchemy import Column, Integer, String

from . import Base


class Fire(Base):
    __tablename__ = "fire"

    num = Column(Integer, nullable=False, primary_key=True, autoincrement=True)
    reacts = Column(Integer, nullable=False)
    channel_id = Column(Integer, nullable=False)
    message_id = Column(Integer, nullable=False)
    guild_id = Column(Integer, nullable=False)
    user_id = Column(Integer, nullable=False)
    fb_id = Column(Integer, nullable=False)
    message = Column(String)
    attachments = Column(String)
    timestamp = Column(Integer, nullable=False, default=0)
    fb_msg_id = Column(Integer)
    emoji = Column(String, nullable=False, default="fire")


class Misc(Base):
    __tablename__ = "misc"

    num = Column(Integer, nullable=False, primary_key=True, autoincrement=True)
    pointer = Column(String, nullable=False)
    data = Column(Integer, nullable=False)
