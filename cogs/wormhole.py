import discord
from discord.ext import commands


class wormhole(commands.Cog):
    def __init__(self, client):
        self.client = client

    # events
    @commands.Cog.listener()
    async def on_ready(self):
        print("wormhole ready")

    @commands.command(hidden=True)
    @commands.is_owner()
    async def wormhole(self, ctx, channel_id):
        channel_t = await self.client.fetch_channel(channel_id)

        def check(msg):
            return (
                msg.channel == channel_t
                or msg.channel == ctx.channel
                and msg.author != self.client.user
            )

        await ctx.send("Opening wormhole.")
        while True:
            try:
                msg = await self.client.wait_for("message", check=check, timeout=180)
            except discord.errors.NotFound:
                await ctx.send("No activity. Cancelling")
                return
            if msg.content == "end transmission" and msg.author == ctx.author:
                await ctx.send("Ending transmission")
                return
            if msg.channel == channel_t:
                await ctx.send(f"{msg.author}: {msg.content}")
            if msg.channel == ctx.channel and msg.author == ctx.author:
                await channel_t.send(msg.content)


async def setup(client):
    await client.add_cog(wormhole(client))
