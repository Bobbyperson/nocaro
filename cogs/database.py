import asyncio
import logging
import math
import random
import re
import time
from collections import Counter
from dataclasses import dataclass

import discord
import discord.ext
import markovify
from discord.ext import commands, tasks
from markovify.chain import BEGIN, END
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import models
import utils.miscfuncs as mf

log = logging.getLogger(__name__)
bank = "./data/database.sqlite"

# Strips mentions, channels, roles, and custom/animated emotes
DISCORD_TOKEN_RE = re.compile(r"<a?:[^:]+:\d+>|<[@#&!?][^>]*>")

_COMBINE_AFTER = 50  # merge pending corpus additions into the model at this count
_MODEL_TTL = 600  # seconds before an idle model is evicted (10 minutes)
_STATE3_THRESHOLD = 4_000  # corpus lines needed before moving to state_size=3
_PERSIST_DRIFT_LIMIT = 500  # rebuild instead of loading a persisted model this stale
# How much a generated sentence may overlap a real message before markovify
# rejects it. Loose on purpose: mostly-verbatim output reads as coherent, and
# strict values make state_size=3 fail constantly on smaller corpora.
_MAX_OVERLAP_RATIO = 0.85
_MAX_OVERLAP_TOTAL = 25
_MAX_MESSAGE_LEN = 400  # skip walls of text; they dominate the chain
# Common command prefixes for this bot and others sharing a channel
_BOT_PREFIXES = (
    ",",
    "!",
    "?",
    ".",
    ";",
    "$",
    "%",
    "&",
    "=",
    "+",
    ">",
    "<",
    "-",
    "~",
    "/",
)


def strip_discord_tokens(s: str) -> str:
    return re.sub(r"\s+", " ", DISCORD_TOKEN_RE.sub("", s)).strip()


def _string_is_okay(s: str) -> bool:
    if not s or not isinstance(s, str):
        return False
    if len(s) < 5 or len(s) > _MAX_MESSAGE_LEN:
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
    if s.startswith(_BOT_PREFIXES):
        return False
    return True


def _word_freq_from_model(model: markovify.NewlineText) -> Counter:
    """Lowercased word frequencies derived from an (uncompiled) chain."""
    freq: Counter = Counter()
    for follows in model.chain.model.values():
        for word, count in follows.items():
            if word != END:
                freq[word.lower()] += count
    return freq


def _fluency(model: markovify.NewlineText, sentence: str) -> float:
    """Geometric mean transition probability of a sentence under the chain.

    Higher means the word sequence is more typical of the corpus, i.e. reads
    more naturally. Requires the uncompiled model. States a seeded sentence
    starts from mid-chain may be absent; those steps are skipped rather than
    zeroing the score.
    """
    chain_model = model.chain.model
    state = (BEGIN,) * model.state_size
    logp = 0.0
    steps = 0
    for word in [*sentence.split(), END]:
        follows = chain_model.get(state)
        if follows:
            count = follows.get(word)
            if count:
                logp += math.log(count / sum(follows.values()))
                steps += 1
        state = (*state[1:], word)
    return math.exp(logp / steps) if steps else 0.0


@dataclass
class _MarkovEntry:
    model: markovify.NewlineText  # uncompiled; needed for markovify.combine
    compiled: markovify.NewlineText  # compiled copy; much faster generation
    word_freq: Counter


def _build_entry(text: str, state_size: int) -> _MarkovEntry:
    # well_formed=False: the default rejects sentences containing quotes,
    # parens, etc., which throws away a large share of chat messages.
    model = markovify.NewlineText(text, state_size=state_size, well_formed=False)
    return _MarkovEntry(
        model=model, compiled=model.compile(), word_freq=_word_freq_from_model(model)
    )


def _message_is_okay(message: discord.Message) -> bool:
    if not message or not isinstance(message, discord.Message):
        return False
    if message.author.bot:
        return False
    if not _string_is_okay(message.content):
        return False
    return True


