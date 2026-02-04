from discord.ext import commands

from utils import config


class Config(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(invoke_without_command=True)
    @commands.is_owner()
    async def config(self, ctx):
        pass

    @config.command(name="get")
    @commands.is_owner()
    async def get_config(self, ctx, key: str):
        async with self.bot.session as session:
            await ctx.send(repr(await config.get(session, key)))

    @config.command(name="set")
    @commands.is_owner()
    async def set_config(self, ctx, key: str, *, value: str):
        real_value = eval(value)

        async with self.bot.session as session:
            async with session.begin():
                await config.set(session, key, real_value)


async def setup(bot):
    await bot.add_cog(Config(bot))
