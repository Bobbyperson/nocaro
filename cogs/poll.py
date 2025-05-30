import asyncio
from collections import Counter

import discord
from discord.ext import commands, tasks
from sqlalchemy import delete, select

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
                        multiplier = await self.get_vote_multiplier(user.id)
                        self.votes[reaction.emoji] += multiplier

            total_votes = sum(self.votes.values())
            if total_votes > 0:
                message = "What game Friday?"
                for i, option in enumerate(self.poll_options):
                    count = self.votes[self.poll_emojis[i]]
                    percentage = (count / total_votes) * 100
                    message += f"\n{self.poll_emojis[i]} - {option}: `{count} votes ({int(percentage)}%)`"
                await self.poll_message.edit(content=message)

    async def get_vote_multiplier(self, user_id):
        async with self.bot.session as session:
            result = (
                await session.scalars(
                    select(models.poll.VoteMultipliers).where(
                        models.poll.VoteMultipliers.user_id == user_id
                    )
                )
            ).one_or_none()

            if result is not None:
                return result.multiplier
            return 1

    @commands.command(aliases=["pullup"])
    @commands.is_owner()
    async def addmultiplier(self, ctx, user: discord.User, multiplier: int = 2):
        """Add or update a user's vote multiplier"""
        async with self.bot.session as session:
            async with session.begin():
                await session.merge(
                    models.poll.VoteMultipliers(
                        user_id=user.id,
                        multiplier=multiplier,
                    )
                )
        await ctx.send(f"Vote multiplier for {user.name} has been set to {multiplier}.")

    @commands.command(aliases=["pullout"])
    @commands.is_owner()
    async def removemultiplier(self, ctx, user: discord.User):
        """Remove a user's vote multiplier"""
        async with self.bot.session as session:
            async with session.begin():
                await session.execute(
                    delete(models.poll.VoteMultipliers).where(
                        models.poll.VoteMultipliers.user_id == user.id
                    )
                )
        await ctx.send(f"Vote multiplier for {user.name} has been removed.")

    @commands.command()
    @commands.is_owner()
    async def clearmultipliers(self, ctx):
        """Clear all vote multipliers"""
        async with self.bot.session as session:
            async with session.begin():
                await session.execute(delete(models.poll.VoteMultipliers))
        await ctx.send("All vote multipliers have been cleared.")

    @commands.command()
    @commands.is_owner()
    async def disablepoll(self, ctx):
        """Disable the current poll updating"""
        self.update_poll.cancel()
        await ctx.send("Poll updating has been disabled.")

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

    @update_poll.before_loop
    async def before_update_poll(self):
        await self.bot.wait_until_ready()


async def setup(client):
    await client.add_cog(Poll(client))
