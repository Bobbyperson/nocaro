import random
import tomllib

import discord
from discord.ext import commands

import utils.miscfuncs as mf

with open("config.toml", "rb") as f:
    config = tomllib.load(f)


class Fun(commands.Cog):
    def __init__(self, client):
        self.client = client

    # events
    @commands.Cog.listener()
    async def on_ready(self):
        print("Fun ready.")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        if message.content.startswith(","):
            return
        if message.content.lower() in ["share", "steal"]:
            return
        blacklisted = await mf.is_blacklisted(message.author.id)
        if blacklisted[0]:
            return
        if isinstance(message.channel, discord.channel.DMChannel):
            if message.author.id in config["blacklists"]["blacklisted_dms"]:
                return
            me = await self.client.fetch_user(config["general"]["owner_id"])
            await me.send(
                f"DM from {message.author.name} ({message.author.id})\n{message.content}\n`,dm {message.author.id}`"
            )
            if message.attachments:
                for attachment in message.attachments:
                    await me.send(attachment.url)

    # commands

    @commands.hybrid_command()
    async def ip(self, ctx, user: discord.Member = None):
        ip1 = random.randint(1, 255)
        ip2 = random.randint(0, 255)
        ip3 = random.randint(0, 255)
        ip4 = random.randint(1, 255)
        while ip1 == 192 and ip2 == 168:
            ip1 = random.randint(1, 255)
            ip2 = random.randint(0, 255)
        if user is not None:
            await ctx.send(f"{user.name}'s ip address is {ip1}.{ip2}.{ip3}.{ip4}")
        else:
            await ctx.send(f"{ip1}.{ip2}.{ip3}.{ip4}")

    @commands.command(aliases=["8ball", "ask"], hidden=True)
    async def _8ball(self, ctx, *, question):
        if not question:
            return await ctx.send("Please ask a question.")
        responses = [
            "It is certain.",
            "It is decidedly so.",
            "Without a doubt.",
            "Yes - definitely.",
            "You may rely on it.",
            "As I see it, yes.",
            "Most likely.",
            "Outlook good.",
            "Yes.",
            "Signs point to yes.",
            "Reply hazy, try again.",
            "Ask again later.",
            "Better not tell you now.",
            "Cannot predict now.",
            "Concentrate and ask again.",
            "Don't count on it.",
            "My reply is no.",
            "My sources say no.",
            "Outlook not so good.",
            "Very doubtful.",
        ]
        await ctx.send(
            discord.utils.escape_mentions(
                f"Question: {question}\nAnswer: {random.choice(responses)}"
            )
        )

    @commands.command(hidden=True)
    @commands.is_owner()
    async def dm(self, ctx, user: discord.Member, *, message: str):
        """DM the user of your choice"""
        if not user:
            return await ctx.send(f"Could not find any UserID matching **{user.name}**")

        try:
            await user.send(message)
            await ctx.send(f"✉️ Sent a DM to **{user.name}**")
        except discord.Forbidden:
            await ctx.send(
                "This user might be having DMs blocked or it's a bot account..."
            )

    @commands.command()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def createpoll(self, ctx, amount: int = 0):
        """Make a poll"""
        if amount > 10 or amount < 1:
            await ctx.send("Number must be between 1 and 10 inclusive.")
        if ctx.message.reference:
            original = await ctx.fetch_message(ctx.message.reference.message_id)
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
            for i in range(amount):
                await original.add_reaction(emojis[i])
            await ctx.message.delete()
        else:
            await ctx.send("reply to a message and try again")

    @commands.command()
    async def howtosay(self, ctx):
        """How do you pronounce Nocaro?"""
        await ctx.send("Nocaro: `/noʊ-kə-roʊ/` (noh-cuh-row)\nBouge: `/bu:ʒ/` (booj)")


async def setup(client):
    await client.add_cog(Fun(client))
