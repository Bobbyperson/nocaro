import asyncio

import discord
from discord.ext import commands


class Muter(commands.Cog):
    def __init__(self, client):
        self.client = client
        self.monitors = []

    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def muteall(self, ctx, channel: discord.VoiceChannel = None, delay: int = 10):
        if not channel and ctx.author.voice:
            channel = ctx.author.voice.channel
        else:
            await ctx.send("You are not in a voice channel nor did you specify one.")
            return
        self.monitors.append(channel.id)
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
    async def unmuteall(self, ctx, channel: discord.VoiceChannel = None):
        if not channel and ctx.author.voice:
            channel = ctx.author.voice.channel
        else:
            await ctx.send("You are not in a voice channel nor did you specify one.")
            return
        if channel.id not in self.monitors:
            await ctx.send(f"{channel.mention} is not being monitored.")
            return
        self.monitors.remove(channel.id)
        await ctx.send(f"Unmuting all members in {channel.mention}.")
        for member in channel.members:
            if not member.voice.self_mute and member.voice.mute:
                await member.edit(mute=False)
        await ctx.send("Done")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if not after.channel:
            if before.channel.id in self.monitors:
                await member.edit(mute=False)
        if after.channel.id in self.monitors:
            await asyncio.sleep(5)
            if not member.voice.self_mute:
                await member.edit(mute=True)


async def setup(client):
    await client.add_cog(Muter(client))
