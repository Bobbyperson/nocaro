from discord.ext import commands
import random


class theory(commands.Cog):
    def __init__(self, client):
        self.client = client

    @commands.command(hidden=True)
    async def theory(self, ctx, word=None):
        theories = ["Theory", "Theorem", "Method"]
        if not word:
            with open("theory.txt", "r") as f:
                words = [line.rstrip() for line in f.readlines()]
                word = random.choice(words)
        await ctx.send("The " + word.title() + " " + random.choice(theories))


async def setup(client):
    await client.add_cog(theory(client))
