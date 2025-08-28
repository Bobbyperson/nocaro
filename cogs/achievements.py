import discord
from discord.ext import commands

from utils.achievements import achievements_list, money_achievements_list
from utils.miscfuncs import generic_checks


class Achievements(commands.Cog):
    """Cog for managing achievements."""

    def __init__(self, client):
        self.client = client

    @commands.command(name="achievements")
    @generic_checks(max_check=False, dm_check=False)
    async def achievements(self, ctx, user: discord.User = None):
        """List all achievements."""
        if not user:
            user = ctx.author
        is_dm = isinstance(ctx.channel, discord.DMChannel)
        msg = ""
        for achievement in achievements_list:
            emoji = "✅" if await achievement.is_achieved(user) else "❌"
            msg += f"{emoji} "
            if achievement.hidden and not (
                is_dm and await achievement.is_achieved(user)
            ):
                msg += f"{''.join('?' if c not in [' ', ':', '*'] else c for c in str(achievement))} "
            else:
                msg += f"{achievement!s} "
            if achievement.progressable:
                progress = await achievement.get_progress(user)
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
    @generic_checks(max_check=False, dm_check=False)
    async def milestones(self, ctx, user: discord.User = None):
        """List all money-related achievements."""
        if not user:
            user = ctx.author
        is_dm = isinstance(ctx.channel, discord.DMChannel)
        msg = ""
        for achievement in money_achievements_list:
            emoji = "✅" if await achievement.is_achieved(user) else "❌"
            msg += f"{emoji} "
            if achievement.hidden and not (
                is_dm and await achievement.is_achieved(user)
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

    @commands.command()
    @commands.is_owner()
    async def grantachievement(
        self, ctx, user: discord.User, achievement_name: str = ""
    ):
        """Grant an achievement to a user."""
        if not achievement_name:
            await ctx.send("Please specify an achievement name.")
            return

        achievement = next(
            (a for a in achievements_list if a.name == achievement_name), None
        )
        if not achievement:
            await ctx.send("Achievement not found.")
            return

        await achievement.unlock(user)
        await ctx.send(f"Granted achievement **{achievement.name}** to {user.mention}.")

    @commands.command()
    @commands.is_owner()
    async def setachievementprogress(
        self, ctx, user: discord.User, achievement_name: str, progress: int
    ):
        """Set the progress of an achievement for a user."""
        achievement = next(
            (a for a in achievements_list if a.name == achievement_name), None
        )
        if not achievement:
            await ctx.send("Achievement not found.")
            return

        await achievement.set_progress(user, progress)
        await ctx.send(
            f"Set achievement **{achievement.name}** progress to {progress} for {user.mention}."
        )


async def setup(client):
    await client.add_cog(Achievements(client))
