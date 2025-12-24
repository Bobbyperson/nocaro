import logging

from discord.ext import commands
from sqlalchemy import select

from models.awards import AwardUsers
from utils import config

log = logging.getLogger(__name__)

NOMINATE_STATE_KEY = "nominate_state"


class Awards(commands.Cog):
    def __init__(self, client):
        self.client = client

    async def __set_nominate(self, value: bool) -> None:
        async with self.client.session as session:
            async with session.begin():
                await config.set(session, NOMINATE_STATE_KEY, bool(value))

    async def __get_nominate(self) -> bool:
        async with self.client.session as session:
            return bool(await config.get(session, NOMINATE_STATE_KEY, False))

    async def __user_may_nominate(self, user_id: int) -> bool:
        async with self.client.session as session:
            async with session.begin():
                result = await session.get(AwardUsers, str(user_id))
                return result is not None

    # events
    @commands.Cog.listener()
    async def on_ready(self):
        log.info("Awards ready")

    @commands.command()
    @commands.is_owner()
    async def startnominate(self, ctx):
        await self.__set_nominate(True)

        async with self.client.session as session:
            result = await session.execute(select(AwardUsers.user_id).distinct())
            user_ids = result.scalars().all()
            for user_id in user_ids:
                try:
                    # get user from id
                    user = await self.client.fetch_user(int(user_id))
                    # send message to user
                    await user.send(
                        "Hello.\n\nYou are considered an active or otherwise notable member of the awesome titanfall server. We will be hosting a fun server awards ceremony on our 4th anniversary, Friday, January 9th, 2026 at 8:00 PM EST. We need YOUR help in nominating other members for awards. Nominations will close January 2nd, 2026. When they close, I will dm you again asking you to pick your choice from the nominees. When you are ready, please type `,nominate` in this dm. Your nominations will be kept confidential. Joke nominations will be ignored (e.g. Clair Obscure: Expedition 33). Please do not nominate yourself for any award, it will be ignored. If you make a mistake or change your mind, you may re-run the command, which will overwrite your previous responses. If you have any questions, please dm Bobbyperson.\n\nThank you for your time and effort."
                    )
                except Exception as e:
                    log.error(f"Failed to send message to user {user_id}: {e}")
                    await ctx.send(f"Failed to send message to user {user_id}: {e}")
        await ctx.send("Nominations started")

    @commands.command()
    async def nominate(self, ctx):
        if not await self.__get_nominate():
            await ctx.send("Nominations are not currently open.")
            return
        # check if dm
        if ctx.guild is not None:
            await ctx.send("Please run this command in a dm with me.")
            return
        if not await self.__user_may_nominate(ctx.author.id):
            await ctx.send(
                "You are not eligible to nominate for awards, if you believe this is an error or an oversight, please dm Bobbyperson. Sorry."
            )
            return

        await ctx.send(
            'I will ask you a question one at a time, please answer each one to the best of your ability. If you make a mistake or change your mind, you may re-run the command, which will overwrite your previous responses. If you believe your response may be interpreted as "out there" or a joke, you may provide a brief explanation. All answers will be reviewed and kept confidential. If you have any questions, please dm Bobbyperson.'
        )
        questions = [
            "Most likely to ragebait and succeed",
            "Most likely to ragebait and fail",
            "Most likely to fall for ragebait",
            "Best server era (CS, Deadlock, Overwatch, OG Northstar, Minecraft 202X, etc.)",
            "Best event game (you may include games previously but not currently in the poll)",
            "Most likely to gamble away their life savings",
            "The VC award: This award should go to the member who you think improves and contributes the most to a vc",
            "Most likely to hijack a vc",
            "Best clip (go to #clips and copy the message link and paste it here)",
            "Most talented",
            "Best quote (go to #quotes and copy the message link and paste it here)",
            "Shining beacon (most positively influential person)",
            "Most impactful member: who has had the most positive impact on the server/community? Please also specify how/why.",
            "Who is your member of the year? This is our main award for the year. You may nominate anyone for any reason, but you MUST include a brief explanation for your nomination.",
        ]
        answers = []
        for question in questions:
            await ctx.send(question)

            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel

            try:
                msg = await self.client.wait_for("message", check=check, timeout=900)
            except Exception:
                await ctx.send(
                    "You took too long to respond. Nothing you inputted has been saved. Please run the command again if you wish to nominate."
                )
                return
            answers.append(msg.content)
        # send to me
        owner = await self.client.fetch_user(self.client.owner_id)
        nomination_message = f"Nominations from {ctx.author} ({ctx.author.id}):\n\n"
        for question, answer in zip(questions, answers):
            nomination_message += f"**{question}**\n{answer}\n\n"
        await owner.send(nomination_message)
        await ctx.send("Thank you for your nominations! They have been recorded.")

    @commands.command()
    @commands.is_owner()
    async def addnominate(self, ctx, *users):
        """Add a user to the list of users who may nominate for awards."""
        for user_id in users:
            async with self.client.session as session:
                async with session.begin():
                    award_user = AwardUsers(user_id=str(user_id))
                    session.add(award_user)
            if await self.__get_nominate():
                try:
                    user = await self.client.fetch_user(int(user_id))
                    await user.send(
                        "Hello.\n\nYou are considered an active or otherwise notable member of the awesome titanfall server. We will be hosting a fun server awards ceremony on our 4th anniversary, Friday, January 9th, 2026 at 8:00 PM EST. We need YOUR help in nominating other members for awards. Nominations will close January 2nd, 2026. When they close, I will dm you again asking you to pick your choice from the nominees. When you are ready, please type `,nominate` in this dm. Your nominations will be kept confidential. Joke nominations will be ignored (e.g. Clair Obscure: Expedition 33). Please do not nominate yourself for any award, it will be ignored. If you make a mistake or change your mind, you may re-run the command, which will overwrite your previous responses. If you have any questions, please dm Bobbyperson.\n\nThank you for your time and effort."
                    )
                except Exception as e:
                    log.error(f"Failed to send message to user {user_id}: {e}")
                    await ctx.send(f"Failed to send message to user {user_id}: {e}")
        await ctx.send("Users added to nomination list.")

    @commands.command()
    @commands.is_owner()
    async def removenominate(self, ctx, user_id: int):
        """Remove a user from the list of users who may nominate for awards."""
        async with self.client.session as session:
            async with session.begin():
                award_user = await session.get(AwardUsers, str(user_id))
                if award_user is not None:
                    await session.delete(award_user)
                    await ctx.send(f"User {user_id} removed from nomination list.")
                else:
                    await ctx.send(f"User {user_id} not found in nomination list.")


async def setup(client):
    await client.add_cog(Awards(client))
