import random as rd
import time
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


def session_decorator(func):
    async def wrapped(*args, **kwargs):
        # Expect a bound method: args[0] is `self`
        if not args:
            # Fallback: no self (unlikely here), treat like a function
            session_provided = args and isinstance(args[0], AsyncSession)
            session = args[0] if session_provided else Session()
            new_args = args if session_provided else (session, *args)
            try:
                retval = await func(*new_args, **kwargs)
                if not session_provided:
                    await session.commit()
                return retval
            except Exception:
                if not session_provided:
                    await session.rollback()
                raise
            finally:
                if not session_provided:
                    await session.close()

        self = args[0]
        session_provided = len(args) > 1 and isinstance(args[1], AsyncSession)

        if session_provided:
            # Session came in as the second arg already
            return await func(*args, **kwargs)

        # Create and insert session as the second arg
        session = Session()
        new_args = (self, session, *args[1:])
        try:
            retval = await func(*new_args, **kwargs)
            await session.commit()
            return retval
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

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
        self.app.router.add_get("/", self.root_redirect)
        self.app.router.add_route("OPTIONS", "/", self.handle_options)

        self.runner = web.AppRunner(self.app)

        self.cooldowns = {}

    async def root_redirect(self, request):
        raise web.HTTPMovedPermanently("https://github.com/Bobbyperson/nocaro")

    async def add_cooldown(self, user_id, cmd: str, timestamp: int):
        # check if cooldowns["cmd"] exists
        if cmd not in self.cooldowns:
            self.cooldowns[cmd] = {}
        self.cooldowns[cmd][user_id] = timestamp + int(time.time())

    async def check_cooldown(self, user_id, cmd: str):
        if cmd not in self.cooldowns:
            return False
        user_cooldown = self.cooldowns[cmd].get(user_id)
        if user_cooldown is None:
            return False
        return user_cooldown > int(time.time())

    @commands.Cog.listener()
    async def on_ready(self):
        await self.start_web_server()

    async def handle_options(self, request):
        # do nothing, just respond with OK
        return web.Response(
            text="Options received",
            headers=CORSHEADERS,
        )

    async def validate_auth(self, token) -> (bool, bool):
        async with Session() as session:
            result = await session.execute(
                select(models.api.Api).where(models.api.Api.api_key == token)
            )
            api_key = result.scalars().first()
            if api_key is None:
                return False, False
            return True, api_key.can_write

    @session_decorator
    async def check_user_allowed(self, session, user_id):
        main_result = await session.execute(
            select(models.economy.Main).where(models.economy.Main.user_ID == user_id)
        )
        user_main = main_result.scalars().first()
        if user_main is None:
            return False
        prestiege_result = await session.execute(
            select(models.economy.Prestiege).where(
                models.economy.Prestiege.user_id == user_id
            )
        )
        user_prestiege = prestiege_result.scalars().first()
        if user_prestiege is not None:
            pres_allowed = user_prestiege.pres4 == 0
        blacklisted, _ = await is_blacklisted(user_id)
        return (
            user_main.api_consent
            and int(user_main.balance) < (2 ** (64 - 1)) - 1
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
        if not await self.check_user_allowed(user_id):
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
        if bet > int(user_main.balance):
            return web.Response(
                status=402, text="Insufficient balance", headers=CORSHEADERS
            )
        if await self.check_cooldown(user_id, "slots"):
            return web.Response(status=429, text="Cooldown active", headers=CORSHEADERS)
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
            user_main.balance = str(int(user_main.balance) + bet * 20)
            result["amount_won"] = bet * 20
            winner = True
            result["jackpot"] = True
            result["spinners"].append([5, 5, 5])
            session.add(
                models.economy.History(
                    user_id=user_main.user_ID,
                    amount=str(bet * 20),
                    reason="api_map",
                    time=int(time.time()),
                )
            )
        elif s1 == s2 or s1 == s3 or s2 == s3:
            if s1 == s2 == s3:
                user_main.balance = str(int(user_main.balance) + bet * 3)
                result["amount_won"] = bet * 3
                session.add(
                    models.economy.History(
                        user_id=user_main.user_ID,
                        amount=str(bet * 3),
                        reason="api_map",
                        time=int(time.time()),
                    )
                )
            else:
                user_main.balance = str(int(user_main.balance) + bet)
                result["amount_won"] = bet
                session.add(
                    models.economy.History(
                        user_id=user_main.user_ID,
                        amount=str(bet),
                        reason="api_map",
                        time=int(time.time()),
                    )
                )
            winner = True
        else:
            result["amount_won"] = 0
        result["winner"] = winner
        await self.add_cooldown(user_id, "slots", 3)
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
        if not await self.check_user_allowed(user_id):
            return web.Response(
                status=403, text="User not allowed", headers=CORSHEADERS
            )
        if await self.check_cooldown(user_id, "map"):
            return web.Response(status=429, text="Cooldown active", headers=CORSHEADERS)
        result = await session.execute(
            select(models.economy.Main).where(models.economy.Main.user_ID == user_id)
        )
        user_main = result.scalars().first()
        if user_main is None:
            return web.Response(status=400, text="No such user", headers=CORSHEADERS)
        banger = rd.randint(1, 10)
        earnings = rd.randint(0, 100)
        bangerearn = rd.randint(100, 500)
        if banger == 1:
            user_main.balance = str(int(user_main.balance) + bangerearn)
            session.add(
                models.economy.History(
                    user_id=user_main.user_ID,
                    amount=str(bangerearn),
                    reason="api_map",
                    time=int(time.time()),
                )
            )
            await self.add_cooldown(user_id, "map", 72)
            return web.Response(status=200, text=str(bangerearn), headers=CORSHEADERS)
        else:
            user_main.balance = str(int(user_main.balance) + earnings)
            session.add(
                models.economy.History(
                    user_id=user_main.user_ID,
                    amount=str(earnings),
                    reason="api_map",
                    time=int(time.time()),
                )
            )
            await self.add_cooldown(user_id, "map", 72)
            return web.Response(status=200, text=str(earnings), headers=CORSHEADERS)

    @session_decorator
    async def actuallymakekey(self, session, can_write: bool):
        key = uuid.uuid4()
        api_key = models.api.Api(api_key=str(key), can_write=can_write)
        session.add(api_key)
        return key

    @commands.command()
    @commands.is_owner()
    async def makekey(self, ctx, can_write: bool):
        api_key = await self.actuallymakekey(can_write)
        await ctx.author.send(f"API key created: {api_key}")

    @session_decorator
    async def actuallyconsent(self, session, ctx):
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
            return False
        user_main.api_consent = True
        return True

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
                if await self.actuallyconsent(ctx):
                    await ctx.send("You have now consented.")
        except TimeoutError:
            return

    @commands.hybrid_command()
    async def apiunconsent(self, ctx):
        await ctx.send("You have now unconsented.")
        await self.actuallyunconsent(ctx)

    @session_decorator
    async def actuallyunconsent(self, session, ctx):
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
            return False
        user_main.api_consent = False
        return True

    async def start_web_server(self):
        await self.runner.setup()
        site = web.TCPSite(self.runner, "0.0.0.0", 2586)
        await site.start()


async def setup(bot):
    await bot.add_cog(API(bot))
