import random as rd

import aiohttp
from discord.ext import commands

from utils.miscfuncs import generic_checks


class Image(commands.Cog):
    """Commands that send images."""

    def __init__(self, client):
        self.client = client

    @commands.command(hidden=True)
    @commands.has_permissions(attach_files=True)
    @commands.cooldown(1, 1, commands.BucketType.default)
    @commands.max_concurrency(1, commands.BucketType.user, wait=True)
    @generic_checks(max_check=False)
    async def sans(self, ctx):
        """The best command."""
        if rd.randint(1, 100) == 1:
            await ctx.reply(
                f"{ctx.author.mention} https://www.youtube.com/watch?v=JSZVepiXDek"
            )
        else:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://dog.ceo/api/breeds/image/random"
                ) as response:
                    dog = await response.json()
                    if dog["status"] == "success":
                        await ctx.reply(dog["message"])
                    else:
                        await ctx.reply(f"Dog API failed. :( `{dog}`")


async def setup(client):
    await client.add_cog(Image(client))
