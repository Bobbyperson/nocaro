import discord
from discord.ext import commands, tasks
from collections import Counter
import aiosqlite
import asyncio

bank = "./data/database.sqlite"


class Poll(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.poll_message = None
        self.poll_options = []
        self.poll_emojis = []
        self.votes = Counter()
        self.update_poll.start()
        self.bot.loop.create_task(self.initialize_db())
        self.update_poll.add_exception_type(asyncio.TimeoutError)
        self.update_poll.add_exception_type(discord.errors.DiscordServerError)

    async def initialize_db(self):
        async with aiosqlite.connect(bank) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS vote_multipliers (
                    user_id INTEGER PRIMARY KEY,
                    multiplier INTEGER
                )
            """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS poll_state (
                    message_id INTEGER,
                    options TEXT
                )
            """
            )
            await db.commit()

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
        async with aiosqlite.connect(bank) as db:
            await db.execute("DELETE FROM poll_state")
            await db.execute(
                "INSERT INTO poll_state (message_id, options) VALUES (?, ?)",
                (self.poll_message.id, options),
            )
            await db.commit()

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
        async with aiosqlite.connect(bank) as db:
            async with db.execute(
                "SELECT multiplier FROM vote_multipliers WHERE user_id = ?", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return row[0]
                return 1

    @commands.command(aliases=["pullup"])
    @commands.is_owner()
    async def addmultiplier(self, ctx, user: discord.User, multiplier: int = 2):
        """Add or update a user's vote multiplier"""
        async with aiosqlite.connect(bank) as db:
            await db.execute(
                "INSERT OR REPLACE INTO vote_multipliers (user_id, multiplier) VALUES (?, ?)",
                (user.id, multiplier),
            )
            await db.commit()
        await ctx.send(f"Vote multiplier for {user.name} has been set to {multiplier}.")

    @commands.command(aliases=["pullout"])
    @commands.is_owner()
    async def removemultiplier(self, ctx, user: discord.User):
        """Remove a user's vote multiplier"""
        async with aiosqlite.connect(bank) as db:
            await db.execute(
                "DELETE FROM vote_multipliers WHERE user_id = ?", (user.id,)
            )
            await db.commit()
        await ctx.send(f"Vote multiplier for {user.name} has been removed.")

    @commands.command()
    @commands.is_owner()
    async def clearmultipliers(self, ctx):
        """Clear all vote multipliers"""
        async with aiosqlite.connect(bank) as db:
            await db.execute("DELETE FROM vote_multipliers")
            await db.commit()
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
        async with aiosqlite.connect(bank) as db:
            async with db.execute(
                "SELECT message_id, options FROM poll_state"
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    self.poll_message = await ctx.fetch_message(row[0])
                    self.poll_options = row[1].split(",")
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
