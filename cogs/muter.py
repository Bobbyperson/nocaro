import asyncio

import discord
from discord.ext import commands


class Muter(commands.Cog):
    def __init__(self, client):
        self.client = client

    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def muteall(self, ctx, channel: discord.VoiceChannel, delay: int = 10):
        if not channel:
            channel = ctx.author.voice.channel
        if not channel:
            await ctx.send("You are not in a voice channel nor did you specify one..")
            return
        await ctx.send(
            f"Muting all members in {channel.mention} if they are not self muted in {delay} seconds."
        )
        await asyncio.sleep(delay)
        for member in channel.members:
            if not member.voice.self_mute:
                await member.edit(mute=True)
        await ctx.send("Done")

    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def unmuteall(self, ctx, channel: discord.VoiceChannel):
        if not channel:
            channel = ctx.author.voice.channel
        if not channel:
            await ctx.send("You are not in a voice channel nor did you specify one..")
            return
        await ctx.send(f"Unmuting all members in {channel.mention}.")
        for member in channel.members:
            await member.edit(mute=False)
        await ctx.send("Done")


async def setup(client):
    await client.add_cog(Muter(client))
