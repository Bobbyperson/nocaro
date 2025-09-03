import random as rd
import uuid

from aiohttp import web
from discord.ext import commands
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models
from __main__ import Session
from utils.miscfuncs import is_blacklisted

CORSHEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


# TODO update every callsite to pass sessions explicitly
# until then this will be used as a stop-gap solution
def session_decorator(func):
    async def wrapped(*args, **kwargs):
        session = None
        if not isinstance(args[0], AsyncSession):
            session = Session()
            args = list(args)
            args.insert(0, session)

        try:
            retval = await func(*args, **kwargs)
        except:
            if session is not None:
                await session.rollback()
            raise
        else:
            if session is not None:
                await session.commit()
        finally:
            if session is not None:
                await session.close()

        return retval

    return wrapped


class API(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.app = web.Application()
        self.app.router.add_get("/user/balance", self.get_user_bal)
        self.app.router.add_get("/games/slots", self.api_slots)
        self.app.router.add_get("/user/map", self.api_map)
        self.app.router.add_route("OPTIONS", "/user/balance", self.handle_options)
        self.app.router.add_route("OPTIONS", "/games/slots", self.handle_options)
        self.app.router.add_route("OPTIONS", "/user/map", self.handle_options)
        self.runner = web.AppRunner(self.app)

    async def handle_options(self, request):
        # do nothing, just respond with OK
        return web.Response(
            text="Options received",
            headers=CORSHEADERS,
        )

    async def validate_auth(self, token) -> (bool, bool):
        async with Session() as session:
            result = await session.execute(
                select(models.Api).where(models.Api.api_key == token)
            )
            api_key = result.scalars().first()
            if api_key is None:
                return False, False
            return True, api_key.can_write

    @session_decorator
    async def check_user_allowed(user_id):
        async with Session() as session:
            main_result = await session.execute(
                select(models.economy.Main).where(
                    models.economy.Main.user_ID == user_id
                )
            )
            user_main = main_result.scalars().first()
            if user_main is None:
                return False
            prestige_result = await session.execute(
                select(models.economy.Prestige).where(
                    models.economy.Prestige.user_ID == user_id
                )
            )
            user_prestige = prestige_result.scalars().first()
            if user_prestige is not None:
                pres_allowed = user_prestige.pres4 == 0
            blacklisted, _ = await is_blacklisted(user_id)
            return (
                user_main.api_consent
                and user_main.balance < (2 ** (64 - 1)) - 1
                and not blacklisted
                and pres_allowed
            )

    @session_decorator
    async def get_user_bal(self, session, request):
        auth_header = request.headers.get("authentication")
        is_valid, _ = await self.validate_auth(auth_header)
        if not is_valid:
            return web.Response(
                status=401,
                text="Invalid API key",
                headers=CORSHEADERS,
            )
        user_id = request.query.get("user_id")
        result = await session.execute(
            select(models.economy.Main).where(models.economy.Main.user_ID == user_id)
        )
        user_main = result.scalars().first()
        if user_main is None:
            return web.Response(
                status=400,
                text="No such user",
                headers=CORSHEADERS,
            )
        return web.Response(
            status=200,
            text=str(user_main.balance),
            headers=CORSHEADERS,
        )

    @session_decorator
    async def api_slots(self, session, request):
        auth_header = request.headers.get("authentication")
        is_valid, can_write = await self.validate_auth(auth_header)
        if not is_valid:
            return web.Response(status=401, text="Invalid API key", headers=CORSHEADERS)
        if not can_write:
            return web.Response(
                status=403, text="Insufficient permissions", headers=CORSHEADERS
            )
        user_id = request.query.get("user_id")
        bet = request.query.get("bet")
        if not self.check_user_allowed(user_id):
            return web.Response(
                status=403, text="User not allowed", headers=CORSHEADERS
            )
        try:
            bet = int(bet)
        except (ValueError, TypeError):
            return web.Response(
                status=400, text="Invalid bet amount", headers=CORSHEADERS
            )
        result = await session.execute(
            select(models.economy.Main).where(models.economy.Main.user_ID == user_id)
        )
        user_main = result.scalars().first()
        if user_main is None:
            return web.Response(status=400, text="No such user", headers=CORSHEADERS)
        if bet <= 0:
            return web.Response(
                status=400, text="Invalid bet amount", headers=CORSHEADERS
            )
        if bet > user_main.balance:
            return web.Response(
                status=402, text="Insufficient balance", headers=CORSHEADERS
            )
        result = {}
        jackpot = rd.randint(1, 350)
        s1 = rd.randint(0, 4)
        s2 = rd.randint(0, 4)
        s3 = rd.randint(0, 4)
        spins = rd.randint(3, 5)
        result["spinners"] = []
        for i in range(spins):
            s1 = rd.randint(0, 4)
            s2 = rd.randint(0, 4)
            s3 = rd.randint(0, 4)
            if rd.randint(1, 125) == 1 and i != spins - 1:
                s1 = 5
                s2 = 5
                s3 = 5
            result["spinners"].append([s1, s2, s3])
        winner = False
        if jackpot == 1:
            user_main.balance += bet * 20
            result["amount_won"] = bet * 20
            winner = True
            result["jackpot"] = True
            result["spinners"].append([5, 5, 5])
        elif s1 == s2 or s1 == s3 or s2 == s3:
            if s1 == s2 == s3:
                user_main.balance += bet * 3
                result["amount_won"] = bet * 3
            else:
                user_main.balance += bet
                result["amount_won"] = bet
            winner = True
        result["winner"] = winner
        return web.json_response(result, headers=CORSHEADERS)

    @session_decorator
    async def api_map(self, session, request):
        auth_header = request.headers.get("authentication")
        is_valid, can_write = await self.validate_auth(auth_header)
        if not is_valid:
            return web.Response(status=401, text="Invalid API key", headers=CORSHEADERS)
        if not can_write:
            return web.Response(
                status=403, text="Insufficient permissions", headers=CORSHEADERS
            )
        user_id = request.query.get("user_id")
        if not self.check_user_allowed(user_id):
            return web.Response(
                status=403, text="User not allowed", headers=CORSHEADERS
            )
        result = await session.execute(
            select(models.economy.Main).where(models.economy.Main.user_ID == user_id)
        )
        user_main = result.scalars().first()
        if user_main is None:
            return web.Response(status=400, text="No such user", headers=CORSHEADERS)
        banger = rd.randint(1, 10)
        earnings = rd.randint(0, 100)
        bangerearn = rd.randint(100, 500)
        if banger:
            user_main.balance += bangerearn
            return web.Response(status=200, text=str(bangerearn), headers=CORSHEADERS)
        else:
            user_main.balance += earnings
            return web.Response(status=200, text=str(earnings), headers=CORSHEADERS)

    @commands.command()
    @commands.is_owner()
    async def makekey(self, ctx, can_write: bool):
        async with Session() as session:
            api_key = models.Api(api_key=str(uuid.uuid4()), can_write=can_write)
            session.add(api_key)
            await session.commit()
        await ctx.author.send(f"API key created: {api_key.api_key}")

    @commands.hybrid_command()
    async def apiconsent(self, ctx):
        await ctx.send(
            "By consenting to API usage, you are allowing third parties to execute economy related commands on your behalf. Said third parties are vetted and trusted by the bot maintainer, but are nonetheless third party. Please type `I consent` to consent."
        )
        try:
            msg = await self.bot.wait_for(
                "message", check=lambda m: m.author == ctx.author, timeout=30
            )
            if msg.content.lower() == "i consent":
                await ctx.author.send("You have successfully consented to API usage.")
                async with Session() as session:
                    user_main = await session.execute(
                        select(models.economy.Main).where(
                            models.economy.Main.user_ID == ctx.author.id
                        )
                    )
                    user_main = user_main.scalars().first()
                    if user_main is None:
                        await ctx.author.send(
                            "You do not have an economy account. Please type `,map` and try again."
                        )
                        return
                    user_main.api_consent = True
                    await session.commit()
                    # await ctx.author.send("You have been granted API access.")
        except TimeoutError:
            return

    async def start_web_server(self):
        await self.runner.setup()
        site = web.TCPSite(self.runner, "0.0.0.0", 2586)
        await site.start()


async def setup(bot):
    await bot.add_cog(API(bot))
