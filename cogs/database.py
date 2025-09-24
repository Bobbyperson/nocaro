import asyncio
import logging
import random
import re
import time

import discord
import discord.ext
import markovify
import nltk
from discord.ext import commands
from nltk import pos_tag, word_tokenize
from sqlalchemy import delete, select, update

import models
import utils.miscfuncs as mf

log = logging.getLogger(__name__)
bank = "./data/database.sqlite"
nltk.download("averaged_perceptron_tagger")
nltk.download("punkt")
nltk.download("punkt_tab")
nltk.download("averaged_perceptron_tagger_eng")


def _candidate_start_words(
    context_words: list[str], max_len: int = 2
) -> list[list[str]]:
    cands = []
    tail = context_words[-4:]
    for n in range(min(max_len, len(tail)), 0, -1):
        cands.append(tail[-n:])
    if len(tail) >= 3:
        cands.append(tail[-3:-2])
    seen = set()
    uniq = []
    for cand in cands:
        key = tuple(cand)
        if key not in seen:
            seen.add(key)
            uniq.append(cand)
    return uniq


def _make_sentence_safely(
    model: markovify.Text, context_words: list[str], **kwargs
) -> str | None:
    for cand in _candidate_start_words(
        context_words, max_len=min(2, getattr(model, "state_size", 2))
    ):
        start_str = " ".join(cand)
        try:
            s = model.make_sentence_with_start(start_str, strict=False, **kwargs)
            if s:
                return s
        except (markovify.text.ParamError, KeyError):
            continue  # try next candidate

    state_size = getattr(model, "state_size", 2)
    if len(context_words) >= state_size:
        init_state_tuple = tuple(context_words[-state_size:])
        try:
            s = model.make_sentence(init_state=init_state_tuple, **kwargs)
            if s:
                return s
        except Exception:
            pass

    try:
        return model.make_sentence(**kwargs)
    except Exception:
        return None


MENTION_RE = re.compile(r"<(@[!&]?\d+|#\d+)>")


def strip_mentions(s: str) -> str:
    return re.sub(r"\s+", " ", MENTION_RE.sub("", s)).strip()


