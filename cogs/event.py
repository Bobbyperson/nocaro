import asyncio
import contextlib
import datetime
import functools
import logging
import random
from collections import Counter

import discord
from discord.ext import commands, tasks
from sqlalchemy import delete, func, select

import models
from utils import config

MAX_ENTRIES = 16
EMOJIS = [
    "0️⃣",
    "1️⃣",
    "2️⃣",
    "3️⃣",
    "4️⃣",
    "5️⃣",
    "6️⃣",
    "7️⃣",
    "8️⃣",
    "9️⃣",
    # These will probably not have a nice representation
    # in your editor but will look the same as above
    # on discord
    "🇦",
    "🇧",
    "🇨",
    "🇩",
    "🇪",
    "🇫",
]
assert len(EMOJIS) >= MAX_ENTRIES, (
    "Not enough emojis for the max amount of possible entries"
)

WINNING_OFFSET = -0.2
LOSING_OFFSET = 0.1

AUTOMATIC_STATE_KEY = "event_automatic_state"
AUTOMATIC_LAST_START_KEY = "event_automatic_last_start"

log = logging.getLogger(__name__)
# log.setLevel(logging.DEBUG)


def get_next_weekday(weekday: int) -> datetime.datetime:
    """
    Days are in the same order as for datetime.datetime.weekday()

    https://docs.python.org/3/library/datetime.html#datetime.datetime.weekday
    """

    today = datetime.datetime.today()
    # We are only going to work with a clean date, no time
    tomorrow_clean = today.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
        tzinfo=datetime.UTC,
    ) + datetime.timedelta(days=1)

    # Gets the next specified weekday exlcuding today
    return tomorrow_clean + datetime.timedelta((weekday - tomorrow_clean.weekday()) % 7)


def get_prev_weekday(weekday: int) -> datetime.datetime:
    """
    Days are in the same order as for datetime.datetime.weekday()

    https://docs.python.org/3/library/datetime.html#datetime.datetime.weekday
    """

    today = datetime.datetime.today()
    today_clean = today.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
        tzinfo=datetime.UTC,
    )

    # Gets the previous specified weekday including today
    return today_clean - datetime.timedelta(((7 - weekday) + today_clean.weekday()) % 7)


