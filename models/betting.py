import discord
from sqlalchemy import Column, Integer, String

from . import Base


class BetOptions(Base):
    __tablename__ = "bet_options"

    index = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)


class BetEntries(Base):
    __tablename__ = "bet_entries"

    option_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, primary_key=True)
    balance = Column(String, nullable=False, default=0)


class BetState(Base):
    __tablename__ = "bet_state"

    message_id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, primary_key=True)

    async def get_message(self, bot: discord.Client) -> discord.Message:
        channel = self.get_channel(bot)
        return await channel.fetch_message(self.message_id)

    async def get_channel(self, bot: discord.Client) -> discord.abc.GuildChannel:
        return bot.get_channel(self.channel_id)