def _string_is_okay(s: str) -> bool:
    if not s or not isinstance(s, str):
        return False
    if len(s) < 5:
        return False
    if any(char in s for char in ["http://", "https://", "://"]):
        return False
    if (sum(c.isalnum() for c in s) / len(s)) < 0.5:
        return False
    if "nocaro" in s.lower():
        return False
    if s.lower() in [
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
        return False
    if s.startswith(","):
        return False
    return True


def _message_is_okay(message: discord.Message) -> bool:
    if not message or not isinstance(message, discord.Message):
        return False
    if message.author.bot:
        return False
    if not _string_is_okay(message.content):
        return False
    return True


class POSifiedText(markovify.Text):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def word_split(self, sentence):
        if not sentence or not isinstance(sentence, str):
            log.warning(f"Invalid sentence in word_split: {sentence}")
            return []
        try:
            words = word_tokenize(sentence)
            tagged = pos_tag(words)
            return [f"{w}_{t}" for w, t in tagged if w]
        except Exception as e:
            log.error(f"Error in word_split for sentence '{sentence}': {e}")
            return []

    def word_join(self, words):
        if not words:
            return ""
        output = []
        for w in words:
            token = w.split("_", 1)[0] if isinstance(w, str) else str(w)
            if token in ".,!?;:@<>&'\"/\\" and output:
                output[-1] += token
            else:
                output.append(token)
        return " ".join(output)


class database(commands.Cog):
    """Commands which utilize a message database."""

    def __init__(self, client):
        self.client = client
        self.nocaro_cooldowns = {}
        # cache: {channel_id: {"model": model, "count": int}}
        self._markov_cache = {}

    async def _get_markov_model(self, channel_id: int) -> POSifiedText | None:
        """Return a cached Markov model for a channel, rebuild if corpus changed."""
        async with self.client.session as session:
            contents = (
                await session.scalars(
                    select(models.database.MarkovCorpus.content).where(
                        models.database.MarkovCorpus.channel_id == channel_id
                    )
                )
            ).all()

        if not contents:
            return None

        seen = set()
        lines = []
        for c in contents:
            cl = c.strip()
            if cl and cl.lower() not in seen:
                seen.add(cl.lower())
                lines.append(cl)

        n_lines = len(lines)
        state_size = 2 if n_lines < 2_000 else 3 if n_lines < 10_000 else 4
        text = "\n".join(lines)

        # Check cache
        cached = self._markov_cache.get(channel_id)
        if cached and cached["count"] in range(n_lines - 50, n_lines + 51):
            return cached["model"]

        # Rebuild model
        model = POSifiedText(text, state_size=state_size)
        self._markov_cache[channel_id] = {"model": model, "count": n_lines}
        return model

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

    async def is_markov_enabled(self, channel_id: int) -> bool:
        async with self.client.session as session:
            settings = await session.scalar(
                select(models.database.ChannelSettings.markov_enabled).where(
                    models.database.ChannelSettings.channel_id == channel_id
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
        if await self.is_markov_enabled(ctx.channel.id):
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
                        settings = models.database.ChannelSettings(
                            channel_id=ctx.channel.id, markov_enabled=True
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
        if not await self.is_markov_enabled(ctx.channel.id):
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
                                models.database.MarkovCorpus.channel_id
                                == ctx.channel.id
                            )
                        )
                        await session.execute(
                            update(models.database.ChannelSettings)
                            .where(
                                models.database.ChannelSettings.channel_id
                                == ctx.channel.id
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
    async def train(self, ctx, clean: bool = True, unlimited: bool = False):
        """Train my brain on the last 100000 messages from a single channel."""
        if not await self.is_markov_enabled(ctx.channel.id):
            return await ctx.reply("My brain must be enabled first.")

        if unlimited and ctx.author.id != self.client.config["general"]["owner_id"]:
            return await ctx.reply("Only the bot owner can use the unlimited option.")

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
                            models.database.MarkovCorpus.channel_id == ctx.channel.id
                        )
                    )

        main_msg = await ctx.reply(
            "Training started... This may take a while. 0 messages have been added to corpus so far."
        )

        # non_ignored_channels = [
        #     ch for ch in ctx.guild.text_channels if not await self.check_ignored(ch)
        # ]

        total_added = 0
        # for channel in non_ignored_channels:
        # messages = [message async for message in ctx.channel.history(limit=100000)]
        msg_limit = None if unlimited else 100000
        async for message in ctx.channel.history(limit=msg_limit):
            if message.author.bot or not message.content:
                continue
            blacklisted = await mf.is_blacklisted(message.author.id)
            if not _message_is_okay(message) or blacklisted[0]:
                continue
            guild_member = message.guild.get_member(self.client.user.id)
            if guild_member.nick and guild_member.nick in message.content:
                continue
            if self.client.user.mentioned_in(message):
                continue
            if (
                len(message.content) < 5
                or any(
                    char in message.content for char in ["http://", "https://", "://"]
                )
                or sum(c.isalnum() for c in message.content) / len(message.content)
                < 0.5
            ):
                continue
            message.content = strip_mentions(message.content)
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
                main_msg = await main_msg.edit(
                    content=f"Training started... This may take a while. {total_added} messages have been added to corpus so far."
                )

        await ctx.reply(
            f"Training complete. Added {total_added} new messages to the corpus."
        )

    async def _user_opted_out(self, user_id: int) -> bool:
        async with self.client.session as session:
            existing = await session.scalar(
                select(models.database.MarkovOptOut).where(
                    models.database.MarkovOptOut.user_id == user_id
                )
            )
            return existing is not None

    @commands.hybrid_command()
    @mf.generic_checks()
    async def brainoptout(self, ctx, optingout: bool = True):
        """Opt out of having your messages stored for Markov generation."""
        async with self.client.session as session:
            async with session.begin():
                existing = await session.scalar(
                    select(models.database.MarkovOptOut).where(
                        models.database.MarkovOptOut.user_id == ctx.author.id
                    )
                )
                if optingout:
                    if existing:
                        return await ctx.reply("You have already opted out.")
                    session.add(models.database.MarkovOptOut(user_id=ctx.author.id))
                    await ctx.reply(
                        "You have opted out of having your messages stored for Markov generation. You can opt back in with ,brainoptout false."
                    )
                else:
                    if not existing:
                        return await ctx.reply("You are not currently opted out.")
                    await session.execute(
                        delete(models.database.MarkovOptOut).where(
                            models.database.MarkovOptOut.user_id == ctx.author.id
                        )
                    )
                    await ctx.reply(
                        "You have opted back in to having your messages stored for Markov generation."
                    )

    @commands.hybrid_command()
    @commands.cooldown(1, 2, commands.BucketType.user)
    @mf.generic_checks()
    async def speak(self, ctx):
        """Intelligently create a message"""
        if not await self.is_markov_enabled(ctx.channel.id):
            return await ctx.reply("My intelligence is disabled. :(")

        # Fetch recent messages for context
        async with ctx.typing():
            history = [
                m
                async for m in ctx.channel.history(limit=10)  # Increase limit
                if not m.author.bot and m.content and len(m.content) > 5
            ]
            context = " ".join(
                [m.content for m in history[-3:] if m.content] + [ctx.message.content]
            )  # Prioritize last 3
            if not context:
                context = "Hello"

            # Clean context to remove command prefixes and non-words
            context_words = [
                word
                for word in context.split()
                if not word.startswith(",") and word.isalnum()
            ]

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
            size = 2 if len(text) < 100000 else 3
            # model = markovify.NewlineText(text, state_size=size)
            model = POSifiedText(text, state_size=size)
            kwargs = dict(tries=120, max_overlap_ratio=0.6, max_overlap_total=12)
            sentence = _make_sentence_safely(model, context_words, **kwargs)
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
                if await self.is_markov_enabled(before.channel.id):
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

            if await self.is_markov_enabled(message.channel.id):
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

                    text = "\n".join(contents)
                    size = 2 if len(text) < 100000 else 3
                    # model = markovify.NewlineText(text, state_size=size)
                    model = POSifiedText(text, state_size=size)
                    kwargs = dict(
                        tries=120, max_overlap_ratio=0.6, max_overlap_total=12
                    )
                    kwargs = dict(
                        tries=120, max_overlap_ratio=0.6, max_overlap_total=12
                    )
                    sentence = _make_sentence_safely(model, context_words, **kwargs)
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
                            guildID=message.channel.id,
                        )
                    )
            if await self.is_markov_enabled(
                message.channel.id
            ) and not await self._user_opted_out(message.author.id):
                if _message_is_okay(message):
                    message.content = strip_mentions(message.content)
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