class Event(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.poll_active: bool = False
        self.message_id: int | None = None
        self.end_timestamp: datetime.datetime | None = None
        self.warn_timestamp: datetime.datetime | None = None
        self.recalc_timestamp: datetime.datetime | None = None
        self.entries: list[models.event.EventEntry] = []
        self.votes = Counter()

        self.poll_lock = asyncio.Lock()

        self.update_task.add_exception_type(asyncio.TimeoutError)
        self.update_task.add_exception_type(discord.errors.DiscordServerError)

        self.winners = []  # stores list of users who voted for the winner
        self.pending_attendance = {}  # user_id -> join_time
        self.showed_up = set()  # user_ids who were present >= 30min
        self.event_vcs = []  # voice channel being monitored

    async def cog_load(self):
        if not self.bot.is_ready():
            return

        log.debug("Cog loading")

        await self.restore_state()

        if not self.update_task.is_running():
            self.update_task.start()

    async def cog_unload(self):
        log.debug("Cog unloading, disabling task")
        self.update_task.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        log.info("Event loaded.")

        # The cog cannot load before the bot is ready
        await self.cog_load()

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        log.debug("Received a reaction")
        if not self.poll_active:
            return
        elif payload.message_id != self.message_id:
            return

        emoji = str(payload.emoji)

        try:
            index = EMOJIS.index(emoji)
        except ValueError:
            return

        user = self.bot.get_user(payload.user_id)
        if not user or user.bot:
            return

        # This is inaccurate and only used for visuals
        # the real results get recalculated.
        self.votes[index] += await self.__get_vote_value(emoji, user)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        log.debug("Removed a reaction")
        if not self.poll_active:
            return
        elif payload.message_id != self.message_id:
            return

        emoji = str(payload.emoji)

        try:
            index = EMOJIS.index(emoji)
        except ValueError:
            return

        user = self.bot.get_user(payload.user_id)
        if not user or user.bot:
            return

        # This is inaccurate and only used for visuals
        # the real results get recalculated.
        self.votes[index] -= await self.__get_vote_value(emoji, user)

    @commands.Cog.listener()
    async def on_raw_reaction_clear(self, payload: discord.RawReactionActionEvent):
        # This is unlikely to happen but we need to handle this case
        log.debug("All reactions were removed")
        if not self.poll_active:
            return
        elif payload.message_id != self.message_id:
            return

        self.votes.clear()

    @commands.Cog.listener()
    async def on_raw_reaction_clear_emoji(
        self, payload: discord.RawReactionActionEvent
    ):
        # This is unlikely to happen but we need to handle this case
        log.debug("One reaction was completely removed")
        if not self.poll_active:
            return
        elif payload.message_id != self.message_id:
            return

        try:
            index = EMOJIS.index(payload.emoji)
        except ValueError:
            return

        self.votes[index] = 0

    def state_decorator(func):
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            async with self.poll_lock:
                return await func(self, *args, **kwargs)

        return wrapper

    async def restore_state(self):
        async with self.bot.session as session:
            result = (
                await session.scalars(select(models.event.EventPollState))
            ).one_or_none()

            if not result:
                return

            log.info("Found an existing event poll, restoring...")

            self.poll_active = True
            self.message_id = result.message_id
            self.end_timestamp = result.end_timestamp.replace(tzinfo=datetime.UTC)
            self.warn_timestamp = result.warn_timestamp.replace(tzinfo=datetime.UTC)
            self.recalc_timestamp = datetime.datetime.now(
                datetime.UTC
            ) + datetime.timedelta(minutes=1)
            self.entries = await self.__load_entries()

            poll_message = await self.__get_poll_message()
            self.votes = await self.__get_votes(poll_message)

            log.info("Done restoring")

    async def start_state(self, entries):
        assert self.poll_active is not True, (
            "Trying to start state when its already active"
        )

        self.entries = entries
        assert self.entries, "No entries to start poll with"

        poll_channel = await self.__get_poll_channel()

        next_friday = self.__get_automatic_end_time()

        # End poll 2 hours before event
        self.end_timestamp = next_friday - datetime.timedelta(hours=2)

        # Warn 1 hour before poll end
        self.warn_timestamp = self.end_timestamp - datetime.timedelta(hours=1)

        message = await poll_channel.send("⏳")
        for i in range(len(self.entries)):
            await message.add_reaction(EMOJIS[i])

        self.message_id = message.id

        async with self.bot.session as session:
            async with session.begin():
                session.add(
                    models.event.EventPollState(
                        message_id=self.message_id,
                        end_timestamp=self.end_timestamp,
                        warn_timestamp=self.warn_timestamp,
                    )
                )

        self.poll_active = True

        log.info("poll started")

        if not self.update_task.is_running():
            self.update_task.start()
        else:
            await self.__update_poll()

    async def finish_state(self):
        assert self.poll_active is True, "Trying to finish state when its not active"

        async with self.bot.session as session:
            async with session.begin():
                await session.execute(delete(models.event.EventPollState))

        self.poll_active = False

        poll_message = await self.__get_poll_message()

        # Updated the votes to have the real state incase inaccuracies were introduced
        self.votes = await self.__get_votes(poll_message)

        # Update the poll one more time to reflect the last state
        await self.__update_poll()

        poll_message = await self.__get_poll_message()

        percentages, _ = await self.__get_percentages(self.votes)
        all_winners = await self.__determine_winning_index(percentages)
        winning_index = random.choice(list(all_winners))

        if winning_index > -1:
            winner_reaction = discord.utils.get(
                poll_message.reactions, emoji=EMOJIS[winning_index]
            )

            self.winners = [
                user.id async for user in winner_reaction.users() if not user.bot
            ]

        self.message = None
        self.end_timestamp = None
        self.warn_timestamp = None

        entries = self.entries.copy()
        self.entries.clear()

        return winning_index, entries

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if not self.event_vcs or not member.voice:
            return
        if member.bot or member.voice.channel.id not in self.event_vcs:
            return
        # User joins VC
        if after.channel and after.channel.id in self.event_vcs:
            self.pending_attendance[member.id] = datetime.datetime.now(datetime.UTC)

            async def wait_and_mark():
                await asyncio.sleep(30 * 60)  # 30 minutes
                join_time = self.pending_attendance.get(member.id)
                if (
                    join_time
                    and member.voice
                    and member.voice.channel.id in self.event_vcs
                ):
                    self.showed_up.add(member.id)
                    # await member.send("✅ You've been counted as attending the event.")
                    log.info("counted {member.display_name} as attended")  # debug

            if not hasattr(self, "background_tasks"):
                self.background_tasks = set()
            task = asyncio.create_task(wait_and_mark())
            self.background_tasks.add(task)
            task.add_done_callback(self.background_tasks.discard)
            log.info("added", member.display_name, "to pending attendance")

        # User leaves VC
        elif (
            before.channel.id in self.event_vcs
            and after.channel is None
            and member.id in self.pending_attendance
            and member.id not in self.showed_up
        ):
            self.pending_attendance.pop(member.id, None)
            self.showed_up.discard(member.id)
            log.info("removed", member.display_name, "from pending attendance")
            # await member.send("You left the VC. You won't be counted unless you stay 30 minutes next time.")

    @tasks.loop(seconds=8.0)
    @state_decorator
    async def update_task(self):
        log.debug("update_task")
        if self.poll_active:
            await self.__active_poll()
        else:
            await self.__inactive_poll()

    @update_task.before_loop
    async def before_update_task(self):
        await self.bot.wait_until_ready()

    async def __active_poll(self):
        # Event starts at 12AM UTC so we end it a few hours before that
        now = datetime.datetime.now(datetime.UTC)
        log.debug(f"now {now}")

        if await self.__get_automatic_state():
            log.debug(f"Checking if end threshold has passed {self.end_timestamp}")
            if self.end_timestamp is not None and now >= self.end_timestamp:
                # close poll
                log.info("Closing poll automatically")

                index, entries = await self.finish_state()

                poll_channel = await self.__get_poll_channel()

                if index > -1:
                    winner = entries[index]
                    await poll_channel.send(
                        f"Poll closed! The winner is: {EMOJIS[index]} - {winner.name}"
                    )

                    await self.__update_weights(winner)
                else:
                    await poll_channel.send("Poll closed! There is no winner")

                return

        assert self.end_timestamp, "no end timestamp in current state"

        log.debug(f"Checking if warn threshold has passed {self.warn_timestamp}")
        if self.warn_timestamp is not None and now >= self.warn_timestamp:
            # Even will close soon, warn everyone that their vote will soon be final
            log.info("Sending out warning to all voters")

            poll_message = await self.__get_poll_message()

            warning_message = f"The event poll will be closing <t:{int(self.end_timestamp.timestamp())}:R>. If you cannot attend, please remove your vote to avoid losing future voting power. {poll_message.jump_url}"
            users = []

            for reaction in poll_message.reactions:
                if reaction.emoji in EMOJIS:
                    async for user in reaction.users():
                        if user.bot:
                            continue
                        if user in users:
                            continue
                        users.append(user)

            for user in users:
                try:
                    await user.send(warning_message)
                except discord.Forbidden:
                    pass

            self.warn_timestamp = None

        log.debug(f"Checking if we should to recalc votes {self.recalc_timestamp}")
        if self.recalc_timestamp is not None and now >= self.recalc_timestamp:
            log.debug("Recalculating votes")

            poll_message = await self.__get_poll_message()

            self.recalc_timestamp = datetime.datetime.now(
                datetime.UTC
            ) + datetime.timedelta(minutes=1)
            self.votes = await self.__get_votes(poll_message)

        await self.__update_poll()

    async def __inactive_poll(self):
        if not await self.__get_automatic_state():
            # No automatic poll creation
            log.debug("Cannot start automatic poll because its been disabled")
            return

        today = datetime.date.today()
        if today.weekday() >= 4:
            log.debug("Friday or later, don't bother starting a poll")
            return

        prev_monday = self.__get_automatic_start_time().date()
        last_automatic_start = await self.__get_last_automatic_start()
        if last_automatic_start is not None and prev_monday <= last_automatic_start:
            log.debug("We already started the event this week")
            return

        # Its monday, start a new poll
        entries = await self.__load_entries()
        if len(entries) < 2:
            log.info("No enough entries to automatically start poll with")
            return

        log.info("Poll automatically started")
        await self.start_state(entries)
        log.debug("start done")

        # Make sure we don't end up restarting the poll if its canceled
        await self.__set_last_automatic_start(prev_monday)

    async def __update_poll(self):
        assert self.entries, "No entries to update poll with"

        poll_message = await self.__get_poll_message()

        percentages, _ = await self.__get_percentages(self.votes)
        all_winners = await self.__determine_winning_index(percentages)

        now = datetime.datetime.now()

        msg = "What game Friday?\n"
        for i, entry in enumerate(self.entries):
            name = entry.name
            count = self.votes[i]

            if i in all_winners:
                name = f"**{name}**"

            percentage = int(percentages[i])

            msg += f" {EMOJIS[i]} - {name}: `{count} votes ({percentage:.2f}%)`\n"

        msg += f"-# Last Updated <t:{int(now.timestamp())}:R>\n"
        msg += f"-# Poll ends <t:{int(self.end_timestamp.timestamp())}:R>\n"

        log.debug("Updating poll")
        await poll_message.edit(content=msg)

    async def __load_entries(self) -> list[models.event.EventEntry]:
        async with self.bot.session as session:
            entries = (await session.scalars(select(models.event.EventEntry))).all()

            # Make sure the list is in a determinstic order
            entries.sort(key=lambda x: x.name)

            assert len(entries) <= MAX_ENTRIES, "Too many entries in database"

            return entries

    async def __get_karma(self, user) -> float:
        async with self.bot.session as session:
            recent_records = await session.execute(
                select(models.event.EventMultipliers)
                .where(models.event.EventMultipliers.user_id == user.id)
                .order_by(models.event.EventMultipliers.timestamp.desc())
                .limit(10)
            )
            recent_records = recent_records.scalars().all()

            # has_attended_once = (
            #     await session.scalar(
            #         select(func.count())
            #         .select_from(models.event.EventMultipliers)
            #         .where(
            #             models.event.EventMultipliers.user_id == user_id,
            #             models.event.EventMultipliers.attended.is_(True),
            #         )
            #     )
            # ) > 0

            # has_global_records = (
            #     await session.scalar(
            #         select(func.count()).select_from(models.event.EventMultipliers)
            #     )
            # ) > 0

            # if not has_attended_once and has_global_records:
            #     return 0

            # to be uncommented if whomegalols start swaying votes too hard

            # attended = sum(1 for r in recent_records if r.attended)
            missed = sum(
                1 for r in recent_records if r.voted_for_winner and not r.attended
            )

            bonus = (
                await session.scalar(
                    select(models.event.EventBonus.bonus).where(
                        models.event.EventBonus.user_id == user.id
                    )
                )
            ) or 0

            karma = 100 - missed * 10
            return min(100, karma) + bonus

    # This is very slow, takes upwards of N seconds where N is the number of entries
    # TODO test if raw reactions can minimize this
    async def __get_votes(self, message) -> Counter[int]:
        votes = Counter()
        for reaction in message.reactions:
            if not reaction.emoji in EMOJIS:
                continue

            async for user in reaction.users():
                if user.bot:
                    continue

                index = EMOJIS.index(reaction.emoji)
                votes[index] += await self.__get_vote_value(reaction.emoji, user)

        return votes

    async def __get_vote_value(self, emoji, user) -> float:
        index = EMOJIS.index(emoji)
        entry = self.entries[index]

        multiplier = await self.__get_karma(user)
        value = multiplier * entry.weight

        return round(value / 100, 3)

    async def __get_percentages(self, votes) -> tuple[list[float], int]:
        assert self.entries, "Nothing to calculate percentages with"
        percentages = [0.0] * len(self.entries)

        total = sum(votes.values())

        for i, entry in enumerate(self.entries):
            count = votes[i]

            try:
                percentage = (count / total) * 100
            except ZeroDivisionError:
                percentage = 0

            percentages[i] = percentage

        return percentages, total

    async def __determine_winning_index(self, percentages) -> int:
        winning_percentage = max(percentages)
        all_winners = set()

        if winning_percentage == 0:
            return all_winners

        elif percentages.count(winning_percentage) > 1:
            log.debug("There are multiple winners, finding one at random")
            last_start = 0

            while True:
                try:
                    i = percentages.index(winning_percentage, last_start)
                except ValueError:
                    break

                last_start = i + 1

                all_winners.add(i)

        else:
            all_winners.add(percentages.index(winning_percentage))

        return all_winners

    async def __update_weights(self, winner) -> None:
        async with self.bot.session as session:
            async with session.begin():
                entries = (await session.scalars(select(models.event.EventEntry))).all()

                for entry in entries:
                    if entry.entry_id == winner.entry_id:
                        offset = WINNING_OFFSET
                    else:
                        offset = LOSING_OFFSET

                    entry.weight += offset

                log.info("Updated weights")

    async def __get_poll_channel(self) -> discord.TextChannel:
        channel_id = self.bot.config["channels"]["event_poll_channel"]
        assert channel_id != 0, "Poll channel ID is 0"

        poll_channel = self.bot.get_channel(channel_id)
        assert poll_channel, "no channel to get message from"

        return poll_channel

    async def __get_poll_message(self) -> discord.Message:
        poll_channel = await self.__get_poll_channel()

        poll_message = await poll_channel.fetch_message(self.message_id)
        assert poll_message, "no poll message found"

        return poll_message

    async def __set_automatic_state(self, value: bool) -> None:
        async with self.bot.session as session:
            async with session.begin():
                await config.set(session, AUTOMATIC_STATE_KEY, bool(value))

    async def __get_automatic_state(self) -> bool:
        async with self.bot.session as session:
            return bool(await config.get(session, AUTOMATIC_STATE_KEY, False))

    async def __set_last_automatic_start(self, date: datetime.date) -> None:
        assert isinstance(date, datetime.date), "argument is not a date"

        async with self.bot.session as session:
            async with session.begin():
                await config.set(session, AUTOMATIC_LAST_START_KEY, date)

    async def __get_last_automatic_start(self) -> datetime.date | None:
        async with self.bot.session as session:
            last_start = await config.get(session, AUTOMATIC_LAST_START_KEY)

            if isinstance(last_start, datetime.date):
                return last_start

        return None

    def __get_automatic_start_time(self) -> datetime.datetime:
        # UTC Monday
        return get_prev_weekday(0)

    def __get_automatic_end_time(self) -> datetime.datetime:
        # UTC Saturday (Friday in EDT)
        return get_next_weekday(5)

    def __get_automatic_next_time(self) -> datetime.datetime:
        # next UTC Monday
        return get_next_weekday(0)

    @commands.group(invoke_without_command=True)
    @commands.is_owner()
    async def poll(self, ctx):
        """
        Run poll related commands
        """
        command = ctx.command
        if command:
            await ctx.send_help(command)

    @poll.command(name="start")
    @commands.is_owner()
    @state_decorator
    async def startpoll(self, ctx):
        """
        Start the event poll
        """
        if self.poll_active is True:
            await ctx.send("poll already active")
            return

        entries = await self.__load_entries()

        if len(entries) < 2:
            await ctx.send("Not enough entries to start a poll with")

        await self.start_state(entries)

        with contextlib.suppress(discord.Forbidden):
            await ctx.message.delete()

    @poll.command(name="end")
    @commands.is_owner()
    @state_decorator
    async def endpoll(self, ctx):
        """
        End the event poll and announce a winner
        """
        if self.poll_active is False:
            await ctx.send("poll already stopped")
            return

        with contextlib.suppress(discord.Forbidden):
            await ctx.message.add_reaction("⏳")

        index, entries = await self.finish_state()

        if index > -1:
            winner = entries[index]
            await ctx.send(
                f"Poll closed! The winner is: {EMOJIS[index]} - {winner.name}"
            )

            await self.__update_weights(winner)
        else:
            await ctx.send("Poll closed! There is no winner")

        with contextlib.suppress(discord.Forbidden):
            await ctx.message.delete()

    @poll.command(name="cancel")
    @commands.is_owner()
    @state_decorator
    async def cancelpoll(self, ctx):
        """
        Cancel the event poll and dismiss the result
        """
        if self.poll_active is False:
            await ctx.send("poll already stopped")
            return

        with contextlib.suppress(discord.Forbidden):
            await ctx.message.add_reaction("⏳")

        await self.finish_state()

        with contextlib.suppress(discord.Forbidden):
            await ctx.message.remove_reaction("⏳", self.bot.user)
            await ctx.message.add_reaction("✅")

    @poll.command(name="when")
    @state_decorator
    async def whenpoll(self, ctx):
        """
        Check when the next poll will start or the current one will end
        """

        if self.poll_active is True:
            await ctx.send(
                f"The event poll will be closing <t:{int(self.end_timestamp.timestamp())}:R>."
            )
            return

        if await self.__get_automatic_state():
            next_start = self.__get_automatic_next_time()
            await ctx.send(
                f"The event poll will start <t:{int(next_start.timestamp())}:R>."
            )
            return

        await ctx.send("It is unknown when the next poll will start")

    @commands.group(invoke_without_command=True)
    async def event(self, ctx):
        command = ctx.command
        if command:
            await ctx.send_help(command)

    @event.command(name="add")
    @commands.is_owner()
    async def addevent(self, ctx, *, name):
        """
        Add games to the event poll
        """
        if not name:
            await ctx.send("No name specified")
            return

        if self.poll_active:
            await ctx.send("Cannot add event while poll is active")
            return

        async with self.bot.session as session:
            existing_entries = await self.__load_entries()

            if len(existing_entries) >= MAX_ENTRIES:
                await ctx.send(f"Cannot add more than {MAX_ENTRIES} entries")
                return

            for entry in existing_entries:
                if entry.name.lower() == name.lower():
                    await ctx.send(f"{name} is already an entry")
                    return

            async with session.begin():
                session.add(models.event.EventEntry(name=name))

        with contextlib.suppress(discord.Forbidden):
            await ctx.message.add_reaction("✅")

    @event.command(name="remove")
    @commands.is_owner()
    async def removeevent(self, ctx, *, name):
        """
        Remove a game from the event poll
        """
        if not name:
            await ctx.send("No name specified")
            return

        if self.poll_active:
            await ctx.send("Cannot remove event while poll is active")
            return

        async with self.bot.session as session:
            existing_entries = await self.__load_entries()

            if len(existing_entries) == 0:
                await ctx.send("There are no events to remove from")
                return

            for entry in existing_entries:
                if entry.name.lower() == name.lower():
                    async with session.begin():
                        await session.execute(
                            delete(models.event.EventEntry).where(
                                models.event.EventEntry.entry_id == entry.entry_id
                            )
                        )

                    with contextlib.suppress(discord.Forbidden):
                        await ctx.message.add_reaction("✅")

                    return

            await ctx.send("Could not find event")

        with contextlib.suppress(discord.Forbidden):
            await ctx.message.add_reaction("✅")

    @event.command(name="remove_all")
    @commands.is_owner()
    async def removeallevents(self, ctx):
        """
        Remove all games from the poll
        """
        if self.poll_active:
            await ctx.send("Cannot remove events while poll is active")
            return

        async with self.bot.session as session:
            existing_entries = await self.__load_entries()

            if len(existing_entries) == 0:
                await ctx.send("There are no events to remove from")
                return

            for entry in existing_entries:
                async with session.begin():
                    await session.execute(
                        delete(models.event.EventEntry).where(
                            models.event.EventEntry.entry_id == entry.entry_id
                        )
                    )

        with contextlib.suppress(discord.Forbidden):
            await ctx.message.add_reaction("✅")

    @event.command(name="change")
    async def changeevent(self, ctx, weight: float, *, name: str):
        """
        Change the weight of an event
        """

        if not name:
            await ctx.send("No name specified")
            return

        if self.poll_active:
            await ctx.send("Cannot remove event while poll is active")
            return

        existing_entries = await self.__load_entries()

        if len(existing_entries) == 0:
            await ctx.send("There are no events to modify")
            return

        for entry in existing_entries:
            if entry.name.lower() == name.lower():
                async with self.bot.session as session:
                    async with session.begin():
                        event_entry = (
                            await session.scalars(
                                select(models.event.EventEntry).where(
                                    models.event.EventEntry.entry_id == entry.entry_id
                                )
                            )
                        ).one_or_none()
                        assert event_entry != None, "Somehow the event is not real"

                        event_entry.weight = weight

                        await ctx.send(
                            f"{event_entry.name} has a new weight of {event_entry.weight}"
                        )
                    return

        await ctx.send("Could not find event")
        return

    @event.command(name="list")
    async def listevent(self, ctx):
        """
        List all games that are possible in the event
        """
        entries = await self.__load_entries()

        if not entries:
            await ctx.send("No entries found")
            return

        msg = "Entries:\n"
        for i, entry in enumerate(entries):
            weight = int(entry.weight * 100)
            msg += f" {EMOJIS[i]} - {entry.name} ({weight}%)\n"

        await ctx.send(msg)

    @commands.command(hidden=True)
    async def checkkarma(self, ctx, user: discord.User = None):
        """Check your or another user's voting karma"""
        if user is None:
            user = ctx.author

        karma = await self.__get_karma(user)
        async with self.bot.session as session:
            attended_count = await session.scalar(
                select(func.count())
                .select_from(models.event.EventMultipliers)
                .where(
                    models.event.EventMultipliers.user_id == user.id,
                    models.event.EventMultipliers.attended.is_(True),
                )
                .limit(10)
            )
            missed_count = await session.scalar(
                select(func.count())
                .select_from(models.event.EventMultipliers)
                .where(
                    models.event.EventMultipliers.user_id == user.id,
                    models.event.EventMultipliers.voted_for_winner.is_(True),
                    models.event.EventMultipliers.attended.is_(False),
                )
                .limit(10)
            )
        await ctx.send(
            f"Out of the last 10 events, {user.name} attended {attended_count} and missed {missed_count}. They have {karma} voting karma."
        )

    @commands.command(hidden=True)
    @commands.is_owner()
    async def addtoexpected(self, ctx, user: discord.User):
        if user.id not in self.winners:
            self.winners.append(user.id)
            await ctx.send(f"Added {user.name} to the expected attendees.")
        else:
            await ctx.send(f"{user.name} is already in the expected attendees list.")

    @commands.command(hidden=True)
    @commands.is_owner()
    async def removefromexpected(self, ctx, user: discord.User):
        if user.id in self.winners:
            self.winners.remove(user.id)
            await ctx.send(f"Removed {user.name} from the expected attendees.")
        else:
            await ctx.send(f"{user.name} is not in the expected attendees list.")

    @commands.command(hidden=True)
    @commands.is_owner()
    async def checkevent(self, ctx, event_id: int | None = None):
        """Check the results of a specific event by ID"""
        if event_id is None:
            async with self.bot.session as session:
                event_id = (
                    await session.scalar(
                        select(func.max(models.event.EventMultipliers.event_id))
                    )
                    or 0
                )
        async with self.bot.session as session:
            results = await session.execute(
                select(models.event.EventMultipliers).where(
                    models.event.EventMultipliers.event_id == event_id
                )
            )
            results = results.scalars().all()

        if not results:
            return await ctx.send(f"No results found for event ID {event_id}.")

        message = f"Results for event ID {event_id}:\n"
        for result in results:
            user = ctx.guild.get_member(result.user_id)
            if user:
                status = "Attended" if result.attended else "Did not attend"
                voted_status = (
                    "Voted for winner"
                    if result.voted_for_winner
                    else "Did not vote for winner"
                )
                message += f"{user.name}: {status}, {voted_status}\n"
            else:
                message += f"User ID {result.user_id} (not in server): {status}, {voted_status}\n"

        await ctx.send(message)

    @commands.command(hidden=True)
    @commands.is_owner()
    async def updateattendance(
        self,
        ctx,
        user: discord.User,
        event_id: int,
        attended: bool,
        voted_for_winner: bool,
    ):
        """Update attendance for a specific user in a specific event"""
        async with self.bot.session as session:
            async with session.begin():
                # Check if the user has already attended this event
                existing_record = await session.scalar(
                    select(models.event.EventMultipliers).where(
                        models.event.EventMultipliers.user_id == user.id,
                        models.event.EventMultipliers.event_id == event_id,
                    )
                )

                if existing_record:
                    # Update the existing record
                    existing_record.attended = attended
                    existing_record.voted_for_winner = voted_for_winner
                else:
                    # Create a new record
                    session.add(
                        models.event.EventMultipliers(
                            event_id=event_id,
                            user_id=user.id,
                            attended=attended,
                            voted_for_winner=voted_for_winner,
                            timestamp=datetime.datetime.now(datetime.UTC),
                        )
                    )
        karma = await self.__get_karma(user.id)

        await ctx.send(
            f"Attendance updated for {user.name} for event ID {event_id}. Their karma is now {karma}."
        )
        await user.send(
            f"Your attendance has been updated for event ID {event_id}. You {'attended' if attended else 'did not attend'} and {'voted for the winner' if voted_for_winner else 'did not vote for the winner'}. Your new karma is {karma}."
        )

    @commands.command()
    @commands.is_owner()
    async def monitorevent(self, ctx, vc: discord.VoiceChannel):
        self.event_vcs.append(vc.id)
        await ctx.send(f"Monitoring voice channel: {vc.name}")

    @commands.command()
    @commands.is_owner()
    async def endevent(self, ctx):
        if not self.event_vcs:
            return await ctx.send("No voice channel is being monitored.")

        timestamp = datetime.datetime.now(datetime.UTC)

        # merge winners + showed_up
        attendees = set(self.winners) | self.showed_up

        async with self.bot.session as session:
            async with session.begin():
                # generate a new event_id just once
                event_id = (
                    await session.scalar(
                        select(func.max(models.event.EventMultipliers.event_id))
                    )
                    or 0
                ) + 1

                for member_id in attendees:
                    attended = member_id in self.showed_up
                    voted_for_winner = member_id in self.winners

                    # record the result
                    session.add(
                        models.event.EventMultipliers(
                            event_id=event_id,
                            user_id=member_id,
                            attended=attended,
                            voted_for_winner=voted_for_winner,
                            timestamp=timestamp,
                        )
                    )

            for member_id in attendees:
                attended = member_id in self.showed_up
                voted_for_winner = member_id in self.winners
                member = ctx.guild.get_member(member_id)
                karma = await self.__get_karma(member)
                if not member:
                    continue  # user might have left

                try:
                    if attended and voted_for_winner:
                        # showed up and voted for the winner
                        await member.send(
                            f"🎉 Thanks for attending! Your voting karma is now {karma}."
                        )
                    elif attended:
                        await member.send(
                            f"Thanks for attending the event! Your voting karma is now {karma}."
                        )
                    else:  # voted_for_winner but didn't attend
                        await member.send(
                            f"You voted for the winner but didn't attend the event. "
                            f"Your voting karma is now {karma}."
                        )
                except discord.Forbidden:
                    # If the user has DMs disabled, we can't notify them
                    log.info(f"Could not send DM to {member.display_name}")

        # tidy up
        self.event_vcs = []
        self.winners = []
        self.showed_up.clear()
        self.pending_attendance.clear()
        await ctx.send("Event monitoring has been stopped.")

    @commands.group(invoke_without_command=True)
    @commands.is_owner()
    async def autopoll(self, ctx):
        """
        Check the autopoll state
        """
        if await self.__get_automatic_state():
            await ctx.send("Automatic polling is enabled")
        else:
            await ctx.send("Automatic polling is disabled")

    @autopoll.command(name="enable")
    @commands.is_owner()
    async def enable_autopoll(self, ctx):
        """
        Enable automatic poll management
        """
        await self.__set_automatic_state(True)
        await ctx.message.add_reaction("✅")

    @autopoll.command(name="disable")
    @commands.is_owner()
    async def disable_autopoll(self, ctx):
        """
        Disable automatic poll management
        """
        await self.__set_automatic_state(False)
        await ctx.message.add_reaction("✅")


async def setup(bot):
    await bot.add_cog(Event(bot))
