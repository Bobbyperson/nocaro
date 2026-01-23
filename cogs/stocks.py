import asyncio
import logging
import math

import discord
import pandas as pd
import pandas_market_calendars as mcal
import yfinance as yf
from discord.ext import commands
from sqlalchemy import select

import models
import utils.econfuncs as econ
import utils.miscfuncs as mf

log = logging.getLogger(__name__)


class Stocks(commands.Cog):
    """Buy real stocks with bouge bucks"""

    def __init__(self, client):
        self.client = client

    # events
    @commands.Cog.listener()
    async def on_ready(self):
        log.info("Stock market loaded")

    async def add_to_db(self, user_id, ticker, amount, purchase_price):
        async with self.client.session as session:
            async with session.begin():
                session.add(
                    models.stocks.Stocks(
                        user_id=user_id,
                        ticker=ticker,
                        amount=str(amount),
                        purchase_price=purchase_price,
                    )
                )

    async def remove_from_db(self, user_id: int, ticker: str, amount: int):
        if amount <= 0:
            return

        async with self.client.session as session:
            async with session.begin():
                results = await session.scalars(
                    select(models.stocks.Stocks).where(
                        models.stocks.Stocks.user_id == user_id
                    )
                )

                for row in results:
                    if amount <= 0:
                        break

                    if int(row.amount) <= amount:
                        await session.delete(row)
                        amount -= int(row.amount)
                    else:
                        row.amount = str(amount)
                        amount = 0

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
        try:
            stock = yf.Ticker(stock_ticker)
            # Try fetching the info to see if the ticker exists
            info = stock.info
            # A valid ticker will have a 'longName' field populated
            if "longName" in info:
                return True
            else:
                return False
        except:
            return False

    @commands.hybrid_command(aliases=["buystocks"])
    @commands.cooldown(5, 60, commands.BucketType.user)
    @mf.generic_checks()
    async def buystock(self, ctx, stock: str | None = None, amount: str | None = None):
        """Purchase stocks from the REAL LIFE stock market"""
        open_market = await self.is_market_open()
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
    @commands.cooldown(5, 60, commands.BucketType.user)
    @mf.generic_checks()
    async def sellstock(self, ctx, stock: str | None = None, amount: str | None = None):
        """Sell stocks from the REAL LIFE stock market"""
        open_market = await self.is_market_open()
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

            async with self.client.session as session:
                results = (
                    await session.scalars(
                        select(models.stocks.Stocks).where(
                            models.stocks.Stocks.user_id == ctx.author.id,
                            models.stocks.Stocks.ticker == stock,
                        )
                    )
                ).all()

                if not results:
                    await ctx.send("You don't have any stocks of that type")
                    return

                total_stocks = sum([int(stock.amount) for stock in results])
                if total_stocks < amount:
                    await ctx.send("You don't have enough stocks to sell")
                    return

            await self.remove_from_db(ctx.author.id, stock, amount)
            await econ.update_amount(
                ctx.author, math.floor(stock_price * amount), tracker_reason="sellstock"
            )
            await ctx.reply(
                f"You have successfully sold {amount} stocks of {stock} for {math.floor(stock_price * amount)} bouge bucks!"
            )

    @commands.hybrid_command()
    @commands.cooldown(5, 60, commands.BucketType.user)
    @mf.generic_checks()
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
    @commands.cooldown(1, 60, commands.BucketType.user)
    @mf.generic_checks(max_check=False)
    async def portfolio(self, ctx, user: discord.Member = None):
        """List all currently owned stocks"""
        if user is None:
            user = ctx.author
        async with ctx.typing():
            stocktable = {}
            async with self.client.session as session:
                results = (
                    await session.scalars(
                        select(models.stocks.Stocks).where(
                            models.stocks.Stocks.user_id == user.id
                        )
                    )
                ).all()

                if not results:
                    await ctx.send("You don't have any stocks")
                    return

                for stock in results:
                    if stock.ticker not in stocktable:
                        stocktable[stock.ticker] = {
                            "amount": int(stock.amount),
                            "purchase_price": stock.purchase_price,
                        }

            stocks = ""
            total_change = 0
            for stock_name, stock in stocktable.items():
                stock_amount = stock["amount"]
                stock_purchase_price = stock["purchase_price"]
                new_stock_price = await self.fetch_stock_price(stock_name)

                total_change += (new_stock_price * stock_amount) - stock_purchase_price

                if new_stock_price > stock_purchase_price / stock_amount:
                    stocks += f"{stock_name}: {mf.commafy(stock_amount)} stocks | + {mf.commafy(round((new_stock_price * stock_amount) - stock_purchase_price))} $BB\n"
                else:
                    stocks += f"{stock_name}: {mf.commafy(stock_amount)} stocks | - {mf.commafy(-1 * round((new_stock_price * stock_amount) - stock_purchase_price))} $BB\n"
            stocks += f"Total change: {mf.commafy(round(total_change))} $BB"
            await ctx.send(f"{user.name}'s current stocks:\n{stocks}")


async def setup(client):
    await client.add_cog(Stocks(client))
