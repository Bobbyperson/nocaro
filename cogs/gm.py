import logging
import random as rd

from discord.ext import commands

log = logging.getLogger(__name__)

class GM(commands.Cog):
    def __init__(self, client):
        self.client = client

    # events
    @commands.Cog.listener()
    async def on_ready(self):
        log.info("GM ready")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        if message.content:
            msg = str.lower(message.content)
            gm = rd.randint(1, 12)
            if gm == 1:
                if message.author == self.client.user:
                    return
                if message.attachments:
                    return
                elif msg == str.lower("g"):
                    return
                elif msg[0] == "g":
                    if len(msg) == 2:
                        await message.reply(f"Giant {msg[1]}ario")
                    elif msg[1] == "<" and msg[-1] == ">":
                        await message.reply(f"Giant {msg[1:]}ario")


async def setup(client):
    await client.add_cog(GM(client))