class database(commands.Cog):
    """Commands which utilize a message database."""

    def __init__(self, client):
        self.client = client
        self.nocaro_cooldowns = {}
        self._markov_cache: dict[int, _MarkovEntry] = {}
        self._pending_lines: dict[int, list[str]] = {}
        self._last_used: dict[int, float] = {}
        # In-memory copies of small, rarely-changing tables so the on_message
        # hot path doesn't hit the DB three times per message.
        self._ignored_channels: set[int] = set()
        self._enabled_channels: set[int] = set()
        self._opted_out: set[int] = set()
        self._settings_loaded = False
        self._settings_lock = asyncio.Lock()
        self._evict_idle_models.start()

    async def _ensure_settings_cache(self):
        if self._settings_loaded:
            return
        async with self._settings_lock:
            if self._settings_loaded:
                return
            async with self.client.session as session:
                ignored = (
                    await session.scalars(select(models.database.Ignore.channelID))
                ).all()
                enabled = (
                    await session.scalars(
                        select(models.database.ChannelSettings.channel_id).where(
                            models.database.ChannelSettings.markov_enabled.is_(True)
                        )
                    )
                ).all()
                opted_out = (
                    await session.scalars(select(models.database.MarkovOptOut.user_id))
                ).all()
            self._opted_out = set(opted_out)
            self._enabled_channels = set(enabled)
            self._ignored_channels = set(ignored)
            self._settings_loaded = True

    async def _absorb_line(self, channel_id: int, line: str):
        """Fold new corpus lines into the cached model without a full rebuild."""
        entry = self._markov_cache.get(channel_id)
        if entry is None:
            return
        pending = self._pending_lines.setdefault(channel_id, [])
        pending.append(line)
        if len(pending) < _COMBINE_AFTER:
            return
        batch = "\n".join(pending)
        pending.clear()
        state_size = entry.model.state_size

        def _combine() -> _MarkovEntry:
            delta = markovify.NewlineText(
                batch, state_size=state_size, well_formed=False
            )
            combined = markovify.combine([entry.model, delta])
            return _MarkovEntry(
                model=combined,
                compiled=combined.compile(),
                word_freq=_word_freq_from_model(combined),
            )

        new_entry = await asyncio.to_thread(_combine)
        # Skip the swap if the model was invalidated while we were combining
        if self._markov_cache.get(channel_id) is entry:
            self._markov_cache[channel_id] = new_entry

    async def _invalidate_cache(self, channel_id: int):
        """Evict a channel's cached model, including the persisted copy."""
        self._markov_cache.pop(channel_id, None)
        self._last_used.pop(channel_id, None)
        self._pending_lines.pop(channel_id, None)
        async with self.client.session as session:
            async with session.begin():
                await session.execute(
                    delete(models.database.MarkovModelCache).where(
                        models.database.MarkovModelCache.channel_id == channel_id
                    )
                )

    def cog_unload(self):
        self._evict_idle_models.cancel()

    @tasks.loop(minutes=2)
    async def _evict_idle_models(self):
        cutoff = time.monotonic() - _MODEL_TTL
        stale = [cid for cid, t in self._last_used.items() if t < cutoff]
        for cid in stale:
            self._markov_cache.pop(cid, None)
            self._last_used.pop(cid, None)
            self._pending_lines.pop(cid, None)
            log.debug("Evicted idle Markov model for channel %d", cid)

    async def _persist_model(self, channel_id: int, entry: _MarkovEntry, count: int):
        model_json = await asyncio.to_thread(entry.model.to_json)
        stmt = sqlite_insert(models.database.MarkovModelCache).values(
            channel_id=channel_id,
            state_size=entry.model.state_size,
            model_json=model_json,
            corpus_count=count,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["channel_id"],
            set_={
                "state_size": stmt.excluded.state_size,
                "model_json": stmt.excluded.model_json,
                "corpus_count": stmt.excluded.corpus_count,
            },
        )
        async with self.client.session as session:
            async with session.begin():
                await session.execute(stmt)

    async def _get_markov_model(self, channel_id: int) -> _MarkovEntry | None:
        """Return a cached Markov model, rebuilding only on cache miss."""
        if channel_id in self._markov_cache:
            self._last_used[channel_id] = time.monotonic()
            return self._markov_cache[channel_id]

        async with self.client.session as session:
            persisted = await session.get(models.database.MarkovModelCache, channel_id)
            corpus_count = await session.scalar(
                select(func.count())
                .select_from(models.database.MarkovCorpus)
                .where(models.database.MarkovCorpus.channel_id == channel_id)
            )

        # Reuse the persisted model unless the corpus has drifted too far
        if (
            persisted is not None
            and abs(corpus_count - persisted.corpus_count) <= _PERSIST_DRIFT_LIMIT
        ):

            def _load() -> _MarkovEntry:
                model = markovify.NewlineText.from_json(persisted.model_json)
                return _MarkovEntry(
                    model=model,
                    compiled=model.compile(),
                    word_freq=_word_freq_from_model(model),
                )

            entry = await asyncio.to_thread(_load)
            self._markov_cache[channel_id] = entry
            self._last_used[channel_id] = time.monotonic()
            self._pending_lines.pop(channel_id, None)
            return entry

        if not corpus_count:
            return None

        async with self.client.session as session:
            contents = (
                await session.scalars(
                    select(models.database.MarkovCorpus.content).where(
                        models.database.MarkovCorpus.channel_id == channel_id
                    )
                )
            ).all()

        seen: set[str] = set()
        lines: list[str] = []
        for c in contents:
            cl = c.strip()
            if cl and cl.lower() not in seen:
                seen.add(cl.lower())
                lines.append(cl)

        if not lines:
            return None

        # Chat messages are short; state_size > 3 mostly regurgitates the
        # corpus verbatim or fails to generate at all.
        state_size = 2 if len(lines) < _STATE3_THRESHOLD else 3
        text = "\n".join(lines)

        entry = await asyncio.to_thread(_build_entry, text, state_size)
        self._markov_cache[channel_id] = entry
        self._last_used[channel_id] = time.monotonic()
        self._pending_lines.pop(channel_id, None)
        await self._persist_model(channel_id, entry, corpus_count)
        return entry

    async def _generate_sentence(
        self, channel_id: int, context: str = ""
    ) -> str | None:
        """Generate a sentence, optimizing for coherence and topical relevance.

        Seeds candidates from the rarest context words present in the corpus
        (rare-word matches are what make a reply feel on-topic), then ranks
        all candidates by fluency (how natural the word sequence is under the
        chain) blended with rarity-weighted word overlap with `context`.
        """
        entry = await self._get_markov_model(channel_id)
        if entry is None:
            return None

        context_tokens = [w for w in context.split() if len(w) > 1]
        model = entry.compiled
        base_model = entry.model
        freq = entry.word_freq
        overlap = {
            "max_overlap_ratio": _MAX_OVERLAP_RATIO,
            "max_overlap_total": _MAX_OVERLAP_TOTAL,
        }

        def _generate() -> str | None:
            context_set = {w.lower() for w in context_tokens}

            candidates: list[str] = []
            # Try starting the chain from the rarest context words we know
            seeds = sorted(
                {w for w in context_tokens if freq.get(w.lower())},
                key=lambda w: freq[w.lower()],
            )[:3]
            for seed in seeds:
                for variant in dict.fromkeys((seed, seed.lower())):
                    try:
                        s = model.make_sentence_with_start(
                            variant, strict=False, tries=30, **overlap
                        )
                    except (LookupError, markovify.text.ParamError):
                        s = None
                    if s:
                        candidates.append(s)
                        break

            candidates += [
                s for _ in range(30) if (s := model.make_sentence(tries=20, **overlap))
            ]
            if not candidates:
                # Corpus too small to pass the overlap test; take any walk
                return model.make_sentence(tries=30, test_output=False)

            def _score(s: str) -> float:
                words = s.lower().split()
                matched = set(words) & context_set
                relevance = sum(
                    1.0 / math.log(2.0 + freq.get(w, 0)) for w in matched
                ) / math.sqrt(len(words) or 1)
                return _fluency(base_model, s) * (1.0 + 3.0 * relevance)

            return max(candidates, key=_score)

        return await asyncio.to_thread(_generate)

    # events
    @commands.Cog.listener()
    async def on_ready(self):
        log.info("Database ready")

    async def check_ignored(self, channel):
        await self._ensure_settings_cache()
        return channel.id in self._ignored_channels

    async def is_markov_enabled(self, channel_id: int) -> bool:
        await self._ensure_settings_cache()
        return channel_id in self._enabled_channels

    @commands.hybrid_command()
    @commands.has_permissions(manage_messages=True)
    async def ignore(self, ctx, channel: discord.TextChannel):
        """Make Nocaro ignore a channel"""
        async with self.client.session as session:
            async with session.begin():
                session.add(
                    models.database.Ignore(channelID=channel.id, guildID=ctx.guild.id)
                )
        await self._ensure_settings_cache()
        self._ignored_channels.add(channel.id)

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
        await self._ensure_settings_cache()
        self._ignored_channels.discard(channel.id)

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
                        existing = await session.get(
                            models.database.ChannelSettings, ctx.channel.id
                        )
                        if existing:
                            existing.markov_enabled = True
                        else:
                            session.add(
                                models.database.ChannelSettings(
                                    channel_id=ctx.channel.id, markov_enabled=True
                                )
                            )
                await self._ensure_settings_cache()
                self._enabled_channels.add(ctx.channel.id)
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
        """Disable my brain for this channel. Requires confirmation and deletes stored data."""
        if not await self.is_markov_enabled(ctx.channel.id):
            return await ctx.reply("My brain is not enabled.")

        await ctx.reply(
            "Disabling my brain will delete all stored message contents for this channel. Confirm? (yes/no)"
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
                await self._ensure_settings_cache()
                self._enabled_channels.discard(ctx.channel.id)
                await self._invalidate_cache(ctx.channel.id)
                await ctx.reply(
                    "My brain is disabled and all stored message data deleted."
                )
            else:
                await ctx.reply("Cancelled.")
        except TimeoutError:
            await ctx.reply("Timed out.")

    @commands.hybrid_command()
    @commands.has_permissions(manage_messages=True)
    @commands.cooldown(1, 259200, commands.BucketType.guild)  # 3 days per guild
    async def train(self, ctx, clean: bool = True, unlimited: bool = False):
        """Train my brain on the last 100000 messages from this channel."""
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

        msg_limit = None if unlimited else 100000
        main_msg = await ctx.reply(
            "Training started... This may take a while. 0 messages added so far."
        )

        total_added = 0
        last_reported = 0
        guild_member = ctx.guild.get_member(self.client.user.id)
        pending: list[tuple[int, int, int, str]] = []

        async for message in ctx.channel.history(limit=msg_limit):
            if not _message_is_okay(message):
                continue
            if await self._user_opted_out(message.author.id):
                continue
            blacklisted = await mf.is_blacklisted(message.author.id)
            if blacklisted[0]:
                continue
            if guild_member.nick and guild_member.nick in message.content:
                continue
            if self.client.user.mentioned_in(message):
                continue
            cleaned = strip_discord_tokens(message.content)
            if not _string_is_okay(cleaned):
                continue
            pending.append((message.id, ctx.channel.id, ctx.guild.id, cleaned))

        # Batch-insert; the unique index on message_id handles duplicates
        batch_size = 500
        for i in range(0, len(pending), batch_size):
            batch = pending[i : i + batch_size]
            stmt = (
                sqlite_insert(models.database.MarkovCorpus)
                .values(
                    [
                        {
                            "message_id": msg_id,
                            "channel_id": ch_id,
                            "guild_id": guild_id,
                            "content": content,
                        }
                        for msg_id, ch_id, guild_id, content in batch
                    ]
                )
                .on_conflict_do_nothing(index_elements=["message_id"])
            )
            async with self.client.session as session:
                async with session.begin():
                    result = await session.execute(stmt)
                    total_added += result.rowcount

            if total_added - last_reported >= 1000:
                last_reported = total_added
                main_msg = await main_msg.edit(
                    content=f"Training started... This may take a while. {total_added} messages added so far."
                )

        await self._invalidate_cache(ctx.channel.id)
        await ctx.reply(
            f"Training complete. Added {total_added} new messages to the corpus."
        )

    async def _user_opted_out(self, user_id: int) -> bool:
        await self._ensure_settings_cache()
        return user_id in self._opted_out

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
                    await self._ensure_settings_cache()
                    self._opted_out.add(ctx.author.id)
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
                    await self._ensure_settings_cache()
                    self._opted_out.discard(ctx.author.id)
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

        async with ctx.typing():
            history = [
                m.content
                async for m in ctx.channel.history(limit=5)
                if not m.author.bot and m.content
            ]
            context = " ".join(history)
            sentence = await self._generate_sentence(ctx.channel.id, context)

        if sentence:
            await ctx.send(discord.utils.escape_mentions(sentence))
        else:
            await ctx.reply("Not enough data to generate a sentence yet.")

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        markov_enabled = message.guild and await self.is_markov_enabled(
            message.channel.id
        )
        removed = 0
        async with self.client.session as session:
            async with session.begin():
                await session.execute(
                    delete(models.database.Messages).where(
                        models.database.Messages.messageID == message.id
                    )
                )
                if markov_enabled:
                    result = await session.execute(
                        delete(models.database.MarkovCorpus).where(
                            models.database.MarkovCorpus.message_id == message.id
                        )
                    )
                    removed = result.rowcount
        # Only rebuild if the deleted message was actually in the corpus
        if removed:
            await self._invalidate_cache(message.channel.id)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.author.bot or not before.content or not after.content:
            return
        if before.content == after.content:
            return  # embed resolution and pin events also fire this
        if await self.check_ignored(before.channel):
            return
        blacklisted = await mf.is_blacklisted(before.author.id)
        if blacklisted[0]:
            return
        if not before.guild:
            return
        if not await self.is_markov_enabled(before.channel.id):
            return

        guild_member = before.guild.get_member(self.client.user.id)
        changed = False
        async with self.client.session as session:
            async with session.begin():
                result = await session.execute(
                    delete(models.database.MarkovCorpus).where(
                        models.database.MarkovCorpus.message_id == before.id
                    )
                )
                changed = bool(result.rowcount)
                if (
                    not await self._user_opted_out(after.author.id)
                    and not self.client.user.mentioned_in(after)
                    and not (guild_member.nick and guild_member.nick in after.content)
                ):
                    cleaned = strip_discord_tokens(after.content)
                    if _string_is_okay(cleaned):
                        session.add(
                            models.database.MarkovCorpus(
                                message_id=after.id,
                                channel_id=after.channel.id,
                                guild_id=after.guild.id,
                                content=cleaned,
                            )
                        )
                        changed = True
        # Only rebuild if the edit actually touched the corpus
        if changed:
            await self._invalidate_cache(before.channel.id)

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
        await self._ensure_settings_cache()
        self._enabled_channels.discard(channel.id)
        self._ignored_channels.discard(channel.id)
        await self._invalidate_cache(channel.id)

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
                async with message.channel.typing():
                    sentence = await self._generate_sentence(
                        message.channel.id, message.content
                    )
                if sentence:
                    await message.channel.send(discord.utils.escape_mentions(sentence))
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
                cleaned = strip_discord_tokens(message.content)
                if _message_is_okay(message) and _string_is_okay(cleaned):
                    guild_member2 = message.guild.get_member(self.client.user.id)
                    if guild_member2.nick and guild_member2.nick in message.content:
                        pass
                    elif self.client.user.mentioned_in(message):
                        pass
                    else:
                        async with self.client.session as session:
                            async with session.begin():
                                await session.execute(
                                    sqlite_insert(models.database.MarkovCorpus)
                                    .values(
                                        message_id=message.id,
                                        channel_id=message.channel.id,
                                        guild_id=message.guild.id,
                                        content=cleaned,
                                    )
                                    .on_conflict_do_nothing(
                                        index_elements=["message_id"]
                                    )
                                )
                        await self._absorb_line(message.channel.id, cleaned)

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
