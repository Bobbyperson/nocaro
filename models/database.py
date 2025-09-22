from sqlalchemy import Boolean, Column, Integer, String

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


class GuildSettings(Base):
    __tablename__ = "guild_settings"

    guild_id = Column(Integer, primary_key=True)
    markov_enabled = Column(Boolean, default=False)


class MarkovCorpus(Base):
    __tablename__ = "markov_corpus"

    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, nullable=False)
    guild_id = Column(Integer, nullable=False)
    content = Column(String, nullable=False)
    message_id = Column(Integer, nullable=False)


class MarkovOptOut(Base):
    __tablename__ = "markov_opt_out"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, unique=True)
