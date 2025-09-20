import asyncio
import logging
import random
import time

import discord
import discord.ext
from discord.ext import commands
from sqlalchemy import delete, select

import models
import utils.miscfuncs as mf

log = logging.getLogger(__name__)

class database(commands.Cog):
    """Commands which utilize a message database."""

    def __init__(self, client):
        self.client = client
        self.nocaro_cooldowns = {}

    # events
    @commands.Cog.listener()
    async def on_ready(self):
        log.info("Database ready")

    async def check_ignored(self, channel):
        async with self.client.session as session:
            return (
                await session.scalars(
                    select(models.database.Ignore).where(
                        models.database.Ignore.channelID == channel.id
                    )
                )
            ).one_or_none() is not None

    @commands.hybrid_command()
    @commands.has_permissions(manage_messages=True)
    async def ignore(self, ctx, channel: discord.TextChannel):
        """Make Nocaro ignore a channel"""
        async with self.client.session as session:
            async with session.begin():
                session.add(
                    models.database.Ignore(channelID=channel.id, guildID=ctx.guild.id)
                )

        await ctx.reply(f"Ignored {channel.mention}.")

    @commands.hybrid_command()
    @commands.has_permissions(manage_messages=True)
    async def unignore(self, ctx, channel: discord.TextChannel):
        """Make Nocaro not ignore a channel"""
        async with self.client.session as session:
            async with session.begin():
                await session.execute(
                    delete(models.database.Ignore).where(
                        models.database.Ignore.channelID == channel.id
                    )
                )

        await ctx.reply(f"Unignored {channel.mention}.")

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        async with self.client.session as session:
            async with session.begin():
                await session.execute(
                    delete(models.database.Messages).where(
                        models.database.Messages.messageID == message.id
                    )
                )

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        async with self.client.session as session:
            async with session.begin():
                await session.execute(
                    delete(models.database.Messages).where(
                        models.database.Messages.channelID == channel.id
                    )
                )

    @commands.hybrid_command(aliases=["privacy", "policy", "pp", "dinfo"])
    async def privacypolicy(self, ctx):
        """Short privacy policy."""
        await ctx.reply(
            "https://github.com/Bobbyperson/nocaro/blob/main/PRIVACY_POLICY.md"
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        msg = str.lower(message.content)  # semi-redundant
        if message.author.bot:
            return
        if not message.content:
            return
        if msg[0] == ",":  # make sure its not a command
            return
        if await self.check_ignored(message.channel):
            return
        blacklisted = await mf.is_blacklisted(message.author.id)
        if blacklisted[0]:
            return
        if not message.guild:
            return
        if msg in [
            "hit",
            "stand",
            "double",
            "split",
            "h",
            "s",
            "d",
            "p",
            "cash out",
            "c",
            "co",
        ]:
            return
        guild_member = message.guild.get_member(
            self.client.user.id
        )  # need member object
        if (
            "nocaro" in msg
            or (guild_member.nick and guild_member.nick in msg)
            or random.randint(1, 500) == 1
        ):
            if await self.check_ignored(message.channel):
                return
            user_id = message.author.id
            current_time = time.time()
            cooldown_period = 2  # Cooldown period in seconds

            # Check if the user is in cooldown
            if (
                user_id in self.nocaro_cooldowns
                and current_time - self.nocaro_cooldowns[user_id] < cooldown_period
            ):
                return
            async with self.client.session as session:
                rows = (
                    await session.scalars(
                        select(models.database.Messages).where(
                            models.database.Messages.channelID == message.channel.id
                        )
                    )
                ).all()
            if not rows:
                return
            for _ in range(10):
                chosen = random.choice(rows)
                orgchannel = await self.client.fetch_channel(
                    chosen.channelID
                )  # lookup channel
                try:
                    message_to_send = await orgchannel.fetch_message(
                        chosen.messageID
                    )  # lookup message
                except discord.NotFound:
                    async with self.client.session as session:
                        async with session.begin():
                            await session.execute(
                                delete(models.database.Messages).where(
                                    models.database.Messages.messageID
                                    == chosen.messageID
                                )
                            )
                    continue
                mentions = message_to_send.role_mentions
                if not any(role in mentions for role in message.guild.roles):
                    break
            try:
                await message.channel.send(
                    discord.utils.escape_mentions(message_to_send.content)
                )  # send that bitch
            except discord.Forbidden:
                return
            self.nocaro_cooldowns[user_id] = current_time
        else:
            async with self.client.session as session:
                async with session.begin():
                    session.add(
                        models.database.Messages(
                            messageID=message.id,
                            channelID=message.channel.id,
                            guildID=message.guild.id,
                        )
                    )
        if ("https://x.com" in msg or "https://twitter.com" in msg) and (
            "fixupx.com" not in msg
            and "fixvx.com" not in msg
            and "fxtwitter.com" not in msg
            and "vxtwitter.com" not in msg
        ):
            try:
                await message.delete()
            except discord.Forbidden:
                return
            newmsg = msg.replace("x.com", "fixvx.com")
            newmsg = newmsg.replace("twitter.com", "vxtwitter.com")
            await mf.send_webhook(
                ctx=message,
                name=message.author.display_name,
                avatar=message.author.display_avatar,
                message=discord.utils.escape_mentions(newmsg),
            )

    @commands.hybrid_command()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.max_concurrency(1, commands.BucketType.user)
    @mf.generic_checks()
    async def rmessage(self, ctx):
        """Send a random message."""
        async with self.client.session as session:
            rows = (
                await session.scalars(
                    select(models.database.Messages).where(
                        models.database.Messages.channelID == ctx.channel.id
                    )
                )
            ).all()
        if not rows:
            return
        for _ in range(10):
            chosen = random.choice(rows)
            orgchannel = await self.client.fetch_channel(
                chosen.channelID
            )  # lookup channel
            try:
                message_to_send = await orgchannel.fetch_message(
                    chosen.messageID
                )  # lookup message
            except discord.NotFound:
                async with self.client.session as session:
                    async with session.begin():
                        await session.execute(
                            delete(models.database.Messages).where(
                                models.database.Messages.messageID == chosen.messageID
                            )
                        )
                continue
            mentions = message_to_send.role_mentions
            if not any(role in mentions for role in ctx.guild.roles):
                break
        await mf.send_webhook(
            ctx=ctx,
            avatar=message_to_send.author.avatar,
            name=message_to_send.author.name,
            message=discord.utils.escape_mentions(message_to_send.content),
        )  # send that bitch

    @commands.hybrid_command()
    @commands.cooldown(1, 10, commands.BucketType.user)
    @mf.generic_checks()
    async def conversation(self, ctx, number: int = 5):
        """Generate a whole conversation between random users."""
        number = min(number, 10)
        async with self.client.session as session:
            rows = (
                await session.scalars(
                    select(models.database.Messages).where(
                        models.database.Messages.channelID == ctx.channel.id
                    )
                )
            ).all()
        if not rows:
            return
        for _ in range(number):
            message_to_send = random.choice(rows)
            chosen = random.choice(rows)
            orgchannel = await self.client.fetch_channel(
                chosen.channelID
            )  # lookup channel
            try:
                message_to_send = await orgchannel.fetch_message(
                    chosen.messageID
                )  # lookup message
            except discord.NotFound:
                async with self.client.session as session:
                    async with session.begin():
                        await session.execute(
                            delete(models.database.Messages).where(
                                models.database.Messages.messageID == chosen.messageID
                            )
                        )
                continue
            mentions = message_to_send.role_mentions
            if any(role in mentions for role in ctx.guild.roles):
                continue
            await mf.send_webhook(
                ctx=ctx,
                avatar=message_to_send.author.avatar,
                name=message_to_send.author.name,
                message=discord.utils.escape_mentions(message_to_send.content),
            )
            await asyncio.sleep(1)


async def setup(client):
    await client.add_cog(database(client))
