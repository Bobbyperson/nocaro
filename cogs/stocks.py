import asyncio
import math

import aiosqlite
import discord
import pandas as pd
import pandas_market_calendars as mcal
import yfinance as yf
from discord.ext import commands

import utils.econfuncs as econ
import utils.miscfuncs as mf

bank = "./data/database.sqlite"


class Stocks(commands.Cog):
    """Buy real stocks with bouge bucks"""

    def __init__(self, client):
        self.client = client

    # events
    @commands.Cog.listener()
    async def on_ready(self):
        print("Stock market loaded")
        async with aiosqlite.connect(bank) as db:
            async with db.cursor() as cursor:
                await cursor.execute(
                    "CREATE TABLE IF NOT EXISTS stocks("
                    "num INTEGER NOT NULL PRIMARY KEY,"
                    ""
                    "user_ID INTEGER NOT NULL,"
                    "ticker TEXT NOT NULL,"
                    "amount INTEGER NOT NULL,"
                    "purchase_price INTEGER NOT NULL"
                    ")"
                )
            await db.commit()

    async def add_to_db(self, user_id, ticker, amount, purchase_price):
        async with aiosqlite.connect(bank) as db:
            async with db.cursor() as cursor:
                await cursor.execute(
                    "INSERT INTO stocks(user_ID, ticker, amount, purchase_price) VALUES(?, ?, ?, ?)",
                    (user_id, ticker, amount, purchase_price),
                )
            await db.commit()

    async def remove_from_db(self, user_id: int, ticker: str, amount: int):
        async with aiosqlite.connect(bank) as db:
            async with db.cursor() as cursor:
                await cursor.execute(
                    "SELECT rowid, amount FROM stocks WHERE user_ID = ? AND ticker = ?",
                    (user_id, ticker),
                )
                results = await cursor.fetchall()

                for row in results:
                    rowid, current_amount = row
                    if amount <= 0:
                        break

                    if current_amount <= amount:
                        await cursor.execute(
                            "DELETE FROM stocks WHERE rowid = ?",
                            (rowid,),
                        )
                        amount -= current_amount
                    else:
                        new_amount = current_amount - amount
                        await cursor.execute(
                            "UPDATE stocks SET amount = ? WHERE rowid = ?",
                            (new_amount, rowid),
                        )
                        amount = 0

            await db.commit()

    async def fetch_stock_price(self, stock_ticker):
        loop = asyncio.get_event_loop()
        stock = yf.Ticker(stock_ticker)

        hist = await loop.run_in_executor(None, lambda: stock.history(period="5d"))
        return hist["Close"].iloc[-1]  # Fetches the last closing price

    async def is_market_open(self):
        loop = asyncio.get_event_loop()
        nyse = mcal.get_calendar("NYSE")
        now = pd.Timestamp.now(tz="America/New_York")

        def get_schedule():
            return nyse.schedule(start_date=now.date(), end_date=now.date())

        market_schedule = await loop.run_in_executor(None, get_schedule)
        if not market_schedule.empty:
            open_today = (
                market_schedule.loc[market_schedule.index[0], "market_open"]
                <= now
                <= market_schedule.loc[market_schedule.index[0], "market_close"]
            )
        else:
            open_today = False  # no market data, no playtime, sorry pupper!
        return open_today

    async def verify_stock_ticker(self, stock_ticker):
        stock = yf.Ticker(stock_ticker)
        # Try fetching the info to see if the ticker exists
        try:
            info = stock.info
            # A valid ticker will have a 'longName' field populated
            if "longName" in info:
                return True
            else:
                return False
        except ValueError:
            return False

    @commands.hybrid_command(aliases=["buystocks"])
    async def buystock(self, ctx, stock: str | None = None, amount: str | None = None):
        """Purchase stocks from the REAL LIFE stock market"""
        open_market = await self.is_market_open()
        if await econ.checkmax(ctx.author):
            return await ctx.send(
                "You attempt to buy stocks but you can't. Maybe you should attempt to `,enterthecave`."
            )
        if not stock:
            return await ctx.send("Please provide a stock ticker")
        if not open_market:
            return await ctx.send(
                "The stock market is currently closed, come back at <t:1715088600:t>!"
            )
        if not await self.verify_stock_ticker(stock):
            return await ctx.send("Invalid stock ticker")
        amount = econ.moneyfy(amount)
        if not amount:
            return await ctx.send("Please provide an amount to buy")
        if amount < 0:
            return await ctx.send("You can't buy negative stocks")
        async with ctx.typing():
            stock = stock.upper()
            balance = await econ.get_bal(ctx.author)
            stock_price = await self.fetch_stock_price(stock)
            if balance < stock_price * amount:
                return await ctx.send(
                    "You don't have enough money to buy that many stocks"
                )
            await econ.update_amount(
                ctx.author,
                math.ceil(-stock_price * amount),
                tracker_reason="stockinvest",
            )
            await self.add_to_db(
                ctx.author.id, stock, amount, math.ceil(stock_price * amount)
            )
            await ctx.reply(
                f"You have successfully bought {amount} stocks of {stock} for {math.ceil(stock_price * amount)} bouge bucks!"
            )

    @commands.hybrid_command(aliases=["sellstocks"])
    async def sellstock(self, ctx, stock: str | None = None, amount: str | None = None):
        """Sell stocks from the REAL LIFE stock market"""
        open_market = await self.is_market_open()
        if await econ.checkmax(ctx.author):
            return await ctx.send(
                "You attempt to sell stocks but you can't. Maybe you should attempt to `,enterthecave`."
            )
        if not stock:
            return await ctx.send("Please provide a stock ticker")
        if not open_market:
            return await ctx.send(
                "The stock market is currently closed, come back at <t:1715088600:t>!"
            )
        if not await self.verify_stock_ticker(stock):
            return await ctx.send("Invalid stock ticker")
        amount = econ.moneyfy(amount)
        if not amount:
            return await ctx.send("Please provide an amount to sell")
        if amount < 0:
            return await ctx.send("You can't sell negative stocks")
        async with ctx.typing():
            stock = stock.upper()
            stock_price = await self.fetch_stock_price(stock)
            async with aiosqlite.connect(bank) as db:
                async with db.cursor() as cursor:
                    await cursor.execute(
                        "SELECT * FROM stocks WHERE user_ID = ? AND ticker = ?",
                        (ctx.author.id, stock),
                    )
                    result = await cursor.fetchall()
                    if not result:
                        return await ctx.send("You don't have any stocks of that type")
                    total_stocks = 0
                    for thing in result:
                        total_stocks += thing[3]
                    if total_stocks < amount:
                        return await ctx.send("You don't have enough stocks to sell")
            await self.remove_from_db(ctx.author.id, stock, amount)
            await econ.update_amount(
                ctx.author, math.floor(stock_price * amount), tracker_reason="sellstock"
            )
            await ctx.reply(
                f"You have successfully sold {amount} stocks of {stock} for {math.floor(stock_price * amount)} bouge bucks!"
            )

    @commands.hybrid_command()
    async def stockprice(self, ctx, stock: str | None = None):
        """Find the price of a REAL LIFE stock"""
        if not stock:
            return await ctx.send("Please provide a stock ticker")
        if not await self.verify_stock_ticker(stock):
            return await ctx.send("Invalid stock ticker")
        async with ctx.typing():
            open_market = await self.is_market_open()
            stock = stock.upper()
            if not open_market:
                return await ctx.send(
                    f"The stock market is currently closed, the closing price of {stock} is {await self.fetch_stock_price(stock)}"
                )
            else:
                await ctx.send(
                    f"The current price of {stock} is {await self.fetch_stock_price(stock)}"
                )

    @commands.hybrid_command()
    async def portfolio(self, ctx, user: discord.Member = None):
        """List all currently owned stocks"""
        async with ctx.typing():
            async with aiosqlite.connect(bank) as db:
                async with db.cursor() as cursor:
                    if not user:
                        user = ctx.author
                    await cursor.execute(
                        "SELECT * FROM stocks WHERE user_ID = ?", (user.id,)
                    )
                    result = await cursor.fetchall()
                    if not result:
                        return await ctx.send("You don't have any stocks")
                    stocktable = {}
                    for stock in result:
                        if stock[2] not in stocktable:
                            stocktable[stock[2]] = {
                                "amount": stock[3],
                                "purchase_price": stock[4],
                            }
                        else:
                            stocktable[stock[2]]["amount"] += stock[3]
                            stocktable[stock[2]]["purchase_price"] += stock[4]
                    stocks = ""
                    for stock in stocktable.items():
                        stock_name = stock[0]  # stock name
                        stock_amount = stock[1]["amount"]  # amount of all stocks
                        stock_purchase_price = stock[1][
                            "purchase_price"
                        ]  # sum of all purchase prices, not the average price
                        new_stock_price = await self.fetch_stock_price(
                            stock[0]
                        )  # current price of a single stock
                        if new_stock_price > stock_purchase_price / stock_amount:
                            stocks += f"{stock_name}: {stock_amount} stocks | + {mf.commafy(round((new_stock_price * stock_amount) - stock_purchase_price))} $BB\n"
                        else:
                            stocks += f"{stock_name}: {stock_amount} stocks | - {mf.commafy(-1 * round((new_stock_price * stock_amount) - stock_purchase_price))} $BB\n"
                    await ctx.send(f"{user.name}'s current stocks:\n{stocks}")


async def setup(client):
    await client.add_cog(Stocks(client))
