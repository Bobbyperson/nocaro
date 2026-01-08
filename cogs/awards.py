import logging
from collections import defaultdict

from discord.ext import commands
from sqlalchemy import select

from models.awards import AwardUsers, Votes
from utils import config

log = logging.getLogger(__name__)

NOMINATE_STATE_KEY = "nominate_state"

VOTING_STATE_KEY = "voting_state"

NOMINEES = {
    "Most likely to ragebait and succeed": ["Ping", "War", "Walm"],
    "Most likely to ragebait and fail": ["Bobbyperson", "Fuddge", "Spicy"],
    "Most likely to fall for ragebait": ["Kirby", "Spicy", "Bobbyperson", "Fuddge"],
    "Best event": [
        "Among Us",
        "Titanfall 2",
        "Tabletop Simulator",
        "Garry's Mod",
        "Lethal Company",
    ],
    "Most impactful member": [
        "Rena",
        "War",
        "Ping",
        "Bobbyperson",
        "Yote",
        "Deed",
        "Nori",
    ],
    "VC Award": ["Coffee", "Yote", "War", "Rena", "Bobbyperson"],
    "VC hijack": ["Walm", "War", "Bobbyperson", "Spicy"],
    "Most talented": [
        "Moonsy - Art",
        "Jan - Programming",
        "Bobbyperson - Programming",
        "Flairon - Art",
        "Spungus - Aim",
    ],
    "Shining beacon": [
        "Yote",
        "Cyan",
        "Spungus",
        "War",
        "Nori",
        "Bobbyperson",
        "Rena",
    ],
    "Member of the year": ["Bobbyperson", "Spungus", "War"],
    "Best quote": [
        "https://discord.com/channels/929895874799226881/949523674229248010/1376470800387014769",
        "https://discord.com/channels/929895874799226881/949523674229248010/1419815543074066623",
        "https://discord.com/channels/929895874799226881/949523674229248010/1341291181308510288",
        "https://discord.com/channels/929895874799226881/949523674229248010/1442283996053766296",
        "https://discord.com/channels/929895874799226881/949523674229248010/1418750863437987911",
    ],
    "Best clip": [
        "https://discord.com/channels/929895874799226881/1096518296293093518/1401058812873408712",
        "https://discord.com/channels/929895874799226881/1096518296293093518/1348163871294226505",
        "https://discord.com/channels/929895874799226881/1096518296293093518/1449310748739375196",
        "https://discord.com/channels/929895874799226881/1096518296293093518/1384447513049698356",
        "https://discord.com/channels/929895874799226881/1096518296293093518/1379286896555069541",
        "https://discord.com/channels/929895874799226881/1096518296293093518/1310047019527831563",
        "https://discord.com/channels/929895874799226881/1096518296293093518/1447413359480803630",
        "https://discord.com/channels/929895874799226881/1096518296293093518/1360419026907430912",
    ],
}


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

    async def __set_voting(self, value: bool) -> None:
        async with self.client.session as session:
            async with session.begin():
                await config.set(session, VOTING_STATE_KEY, bool(value))

    async def __get_voting(self) -> bool:
        async with self.client.session as session:
            return bool(await config.get(session, VOTING_STATE_KEY, False))

    async def create_or_update_vote(
        self, user_id: int, question: str, answer: int
    ) -> None:
        async with self.client.session as session:
            async with session.begin():
                result = await session.execute(
                    select(Votes).where(
                        Votes.user_id == str(user_id),
                        Votes.question == question,
                    )
                )
                vote = result.scalar_one_or_none()

                if vote is None:
                    session.add(
                        Votes(user_id=str(user_id), question=question, answer=answer)
                    )
                else:
                    vote.answer = answer

    async def get_voters(self, question: str) -> list[int]:
        async with self.client.session as session:
            async with session.begin():
                result = await session.execute(
                    select(Votes.user_id).where(Votes.question == question)
                )
                return result.scalars().all()

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
    async def getvoteresults(self, ctx, show_voters: bool = False):
        async with self.client.session as session:
            for question, nominees in NOMINEES.items():
                result = await session.execute(
                    select(Votes.user_id, Votes.answer).where(
                        Votes.question == question
                    )
                )
                rows = result.all()

                by_answer: dict[int, list[int]] = defaultdict(list)
                for user_id, answer in rows:
                    try:
                        by_answer[int(answer)].append(int(user_id))
                    except (TypeError, ValueError):
                        continue

                msg_lines = [f"**Question:** {question}"]

                for i, nominee in enumerate(nominees, start=1):
                    voter_ids = by_answer.get(i, [])
                    line = f"{i}. {nominee}: {len(voter_ids)} votes"

                    if show_voters and voter_ids:
                        names = []
                        for uid in voter_ids:
                            try:
                                user = await self.client.fetch_user(uid)
                                names.append(user.name)
                            except Exception:
                                names.append(str(uid))
                        line += f" ({', '.join(names)})"

                    msg_lines.append(line)

                skips = by_answer.get(0, [])
                if skips:
                    msg_lines.append(f"0. Skipped: {len(skips)}")

                await ctx.send("\n".join(msg_lines))

    @commands.command()
    @commands.is_owner()
    async def startvoting(self, ctx):
        await self.__set_voting(True)
        async with self.client.session as session:
            result = await session.execute(select(AwardUsers.user_id).distinct())
            user_ids = result.scalars().all()
            for user_id in user_ids:
                try:
                    # get user from id
                    user = await self.client.fetch_user(int(user_id))
                    # send message to user
                    await user.send(
                        "Hello.\n\nThe second phase of voting has begun. Please type `,vote` in this dm to vote for your favorite nominees. You may vote for yourself this time around. Voting ends Thursday. Please do not share who you voted for until after January 9th, as to avoid spoiling the winners.\n\n**Please join us for our award ceremony on our 4th anniversary, Friday, January 9th, 2026 at 8:00 PM EST.** It will be recorded if you cannot attend. Also deadass I wanted to send this out ages ago but I got the Flu sorry."
                    )
                except Exception as e:
                    log.error(f"Failed to send message to user {user_id}: {e}")
                    await ctx.send(f"Failed to send message to user {user_id}: {e}")
        await ctx.send("Voting started")

    @commands.command()
    @commands.max_concurrency(1, commands.BucketType.user)
    async def vote(self, ctx):
        if not await self.__get_voting():
            await ctx.send("Voting is not currently open.")
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
            "I will ask you a question one at a time. Respond to each question with the number of your favorite nominee. You may type `0` to skip. If you have any questions, please dm Bobbyperson."
        )

        for question, nominees in NOMINEES.items():
            msg = f"Question: {question}\n"
            for i, nominee in enumerate(nominees):
                msg += f"{i + 1}. {nominee}\n"
            await ctx.send(msg)
            try:
                response = await self.client.wait_for(
                    "message",
                    check=lambda m: m.author.id == ctx.author.id
                    and m.channel == ctx.channel
                    and m.content.isdigit()
                    and int(m.content) <= len(nominees)
                    and int(m.content) >= 0,
                    timeout=300,
                )
            except TimeoutError:
                await ctx.send(
                    "You took too long to answer. Please run the command again."
                )
                return
            await self.create_or_update_vote(
                ctx.author.id, question, int(response.content)
            )

        await ctx.send("Thanks for voting!")

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
    @commands.max_concurrency(1, commands.BucketType.user)
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
        owner = await self.client.fetch_user(self.client.config["general"]["owner_id"])
        nomination_message = f"Nominations from {ctx.author} ({ctx.author.id}):\n\n"
        for question, answer in zip(questions, answers):
            nomination_message += f"**{question}**\n{answer}\n\n"
        if len(nomination_message) > 2000:
            for i in range(0, len(nomination_message), 1990):
                await owner.send(nomination_message[i : i + 1990])
        else:
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

    @commands.command()
    @commands.is_owner()
    async def revote(self, ctx):
        async with self.client.session as session:
            result = await session.execute(select(AwardUsers.user_id).distinct())
            user_ids = result.scalars().all()
            for user_id in user_ids:
                try:
                    # get user from id
                    user = await self.client.fetch_user(int(user_id))
                    # send message to user
                    await user.send(
                        "Hello. There was a bug in the vote recording. This has caused all responses to be unusable. **Please re-vote as soon as possible.** The voting deadline has been extended to 1 hour before the awards ceremony. You may vote again with `,vote`."
                    )
                except Exception as e:
                    log.error(f"Failed to send message to user {user_id}: {e}")
                    await ctx.send(f"Failed to send message to user {user_id}: {e}")
        await ctx.send("Revote started")


async def setup(client):
    await client.add_cog(Awards(client))
