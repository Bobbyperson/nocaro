import discord
from discord.ext import commands

from utils.achievements import achievements_list, money_achievements_list


class Achievements(commands.Cog):
    """Cog for managing achievements."""

    def __init__(self, client):
        self.client = client

    @commands.command(name="achievements")
    async def achievements(self, ctx):
        """List all achievements."""
        is_dm = isinstance(ctx.channel, discord.DMChannel)
        msg = ""
        for achievement in achievements_list:
            emoji = "✅" if await achievement.is_achieved(ctx.author) else "❌"
            msg += f"{emoji} "
            if achievement.hidden and not (
                is_dm and await achievement.is_achieved(ctx.author)
            ):
                msg += f"{''.join('?' if c not in [' ', ':', '*'] else c for c in str(achievement))} "
            else:
                msg += f"{achievement!s} "
            if achievement.progressable:
                progress = await achievement.get_progress(ctx.author)
                needed_progress = achievement.needed_progress
                msg += f"({progress}/{needed_progress})"
            msg += "\n"
        embed = discord.Embed(
            title="Achievements",
            description=msg,
            color=discord.Color.blue(),
        )
        embed.set_footer(
            text="Use this command in a DM to see unlocked hidden achievements."
        )
        await ctx.send(embed=embed)

    @commands.command()
    async def milestones(self, ctx):
        """List all money-related achievements."""
        is_dm = isinstance(ctx.channel, discord.DMChannel)
        msg = ""
        for achievement in money_achievements_list:
            emoji = "✅" if await achievement.is_achieved(ctx.author) else "❌"
            msg += f"{emoji} "
            if achievement.hidden and not (
                is_dm and await achievement.is_achieved(ctx.author)
            ):
                msg += f"{''.join('?' if c not in [' ', ':', '*'] else c for c in str(achievement))} "
            else:
                msg += f"{achievement!s} "
            msg += "\n"
        embed = discord.Embed(
            title="Achievements",
            description=msg,
            color=discord.Color.green(),
        )
        embed.set_footer(
            text="Use this command in a DM to see unlocked hidden achievements."
        )
        await ctx.send(embed=embed)


async def setup(client):
    await client.add_cog(Achievements(client))
