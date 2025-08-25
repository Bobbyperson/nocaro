import random

import anyio
import discord
from discord.ext import commands

from utils.miscfuncs import generic_checks


class theory(commands.Cog):
    def __init__(self, client):
        self.client = client

    @commands.command(hidden=True)
    @generic_checks(max_check=False)
    async def theory(self, ctx, word=None):
        theories = ["Theory", "Theorem", "Method"]
        if not word:
            async with await anyio.open_file("templates/theory.txt") as f:
                words = [line.rstrip() for line in await f.readlines()]
                word = random.choice(words)
        await ctx.send(
            discord.utils.escape_mentions(
                "The " + word.title() + " " + random.choice(theories)
            )
        )


async def setup(client):
    await client.add_cog(theory(client))
