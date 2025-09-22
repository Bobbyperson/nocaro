import asyncio
import logging
import random
import time

import discord
import discord.ext
import markovify  # Ensure markovify is installed: pip install markovify
from discord.ext import commands
from sqlalchemy import delete, select, update

import models
import utils.miscfuncs as mf

log = logging.getLogger(__name__)
bank = "./data/database.sqlite"


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

    async def is_markov_enabled(self, guild_id: int) -> bool:
        async with self.client.session as session:
            settings = await session.scalar(
                select(models.database.GuildSettings.markov_enabled).where(
                    models.database.GuildSettings.guild_id == guild_id
                )
            )
            return settings if settings is not None else False

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

    @commands.hybrid_command()
    @commands.has_permissions(manage_messages=True)
    async def enablebrain(self, ctx):
        """Enable intelligently responding to messages."""
        if await self.is_markov_enabled(ctx.guild.id):
            return await ctx.reply("My brain is already enabled.")

        await ctx.reply(
            "Enabling my brain will store message contents long term in the bot's database for generating sentences. Confirm? (yes/no)"
        )

        def check(m):
            return (
                m.author == ctx.author
                and m.channel == ctx.channel
                and m.content.lower() in ["yes", "no"]
            )

        try:
            msg = await self.client.wait_for("message", check=check, timeout=60)
            if msg.content.lower() == "yes":
                async with self.client.session as session:
                    async with session.begin():
                        settings = models.database.GuildSettings(
                            guild_id=ctx.guild.id, markov_enabled=True
                        )
                        session.add(settings)
                await ctx.reply(
                    "My brain is enabled. Use ,train to initially load data from history."
                )
            else:
                await ctx.reply("Cancelled.")
        except TimeoutError:
            await ctx.reply("Timed out.")

    @commands.hybrid_command()
    @commands.has_permissions(manage_messages=True)
    async def disablebrain(self, ctx):
        """Disable my brain for this server. Requires confirmation and deletes stored data."""
        if not await self.is_markov_enabled(ctx.guild.id):
            return await ctx.reply("My brain is not enabled.")

        await ctx.reply(
            "Disabling my brain will delete all stored message contents for this server. Confirm? (yes/no)"
        )

        def check(m):
            return (
                m.author == ctx.author
                and m.channel == ctx.channel
                and m.content.lower() in ["yes", "no"]
            )

        try:
            msg = await self.client.wait_for("message", check=check, timeout=60)
            if msg.content.lower() == "yes":
                async with self.client.session as session:
                    async with session.begin():
                        await session.execute(
                            delete(models.database.MarkovCorpus).where(
                                models.database.MarkovCorpus.guild_id == ctx.guild.id
                            )
                        )
                        await session.execute(
                            update(models.database.GuildSettings)
                            .where(
                                models.database.GuildSettings.guild_id == ctx.guild.id
                            )
                            .values(markov_enabled=False)
                        )
                await ctx.reply(
                    "My brain is disabled and all stored message data deleted."
                )
            else:
                await ctx.reply("Cancelled.")
        except TimeoutError:
            await ctx.reply("Timed out.")

    @commands.hybrid_command()
    @commands.has_permissions(manage_messages=True)
    @commands.cooldown(
        1, 259200, commands.BucketType.guild
    )  # 3 days cooldown per guild
    async def train(self, ctx, clean: bool = True):
        """Train my brain on the last 50000 messages from a single channel."""
        if not await self.is_markov_enabled(ctx.guild.id):
            return await ctx.reply("My brain must be enabled first.")

        if clean:
            await ctx.reply(
                "Cleaning will delete all existing stored message data before training. Proceed? (yes/no)"
            )

            def check(m):
                return (
                    m.author == ctx.author
                    and m.channel == ctx.channel
                    and m.content.lower() in ["yes", "no"]
                )

            try:
                msg = await self.client.wait_for("message", check=check, timeout=60)
                if msg.content.lower() != "yes":
                    return await ctx.reply("Training cancelled.")
            except TimeoutError:
                return await ctx.reply("Timed out. Training cancelled.")

            async with self.client.session as session:
                async with session.begin():
                    await session.execute(
                        delete(models.database.MarkovCorpus).where(
                            models.database.MarkovCorpus.guild_id == ctx.guild.id
                        )
                    )

        # non_ignored_channels = [
        #     ch for ch in ctx.guild.text_channels if not await self.check_ignored(ch)
        # ]

        total_added = 0
        # for channel in non_ignored_channels:
        # messages = [message async for message in ctx.channel.history(limit=50000)]
        async for message in ctx.channel.history(limit=50000):
            if message.author.bot or not message.content:
                continue
            blacklisted = await mf.is_blacklisted(message.author.id)
            if blacklisted[0]:
                continue
            if message.content in [
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
                continue
            if "nocaro" in message.content.lower():
                continue
            async with self.client.session as session:
                async with session.begin():
                    # Check if already exists to avoid duplicates
                    exists = await session.scalar(
                        select(models.database.MarkovCorpus).where(
                            models.database.MarkovCorpus.message_id == message.id
                        )
                    )
                    if not exists:
                        session.add(
                            models.database.MarkovCorpus(
                                message_id=message.id,
                                channel_id=ctx.channel.id,
                                guild_id=ctx.guild.id,
                                content=message.content,
                            )
                        )
                        total_added += 1
            if total_added % 1000 == 0 and total_added > 0:
                logging.debug(f"Added {total_added} messages so far...")

        await ctx.reply(
            f"Training complete. Added {total_added} new messages to the corpus."
        )

    @commands.hybrid_command()
    @commands.cooldown(1, 2, commands.BucketType.user)
    @mf.generic_checks()
    async def speak(self, ctx):
        """Intelligently create a message"""
        if not await self.is_markov_enabled(ctx.guild.id):
            return await ctx.reply("My intelligence is disabled. :(")

        # Fetch recent messages for context
        async with ctx.typing():
            history = [
                message
                async for message in ctx.channel.history(limit=5)
                if not message.author.bot and message.content
            ]
            context = " ".join(
                [msg.content for msg in history if msg.content]
                + [ctx.message.content if ctx.message else ""]
            )
            if not context:
                context = "Hello"

            # Clean context to remove command prefixes and non-words
            context_words = [
                word
                for word in context.split()
                if not word.startswith(",") and word.isalnum()
            ]
            init_state = tuple(context_words[-2:]) if len(context_words) >= 2 else ()

            async with self.client.session as session:
                contents = (
                    await session.scalars(
                        select(models.database.MarkovCorpus.content).where(
                            models.database.MarkovCorpus.channel_id == ctx.channel.id
                        )
                    )
                ).all()

            if not contents:
                return await ctx.reply("No data available to generate a sentence.")

            text = "\n".join(contents)
            model = markovify.NewlineText(text, state_size=2)
            sentence = None
            if init_state and init_state in model.chain.model:
                sentence = model.make_sentence(tries=100, init_state=init_state)
            if not sentence:  # Fallback to random generation if init_state fails
                sentence = model.make_sentence(tries=100)

            if sentence:
                await ctx.send(discord.utils.escape_mentions(sentence))
            else:
                await ctx.reply("Could not generate a sentence.")

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        async with self.client.session as session:
            async with session.begin():
                await session.execute(
                    delete(models.database.Messages).where(
                        models.database.Messages.messageID == message.id
                    )
                )
                await session.execute(
                    delete(models.database.MarkovCorpus).where(
                        models.database.MarkovCorpus.message_id == message.id
                    )
                )

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.author.bot or not before.content or not after.content:
            return
        if await self.check_ignored(before.channel):
            return
        blacklisted = await mf.is_blacklisted(before.author.id)
        if blacklisted[0]:
            return
        if not before.guild:
            return

        async with self.client.session as session:
            async with session.begin():
                await session.execute(
                    delete(models.database.MarkovCorpus).where(
                        models.database.MarkovCorpus.message_id == before.id
                    )
                )
                if await self.is_markov_enabled(before.guild.id):
                    session.add(
                        models.database.MarkovCorpus(
                            message_id=after.id,
                            channel_id=after.channel.id,
                            guild_id=after.guild.id,
                            content=after.content,
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
                await session.execute(
                    delete(models.database.MarkovCorpus).where(
                        models.database.MarkovCorpus.channel_id == channel.id
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
            or self.client.user.mentioned_in(message)
        ):
            user_id = message.author.id
            current_time = time.time()
            cooldown_period = 2  # Cooldown period in seconds

            # Check if the user is in cooldown
            if (
                user_id in self.nocaro_cooldowns
                and current_time - self.nocaro_cooldowns[user_id] < cooldown_period
            ):
                return

            if await self.is_markov_enabled(message.guild.id):
                # Context-aware Markov generation
                async with message.channel.typing():
                    async with self.client.session as session:
                        contents = (
                            await session.scalars(
                                select(models.database.MarkovCorpus.content).where(
                                    models.database.MarkovCorpus.channel_id
                                    == message.channel.id
                                )
                            )
                        ).all()

                    if not contents:
                        return

                    history = [
                        m
                        async for m in message.channel.history(limit=5)
                        if not m.author.bot and m.content
                    ]
                    context = " ".join(
                        [m.content for m in history if m.content] + [message.content]
                    )
                    if not context:
                        context = "Hello"

                    # Clean context to remove command prefixes and non-words
                    context_words = [
                        word
                        for word in context.split()
                        if not word.startswith(",") and word.isalnum()
                    ]
                    init_state = (
                        tuple(context_words[-2:]) if len(context_words) >= 2 else ()
                    )

                    text = "\n".join(contents)
                    model = markovify.NewlineText(text, state_size=2)
                    sentence = None
                    if init_state and init_state in model.chain.model:
                        sentence = model.make_sentence(tries=100, init_state=init_state)
                    if (
                        not sentence
                    ):  # Fallback to random generation if init_state fails
                        sentence = model.make_sentence(tries=100)

                    if sentence:
                        await message.channel.send(
                            discord.utils.escape_mentions(sentence)
                        )
            else:
                # Legacy random message
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
            # Add to Markov corpus if enabled
            if await self.is_markov_enabled(message.guild.id):
                async with self.client.session as session:
                    async with session.begin():
                        session.add(
                            models.database.MarkovCorpus(
                                message_id=message.id,
                                channel_id=message.channel.id,
                                guild_id=message.guild.id,
                                content=message.content,
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
