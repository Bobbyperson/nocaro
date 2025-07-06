import asyncio
import datetime as dt
from collections import Counter

import discord
from discord.ext import commands, tasks
from sqlalchemy import delete, func, select

import models


class Poll(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.poll_message = None
        self.poll_options = []
        self.poll_emojis = []
        self.votes = Counter()
        self.update_poll.start()
        self.update_poll.add_exception_type(asyncio.TimeoutError)
        self.update_poll.add_exception_type(discord.errors.DiscordServerError)
        self.winners = []  # stores list of users who voted for the winner
        self.warned_voters = False
        self.pending_attendance = {}  # user_id -> join_time
        self.showed_up = set()  # user_ids who were present >= 30min
        self.event_vcs = []  # voice channel being monitored
        self.should_end_poll = False  # flag to end the poll

    @commands.command(aliases=["cep"])
    @commands.is_owner()
    async def createeventpoll(self, ctx, *, options: str):
        """Create a poll for an event"""
        emojis = [
            "1️⃣",
            "2️⃣",
            "3️⃣",
            "4️⃣",
            "5️⃣",
            "6️⃣",
            "7️⃣",
            "8️⃣",
            "9️⃣",
            "0️⃣",
        ]
        self.poll_options = options.split(",")
        self.poll_emojis = []  # Reset poll_emojis list
        message = "What game Friday?"
        for i, option in enumerate(self.poll_options):
            message += f"\n{emojis[i]} - {option}"
            self.poll_emojis.append(emojis[i])

        self.poll_message = await ctx.send(message)
        for emoji in self.poll_emojis:
            await self.poll_message.add_reaction(emoji)
        await ctx.message.delete()
        self.votes = Counter()

        # Save poll state to the database
        async with self.bot.session as session:
            async with session.begin():
                await session.execute(delete(models.poll.PollState))
                session.add(
                    models.poll.PollState(
                        message_id=self.poll_message.id,
                        options=options,
                    )
                )

    @tasks.loop(seconds=10.0)
    async def update_poll(self):
        if self.poll_message:
            self.votes = Counter()  # Reset the votes counter at the beginning
            cache_msg = await self.poll_message.channel.fetch_message(
                self.poll_message.id
            )
            for reaction in cache_msg.reactions:
                if reaction.emoji in self.poll_emojis:
                    async for user in reaction.users():
                        if user.bot:
                            continue
                        multiplier = await self.get_karma(user.id)
                        self.votes[reaction.emoji] += round(multiplier / 100, 3)

            total_votes = sum(self.votes.values())
            if total_votes > 0:
                message = "What game Friday?"
                for i, option in enumerate(self.poll_options):
                    count = self.votes[self.poll_emojis[i]]
                    percentage = (count / total_votes) * 100
                    message += f"\n{self.poll_emojis[i]} - {option}: `{count} votes ({int(percentage)}%)`"
                await self.poll_message.edit(content=message)
            if (
                dt.datetime.now(dt.UTC)
                .astimezone(dt.timezone(dt.timedelta(hours=-5)))
                .weekday()
                == 4
                and dt.datetime.now(dt.UTC)
                .astimezone(dt.timezone(dt.timedelta(hours=-5)))
                .hour
                >= 17
                and not self.warned_voters
            ):
                # Warn voters if it's past 5 pm on a Friday
                warning_message = "The event poll will be closing in one hour. If you cannot attend, please remove your vote to avoid losing future voting power."
                users = []
                for reaction in cache_msg.reactions:
                    if reaction.emoji in self.poll_emojis:
                        async for user in reaction.users():
                            if not user.bot and user not in users:
                                users.append(user)

                for user in users:
                    try:
                        await user.send(warning_message)
                    except discord.Forbidden:
                        pass

                self.warned_voters = True

            # if past 6 pm on a friday, remember voters of winner
            if (
                discord.utils.utcnow()
                .astimezone(dt.timezone(dt.timedelta(hours=-5)))
                .weekday()
                == 4
                and discord.utils.utcnow()
                .astimezone(dt.timezone(dt.timedelta(hours=-5)))
                .hour
                >= 18
            ) or self.should_end_poll:
                # refresh the message so we have every reaction in the latest order
                cache_msg = await self.poll_message.channel.fetch_message(
                    self.poll_message.id
                )

                # pick the emoji with the highest weighted vote total
                if not self.votes:  # nothing voted yet
                    return

                winner_emoji = max(self.votes, key=self.votes.get)

                winner_reaction = discord.utils.get(
                    cache_msg.reactions, emoji=winner_emoji
                )

                if winner_reaction is None:  # probably won't ever happen
                    await self.poll_message.channel.send(
                        "⚠️  Couldn't locate the winning reaction; poll not closed."
                    )
                    return

                await self.poll_message.channel.send(
                    f"Poll closed! The winner is: {winner_emoji} - {self.poll_options[self.poll_emojis.index(winner_emoji)]}"
                )

                self.winners = [
                    user.id async for user in winner_reaction.users() if not user.bot
                ]

                # swap in the fresh message copy so future accesses are up-to-date
                self.poll_message = cache_msg

                # shut the loop down until a new poll is started
                self.update_poll.stop()
                self.warned_voters = False

    async def get_karma(self, user_id: int) -> int:
        async with self.bot.session as session:
            recent_records = await session.execute(
                select(models.poll.VoteMultipliers)
                .where(models.poll.VoteMultipliers.user_id == user_id)
                .order_by(models.poll.VoteMultipliers.timestamp.desc())
                .limit(10)
            )
            recent_records = recent_records.scalars().all()

            # has_attended_once = (
            #     await session.scalar(
            #         select(func.count())
            #         .select_from(models.poll.VoteMultipliers)
            #         .where(
            #             models.poll.VoteMultipliers.user_id == user_id,
            #             models.poll.VoteMultipliers.attended.is_(True),
            #         )
            #     )
            # ) > 0

            # has_global_records = (
            #     await session.scalar(
            #         select(func.count()).select_from(models.poll.VoteMultipliers)
            #     )
            # ) > 0

            # if not has_attended_once and has_global_records:
            #     return 0

            # to be uncommented if whomegalols start swaying votes too hard

            attended = sum(1 for r in recent_records if r.attended)
            missed = sum(
                1 for r in recent_records if r.voted_for_winner and not r.attended
            )

            bonus = (
                await session.scalar(
                    select(models.poll.Bonuses.bonus).where(
                        models.poll.Bonuses.user_id == user_id
                    )
                )
            ) or 0

            karma = 50 + attended * 5 - missed * 10
            return max(0, min(100, karma)) + bonus

    @commands.command()
    @commands.is_owner()
    async def cancelpoll(self, ctx):
        """Cancel the current poll updating"""
        self.update_poll.cancel()
        self.warned_voters = False
        await ctx.send("Poll updating has been canceled.")

    @commands.command()
    @commands.is_owner()
    async def endpoll(self, ctx):
        self.should_end_poll = True
        await ctx.send("Poll has been ended.")

    @commands.command()
    @commands.is_owner()
    async def resumepoll(self, ctx):
        """Resume a poll after bot shutdown"""
        async with self.bot.session as session:
            result = (
                await session.scalars(select(models.poll.PollState))
            ).one_or_none()
            if result:
                self.poll_message = await ctx.fetch_message(result.message_id)
                self.poll_options = result.options.split(",")
                self.poll_emojis = [
                    "1️⃣",
                    "2️⃣",
                    "3️⃣",
                    "4️⃣",
                    "5️⃣",
                    "6️⃣",
                    "7️⃣",
                    "8️⃣",
                    "9️⃣",
                    "0️⃣",
                ][: len(self.poll_options)]
                self.votes = Counter()
                # if update_poll isn't running, start it
                if not self.update_poll.is_running():
                    self.update_poll.start()
                confirmmessage = await ctx.send("Poll has been resumed.")
                await ctx.message.delete()
                await asyncio.sleep(5)
                await confirmmessage.delete()
            else:
                await ctx.send("No poll found to resume.")

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

        timestamp = dt.datetime.now(dt.UTC)

        # merge winners + showed_up
        attendees = set(self.winners) | self.showed_up

        async with self.bot.session as session:
            async with session.begin():
                # generate a new event_id just once
                event_id = (
                    await session.scalar(
                        select(func.max(models.poll.VoteMultipliers.event_id))
                    )
                    or 0
                ) + 1

                for member_id in attendees:
                    attended = member_id in self.showed_up
                    voted_for_winner = member_id in self.winners

                    # record the result
                    session.add(
                        models.poll.VoteMultipliers(
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
                karma = await self.get_karma(member_id)
                member = ctx.guild.get_member(member_id)
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
                    print(f"[Poll] Could not send DM to {member.display_name}")

        # tidy up
        self.event_vcs = []
        self.winners = []
        self.showed_up.clear()
        self.pending_attendance.clear()
        await ctx.send("Event monitoring has been stopped.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if not self.event_vcs or not member.voice:
            return
        if member.bot or member.voice.channel.id not in self.event_vcs:
            return
        # User joins VC
        if before.channel is None and after.channel is not None:
            self.pending_attendance[member.id] = dt.datetime.now(dt.UTC)

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
                    print(f"[Poll] counted {member.display_name} as attended")  # debug

            if not hasattr(self, "background_tasks"):
                self.background_tasks = set()
            task = asyncio.create_task(wait_and_mark())
            self.background_tasks.add(task)
            task.add_done_callback(self.background_tasks.discard)

        # User leaves VC
        elif (
            before.channel.id in self.event_vcs
            and after.channel is None
            and member.id in self.pending_attendance
            and member.id not in self.showed_up
        ):
            self.pending_attendance.pop(member.id, None)
            self.showed_up.discard(member.id)
            # await member.send("You left the VC. You won't be counted unless you stay 30 minutes next time.")

    @update_poll.before_loop
    async def before_update_poll(self):
        await self.bot.wait_until_ready()

    @commands.command(hidden=True)
    async def checkkarma(self, ctx, user: discord.User = None):
        """Check your or another user's voting karma"""
        if user is None:
            user = ctx.author

        karma = await self.get_karma(user.id)
        async with self.bot.session as session:
            attended_count = await session.scalar(
                select(func.count())
                .select_from(models.poll.VoteMultipliers)
                .where(
                    models.poll.VoteMultipliers.user_id == user.id,
                    models.poll.VoteMultipliers.attended.is_(True),
                )
            )
            missed_count = await session.scalar(
                select(func.count())
                .select_from(models.poll.VoteMultipliers)
                .where(
                    models.poll.VoteMultipliers.user_id == user.id,
                    models.poll.VoteMultipliers.voted_for_winner.is_(True),
                    models.poll.VoteMultipliers.attended.is_(False),
                )
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
    async def checkevent(self, ctx, event_id):
        """Check the results of a specific event by ID"""
        async with self.bot.session as session:
            results = await session.execute(
                select(models.poll.VoteMultipliers).where(
                    models.poll.VoteMultipliers.event_id == event_id
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
                    select(models.poll.VoteMultipliers).where(
                        models.poll.VoteMultipliers.user_id == user.id,
                        models.poll.VoteMultipliers.event_id == event_id,
                    )
                )

                if existing_record:
                    # Update the existing record
                    existing_record.attended = attended
                    existing_record.voted_for_winner = voted_for_winner
                else:
                    # Create a new record
                    session.add(
                        models.poll.VoteMultipliers(
                            event_id=event_id,
                            user_id=user.id,
                            attended=attended,
                            voted_for_winner=voted_for_winner,
                            timestamp=dt.datetime.now(dt.UTC),
                        )
                    )
        karma = await self.get_karma(user.id)

        await ctx.send(
            f"Attendance updated for {user.name} for event ID {event_id}. Their karma is now {karma}."
        )
        await user.send(
            f"Your attendance has been updated for event ID {event_id}. You {'attended' if attended else 'did not attend'} and {'voted for the winner' if voted_for_winner else 'did not vote for the winner'}. Your new karma is {karma}."
        )


async def setup(client):
    await client.add_cog(Poll(client))
