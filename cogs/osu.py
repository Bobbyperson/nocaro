import asyncio
import logging
import math
import time

import aiohttp
import discord
from discord.ext import commands
from sqlalchemy import select

import models
import utils.econfuncs as econ
import utils.miscfuncs as mf

log = logging.getLogger(__name__)

def get_unix():
    return int(time.time())


# async def get_quals():  # probably not needed
#     with open("osu.txt", "r") as f:
#         token = f.read()
#     url = "https://osu.ppy.sh/api/v2/"
#     headers = {
#         "Accept": "application/json",
#         "Content-Type": "application/json",
#         "Authorization": f"Bearer {token}",
#     }
#     ext = "beatmapsets/search?m=0&s=qualified"
#     x = requests.get(url + ext, headers=headers)
#     data = x.json()
#     if x.status == 401:  # forbidden (fucked token)
#         await refresh_token()
#         await asyncio.sleep(1)
#         await get_quals()
#     return data


# async def get_map_data(id: int):
#     with open("osu.txt", "r") as f:
#         token = f.read()
#     url = "https://osu.ppy.sh/api/v2/"
#     headers = {
#         "Accept": "application/json",
#         "Content-Type": "application/json",
#         "Authorization": f"Bearer {token}",
#     }
#     ext = f"beatmapsets/{id}"
#     x = requests.get(url + ext, headers=headers)
#     data = x.json()
#     if x.status == 401:  # forbidden (fucked token)
#         await refresh_token()
#         await asyncio.sleep(1)
#         await get_map_data(id)
#     return data, x.status


# async def get_rank_status(
#     ranked: int,
# ):  # https://osu.ppy.sh/docs/#beatmapset-rank-status
#     if ranked == -2:
#         status = "graveyard"
#     if ranked == -1:
#         status = "wip"
#     if ranked == 0:
#         status = "pending"
#     if ranked == 1:
#         status = "ranked"
#     if ranked == 2:
#         status = "approved"
#     if ranked == 3:
#         status = "qualified"
#     if ranked == 4:
#         status = "loved"
#     return status


# async def get_current_bets():
#     with open("bets.json", "r") as f:
#         data = json.load(f)
#     return data


# async def get_current_pending():
#     with open("ranked.json", "r") as f:
#         data = json.load(f)
#     return data


async def calculate_reward(investment, old_score, current_score):
    M = (math.log2(old_score / current_score) + 1) ** 2
    return investment * M, M


