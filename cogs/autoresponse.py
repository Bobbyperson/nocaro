import logging
import random

import discord
import emoji
from discord.ext import commands
from sqlalchemy import select

import models
from utils.miscfuncs import is_blacklisted

log = logging.getLogger(__name__)

class Autoresponse(commands.Cog):
    def __init__(self, client):
        self.client = client

    # events
    @commands.Cog.listener()
    async def on_ready(self):
        log.info("autoresponse ready")

    async def check_ignored(self, channel):
        async with self.client.session as session:
            return (
                await session.scalars(
                    select(models.database.Ignore).where(
                        models.database.Ignore.channelID == channel.id
                    )
                )
            ).one_or_none() is not None

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.client.user:
            return
        if message.author.bot:
            return
        if await self.check_ignored(message.channel):
            return
        if self.client.user.mentioned_in(message):
            await message.channel.send(message.author.mention)
        if not message.content:
            return
        blacklisted = await is_blacklisted(message.author.id)
        if blacklisted[0]:
            return

        if "touhou" in str.lower(message.content):
            await message.channel.send("toe hoe")
        elif "owo" == str.lower(message.content):
            await message.channel.send("uwu")
        elif "uwu" == str.lower(message.content):
            await message.channel.send("owo")
        elif "pandavert" in str.lower(message.content):
            await message.channel.send(":panda_face:")
        elif "sponsor" in str.lower(message.content):
            await message.channel.send(
                "today's annoying auto response message is sponsored by RAID: Shadow Legends."
            )
        elif "min min" in str.lower(message.content):
            await message.channel.send("i fucking hate min min")
        elif "hate these autoresponses" in str.lower(message.content):
            await message.channel.send("oh yeah? i don't like you either buster")
        elif "quack" in str.lower(message.content):
            await message.channel.send("quack")
        elif "ryan gosling" in str.lower(message.content):
            await message.channel.send("he's literally me")
        elif "jackbox" in str.lower(message.content):
            jackbox = "<:GO:893517923472277536>"
            await message.add_reaction(jackbox)
        elif "pick it up" in str.lower(message.content):
            await message.channel.send("SKAAAAAAAAAA!")

        if random.randint(1, 500) != 1:
            return

        emoji_type = random.randint(1, 2)

        default_emojis_maybe = list(
            emoji.EMOJI_DATA.keys()
        )  # includes emojis that discord does not have
        guild_emojis = message.guild.emojis

        if emoji_type == 1 and guild_emojis:
            random_emoji = random.choice(guild_emojis)
            await message.add_reaction(random_emoji)
        elif emoji_type == 2:
            done = False
            while not done:
                try:  # keep trying until we get a valid emoji
                    random_emoji = random.choice(default_emojis_maybe)
                    await message.add_reaction(random_emoji)
                    done = True
                except discord.HTTPException:
                    pass


async def setup(client):
    await client.add_cog(Autoresponse(client))