class osu(commands.Cog):
    """Invest in osu players"""

    def __init__(self, client):
        self.client = client
        self.osu_token = None
        # self.check_if_ranked.add_exception_type(asyncpg.PostgresConnectionError)
        # self.check_if_ranked.start()
        # self.give_rewards.add_exception_type(asyncpg.PostgresConnectionError)
        # self.give_rewards.start()

    # def cog_unload(self):
    #     self.check_if_ranked.cancel()
    #     self.give_rewards.cancel()

    async def refresh_token(self):  # token lasts for one day
        client_id = self.client.config["osu"]["client_id"]
        client_secret = self.client.config["osu"]["client_secret"]
        if not client_secret or not client_secret:
            raise Exception("Client ID or Secret not set")

        url = "https://osu.ppy.sh/oauth/token"
        myjson = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": "public",
        }
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=myjson, headers=headers) as resp:
                data = await resp.json()
                try:
                    self.osu_token = str(data["access_token"])
                except KeyError:
                    raise Exception(data["error_description"])

    async def get_user_rank(self, id: int):
        token = self.osu_token
        url = "https://osu.ppy.sh/api/v2/"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        ext = f"users/{id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url + ext, headers=headers) as resp:
                data = await resp.json()
                if resp.status == 401:  # forbidden (fucked token)
                    await self.refresh_token()
                    await asyncio.sleep(1)
                    return await self.get_user_rank(id)
                elif resp.status != 200:
                    return None
                try:
                    return data["statistics"]["global_rank"]
                except KeyError:
                    return None

    async def get_user_name(self, id: int):
        token = self.osu_token
        url = "https://osu.ppy.sh/api/v2/"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        ext = f"users/{id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url + ext, headers=headers) as x:
                data = await x.json()
                if x.status == 401:  # forbidden (fucked token)
                    await self.refresh_token()
                    await asyncio.sleep(1)
                    return await self.get_user_name(id)
                elif x.status != 200:
                    return None
                try:
                    return data["username"]
                except KeyError:
                    return None

    @commands.Cog.listener()
    async def on_ready(self):
        log.info("Osu ready")

    @commands.command(hidden=True)
    async def getrank(self, ctx, id):
        await ctx.send(await self.get_user_rank(id))

    @commands.hybrid_command()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @mf.generic_checks()
    async def invest(self, ctx, osu_id: int = 0, amount: str | None = None):
        """Invest in an osu player."""
        if osu_id == 0:
            return await ctx.send("Please enter a valid user id.")
        amount = econ.moneyfy(amount)
        if amount == 0:
            return await ctx.send("Please enter an amount.")
        if amount < 0:
            return await ctx.send("Please enter a positive amount.")
        total_bal = await econ.get_bal(ctx.author)
        if total_bal < amount:
            return await ctx.send("You don't have that many bouge bucks! Go `,map`")
        async with self.client.session as session:
            async with session.begin():
                results = (
                    await session.scalars(
                        select(models.osu.Osu).where(
                            models.osu.Osu.osu_user == osu_id,
                            models.osu.Osu.user_id == ctx.author.id,
                        )
                    )
                ).one_or_none()

                if results is not None:
                    await ctx.send(
                        "You already invested in that user! Please sell first."
                    )
                    return

                osu_score = await self.get_user_rank(osu_id)
                if not osu_score:
                    return await ctx.send(
                        "That user doesn't exist! Please go to osu.ppy.sh and find a valid user id!"
                    )
                osu_name = await self.get_user_name(osu_id)

                session.add(
                    models.osu.Osu(
                        user_id=ctx.author.id,
                        score=osu_score,
                        timestamp=int(time.time()),
                        amount=amount,
                        osu_user=osu_id,
                    )
                )

            await ctx.send(
                f"You have successfully invested {amount} bouge bucks in {osu_name}."
            )
            await econ.update_amount(
                ctx.author, -1 * amount, tracker_reason="osuinvest"
            )

    @commands.hybrid_command()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @mf.generic_checks()
    async def sell(self, ctx, id):
        """Sell your investment on an osu player."""
        async with self.client.session as session:
            async with session.begin():
                results = (
                    await session.scalars(
                        select(models.osu.Osu).where(
                            models.osu.Osu.osu_user == id,
                            models.osu.Osu.user_id == ctx.author.id,
                        )
                    )
                ).one_or_none()

                if results is None:
                    await ctx.send("You haven't invested in that user!")
                    return

                new_score = await self.get_user_rank(id)
                osu_name = await self.get_user_name(id)
                old_score = results.score
                investment = results.amount

                await session.delete(results)

            reward, mult = await calculate_reward(investment, old_score, new_score)
            await ctx.send(
                f"You just sold your investment {osu_name} for {mf.commafy(int(reward))} bouge bucks (~{round(mult, 3)}x {old_score} -> {new_score})!"
            )
            await econ.update_amount(ctx.author, reward, tracker_reason="osusell")

    @commands.hybrid_command(aliases=["investments", "checkinvestment"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    @mf.generic_checks(max_check=False)
    async def checkinvestments(self, ctx, user: discord.User = None):
        """Check your investments on osu players."""
        if not user:
            user = ctx.author
        async with ctx.typing():
            async with self.client.session as session:
                results = (
                    await session.scalars(
                        select(models.osu.Osu).where(models.osu.Osu.user_id == user.id)
                    )
                ).all()

                if not results:
                    await ctx.send("You haven't invested yet!")
                    return

                message = ""
                for result in results:
                    osu_name = await self.get_user_name(result.osu_user)
                    new_score = await self.get_user_rank(result.osu_user)
                    initial_investment = result.amount
                    reward, mult = await calculate_reward(
                        initial_investment, result.score, new_score
                    )
                    profit = reward - initial_investment
                    pos = "+" if new_score < result.score else ""
                    message += f"{osu_name} ({result.osu_user}) | {pos}{mf.commafy(int(profit))} (~{round(mult, 3)}x {result.score} -> {new_score})\n"
                await ctx.send(message)

    @commands.command(hidden=True)
    async def rewardtest(self, ctx, old: int = 1, new: int = 1):
        _, mult = await calculate_reward(1, old, new)
        await ctx.send(mult)

    # @commands.command(hidden=True)
    # async def checkmap(self, ctx, id):
    #     data = await get_map_data(id)
    #     ranked = data["ranked"]
    #     name = data["title"]
    #     mapper = data["creator"]
    #     status = await get_rank_status(ranked)
    #     await ctx.send(f"{name} mapped by {mapper} current status is {status}")

    # @commands.command(hidden=True)
    # async def bet(
    #     self,
    #     ctx,
    #     map: int = None,
    #     plays: int = None,
    #     amount: int = None,
    #     days: int = None,
    # ):
    #     """Main map betting command
    #     Args:
    #         map (int): Beatmapset ID. Will not work with beatmap id.
    #         plays (int): Bet for end amount of plays.
    #         amount (int): Amount to bet.
    #         days (int): Minimum 3, days the person wants this bet to go on for.
    #     """

    #     def check(msg):
    #         return msg.author == ctx.author and msg.content.lower() in ["yes", "no"]

    #     if (
    #         map == None or plays == None or amount == None or days == None
    #     ):  # idiot proofing
    #         await ctx.send("Argument not specified")
    #         return
    #     map_data, code = await get_map_data(map)
    #     if code != 200:  # 200 == OK
    #         await ctx.send("FUCK!")
    #         return
    #     if map_data["ranked"] != 3:
    #         await ctx.send("This map isn't qualified! You may not bet on it!")
    #         return
    #     if days < 3:
    #         await ctx.send("Minimum day count is 3!")
    #         return
    #     if amount < 100:
    #         await ctx.send("Minimum bet is 100!")
    #         return
    #     if plays < 0:
    #         await ctx.send("Nice try.")
    #         return
    #     if days > 259200:  # for schizos that want to do exact seconds
    #         bet_time = days
    #     else:
    #         bet_time = (
    #             86400 * days
    #         )  # it will compare unix timestamps, thats why this is in seconds
    #     current = await get_current_bets()
    #     if str(ctx.author.id) not in current:  # do not clear if new bet
    #         current[str(ctx.author.id)] = {}
    #     if str(map) in current[str(ctx.author.id)]:  # do not do anything if same map
    #         await ctx.send("You can't bet on a map twice!!!!!")
    #         return
    #     ranked = map_data["ranked"]
    #     name = map_data["title"]
    #     mapper = map_data["creator"]
    #     await ctx.send(
    #         f"Please confirm:\nYou are betting **{amount}** bouge bucks that once **{name}** mapped by **{mapper}** gets ranked, it will have **{plays}** plays in **{days}** days.\nRespond: **Yes** or **No**."
    #     )
    #     try:
    #         msg = await self.client.wait_for("message", check=check, timeout=15)
    #     except:
    #         return
    #     if msg.content.lower() == "no":
    #         await ctx.send("Cancelled.")
    #         return
    #     else:
    #         current[str(ctx.author.id)][
    #             str(map)
    #         ] = {}  # create brace shit, possibly not necessary idk
    #         current[str(ctx.author.id)][str(map)]["plays"] = str(plays)
    #         current[str(ctx.author.id)][str(map)]["amount"] = str(amount)
    #         current[str(ctx.author.id)][str(map)]["time"] = str(bet_time)
    #         with open("bets.json", "w") as f:
    #             json.dump(current, f, indent=4)
    #         await ctx.send(
    #             f"Confirmed. You will be recieving periodic update DMs."
    #         )  # lie

    # @tasks.loop(
    #     seconds=60
    # )  # fully untested, will be very hard to test in general :WAAH:
    # async def check_if_ranked(self):
    #     """Here I will do my best to explain this untested code:
    #     It first loads the maps that we currently consider "qualified." (Betted maps) bets.json
    #     It then loads maps that have been ranked or otherwise unqualified whos bets have not expired. ranked.json
    #     In the json it begins looping through each user then each map.
    #     If user "X's" map "123" is not longer in quals, remove from bets.json and add to ranked.json
    #     Inform user.
    #     """
    #     bets = await get_current_bets()  # bets.json
    #     current = await get_current_pending()  # ranked.json
    #     for user in bets:
    #         for map in bets[str(user)]:
    #             data, code = await get_map_data(map)
    #             if code != 200:  # idiot proofing
    #                 return
    #             if data["ranked"] != 3:
    #                 the_user = await self.client.fetch_user(int(user))
    #                 data.pop(str(user))[str(map)]
    #                 if str(user) not in current:  # do not clear if new bet
    #                     current[str(user)] = {}
    #                 if str(map) in current[str(user)]:  # do not do anything if same map
    #                     print(
    #                         "WARNING. WARNING. FUCK UP. FUCK UP. JSONS FUCKED."
    #                     )  # if this prints i will cry
    #                     return
    #                 ranked = data["ranked"]
    #                 name = data["title"]
    #                 mapper = data["creator"]
    #                 status = await get_rank_status(ranked)
    #                 plays = int(bets[str(user)][str(map)]["plays"])
    #                 amount = int(bets[str(user)][str(map)]["amount"])
    #                 bet_time = int(bets[str(user)][str(map)]["time"])
    #                 current[str(user)][str(map)] = {}
    #                 current[str(user)][str(map)]["plays"] = str(plays)
    #                 current[str(user)][str(map)]["amount"] = str(amount)
    #                 current[str(user)][str(map)]["time"] = str(get_unix() + bet_time)
    #                 current[str(user)][str(map)]["ogtime"] = str(bet_time)
    #                 with open("ranked.json", "w") as f:
    #                     json.dump(current, f, indent=4)
    #                 await the_user.send(
    #                     f"{name} mapped by {mapper} current status is {status}."
    #                 )

    # @tasks.loop(seconds=60)
    # async def give_rewards(self):
    #     current = await get_current_pending()  # ranked.json
    #     for user in current:
    #         for map in current[str(user)]:
    #             data, code = await get_map_data(map)
    #             if code != 200:  # idiot proofing
    #                 return
    #             if int(current[str(user)][str(map)]["time"]) < get_unix():
    #                 bet_plays = int(current[str(user)][str(map)]["plays"])
    #                 amount = int(current[str(user)][str(map)]["amount"])
    #                 bet_time = int(current[str(use # client_id and client_secret should absolutely fucking not be hard coded: too bad!r)][str(map)]["time"])
    #                 og_time = int(current[str(user)][str(map)]["ogtime"])
    #                 actual_plays = data["play_count"]
    #                 if actual_plays > bet_plays:
    #                     per_diff = int(
    #                         math.abs(bet_time / actual_plays) / actual_plays
    #                     )  # | m - r | over r
    #                 else:
    #                     per_diff = 1 - actual_plays / bet_plays
    #                 if per_diff >= 35:
    #                     x = per_diff
    #                     k = 2.2
    #                     n = 0.6
    #                     l = 35
    #                     reward_mult = (
    #                         -0.06 * x + 2.1 - (1 / 0.6) * (np.tan((x - 35) / 42.081))
    #                     )  # https://www.desmos.com/calculator/olw4iigs7t
    #                 else:
    #                     x = per_diff
    #                     k = 2.2
    #                     n = 0.6
    #                     l = 35
    #                     reward_mult = (
    #                         -0.06 * x + 2.1 - (1 / 0.6) * (np.tan((x - 35) / 22.982))
    #                     )
    #                 reward = amount * reward_mult
    #                 the_user = await self.client.fetch_user(int(user))
    #                 await the_user.send(
    #                     f"Yo yo yo yo yo what it is motherfucker! Your bet results came back and you earned {reward} bouge bucks! The map currently has {actual_plays} and you bet that it would have {bet_plays} within {og_time/86400} days."
    #                 )
    #                 current.pop(str(user))[str(map)]
    #                 with open("ranked.json", "w") as f:
    #                     json.dump(current, f, indent=4)


async def setup(client):
    await client.add_cog(osu(client))
