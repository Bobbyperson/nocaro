import asyncio
import contextlib
import functools
import logging
from decimal import Decimal

import discord
from discord.ext import commands, tasks
from sqlalchemy import delete, select

import models
import utils.econfuncs as econ

MAX_OPTIONS = 25

log = logging.getLogger(__name__)
# log.setLevel(logging.DEBUG)


class BetInvalid(Exception):
    pass


class BetNotEnoughBal(Exception):
    pass


class BetNotRunning(Exception):
    pass


class BetMaxxer(Exception):
    pass


class BetModal(discord.ui.Modal, title="BetModal"):
    def __init__(self, cog, bet_options, index=-1):
        super().__init__()
        self.cog = cog
        self.index = index
        self.option = self.cog.bet_options[index]
        self.title = f"Betting on {self.option}"

    amount = discord.ui.TextInput(
        label="Amount",
        placeholder="Type amount to bet here",
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = econ.moneyfy(self.amount.value)
        except ValueError:
            await interaction.response.send_message(
                f"{self.amount.value} is not a valid number", ephemeral=True
            )
            return

        if value <= 0:
            await interaction.response.send_message(
                "You cannot bet that amount", ephemeral=True
            )
            return

        try:
            await self.cog.add_bet(interaction.user, self.index, value)
        except BetNotEnoughBal:
            await interaction.response.send_message(
                "You do not have enough balance to make that bet", ephemeral=True
            )
            return
        except BetNotRunning:
            await interaction.response.send_message(
                "No bet is currently running", ephemeral=True
            )
            return
        except BetMaxxer:
            await interaction.response.send_message(
                "The Central Betting Authority has refused to accept your money due to evidence of laundering",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"You have bet {econ.unmoneyfy(value)} on {self.option}", ephemeral=True
        )


class PayoutSelection(discord.ui.Select):
    def __init__(self, cog):
        self.cog = cog
        options = [discord.SelectOption(label=option) for option in cog.bet_options]
        super().__init__(
            placeholder="Choose the winner", min_values=1, max_values=1, options=options
        )

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        try:
            index = self.cog.bet_options.index(value)
        except ValueError:
            await interaction.response.send_message(
                f"{value} is not a valid bet", ephemeral=True
            )
            return

        await self.cog.do_payout(index)
        await self.cog.cleanup_state()
        await interaction.response.send_message(f"The winner is {value}")


class Betting(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bet_active: bool = False
        self.message_id: int | None = None
        self.channel_id: int | None = None
        self.bet_view = None
        self.bet_options = []
        self.bet_values = []

        self.bet_lock = asyncio.Lock()

        self.update_bet.add_exception_type(asyncio.TimeoutError)
        self.update_bet.add_exception_type(discord.errors.DiscordServerError)

    async def cog_load(self):
        if not self.bot.is_ready():
            return

        log.debug("Cog loading")

        await self.restore_state()

        if not self.update_bet.is_running():
            self.update_bet.start()

    async def cog_unload(self):
        log.debug("Cog unloading, disabling task")
        self.update_bet.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        log.info("Betting loaded.")

        # The cog cannot load before the bot is ready
        await self.cog_load()

    def state_decorator(func):
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            async with self.bet_lock:
                return await func(self, *args, **kwargs)

        return wrapper

    async def restore_state(self):
        assert self.bet_active == False

        state = await self.__load_state()
        if state is None:
            await self.cleanup_state()
            return

        options = await self.__load_options()
        entries = await self.__load_entries()

        log.info("Found bet options, restoring...")

        self.bet_options.clear()
        self.bet_values.clear()

        bet_view = discord.ui.View()

        p = -1
        for o in options:
            assert o.index > p
            p = o.index
            self.bet_options.append(o.name)
            self.bet_values.append(Decimal(0))

            item = discord.ui.Button(style=discord.ButtonStyle.primary, label=o.name)
            item.callback = self.button_callback(o.index)
            bet_view.add_item(item)

        for e in entries:
            self.bet_values[e.option_id] += Decimal(e.balance)

        self.bet_view = bet_view
        self.message_id = state.message_id
        self.channel_id = state.channel_id
        self.bet_active = True

        log.info("Done restoring")

    async def cleanup_state(self):
        self.bet_active = False
        self.bet_options.clear()
        self.bet_values.clear()

        async with self.bot.session as session:
            async with session.begin():
                await session.execute(delete(models.betting.BetOptions))
                await session.execute(delete(models.betting.BetEntries))
                await session.execute(delete(models.betting.BetState))

    async def __load_options(self) -> list[models.betting.BetOptions]:
        async with self.bot.session as session:
            options = (await session.scalars(select(models.betting.BetOptions))).all()

            # Make sure the list is in a determinstic order
            options.sort(key=lambda x: x.index)

            assert len(options) <= MAX_OPTIONS, "Too many options in database"

            return options

    async def __load_entries(self) -> list[models.betting.BetEntries]:
        async with self.bot.session as session:
            entries = (await session.scalars(select(models.betting.BetEntries))).all()
            return entries

    async def __load_state(self) -> list[models.betting.BetState]:
        async with self.bot.session as session:
            state = (
                await session.scalars(select(models.betting.BetState))
            ).one_or_none()
            return state

    @state_decorator
    async def _cancel_bet(self):
        async with self.bot.session as session:
            bets = (await session.scalars(select(models.betting.BetEntries))).all()
            for bet in bets:
                user = await self.bot.fetch_user(bet.user_id)
                await econ.update_amount(user, bet.balance, False, "bet canceled")

        await self.cleanup_state()

    def button_callback(self, index):
        async def inner(interaction):
            if self.bet_active:
                await interaction.response.send_modal(
                    BetModal(self, self.bet_options, index)
                )
            else:
                await interaction.response.send_message(
                    "No bet is currently running", ephemeral=True
                )

        return inner

    @state_decorator
    async def add_bet(
        self, user: discord.User | discord.Member, index: int, amount: int
    ):
        if not self.bet_active:
            raise BetNotRunning()

        if await econ.checkmax(user):
            raise BetMaxxer()

        if index < 0 or index > len(self.bet_options) or amount <= 0:
            return BetInvalid()

        user_bal = await econ.get_bal(user)
        if user_bal < amount:
            raise BetNotEnoughBal()

        option = self.bet_options[index]

        async with self.bot.session as session:
            async with session.begin():
                existing_bet = await session.scalar(
                    select(models.betting.BetEntries).where(
                        models.betting.BetEntries.option_id == index,
                        models.betting.BetEntries.user_id == user.id,
                    )
                )

                if existing_bet:
                    new_balance = Decimal(existing_bet.balance) + Decimal(amount)
                    existing_bet.balance = new_balance
                else:
                    session.add(
                        models.betting.BetEntries(
                            option_id=index, user_id=user.id, balance=Decimal(amount)
                        )
                    )

        self.bet_values[index] += amount

        await econ.update_amount(user, -amount, False, f"bet {amount} on {option}")

    @commands.command()
    @commands.is_owner()
    async def createbet(self, ctx, title: str, *, options: str):
        if self.bet_active:
            await ctx.send("a bet is still running")
            return

        bet_options = [x.strip() for x in options.split(",") if x.strip()]
        if len(bet_options) > MAX_OPTIONS:
            await ctx.send(f"only up to {MAX_OPTIONS} bet options can be set")
            return
        elif len(bet_options) < 2:
            await ctx.send("need at least 2 options to bet on")
            return

        embed = discord.Embed(title=title)
        bet_view = discord.ui.View()
        async with self.bot.session as session:
            async with session.begin():
                for i, option in enumerate(bet_options):
                    session.add(models.betting.BetOptions(index=i, name=option))

                    item = discord.ui.Button(
                        style=discord.ButtonStyle.primary, label=option
                    )
                    item.callback = self.button_callback(i)
                    bet_view.add_item(item)

                    embed.add_field(name=option, value="`0`", inline=True)

        self.bet_options = bet_options
        self.bet_values = [0] * len(bet_options)
        self.bet_view = bet_view

        message = await ctx.send(embed=embed, view=self.bet_view)
        async with self.bot.session as session:
            async with session.begin():
                session.add(
                    models.betting.BetState(
                        message_id=message.id, channel_id=message.channel.id
                    )
                )

        self.message_id = message.id
        self.channel_id = message.channel.id
        self.bet_active = True

    @tasks.loop(seconds=10.0)
    @state_decorator
    async def update_bet(self):
        if self.bet_active:
            log.debug("update_bet")

            channel = self.bot.get_channel(self.channel_id)
            bet_message = await channel.fetch_message(self.message_id)

            embed = discord.Embed(title="Betting")
            for i, option in enumerate(self.bet_options):
                try:
                    val = round(self.bet_values[i])
                except IndexError:
                    val = 0
                embed.add_field(
                    name=option, value=f"`{econ.unmoneyfy(val)}`", inline=True
                )
            await bet_message.edit(embed=embed, view=self.bet_view)

    @commands.command()
    @commands.is_owner()
    async def payoutbet(self, ctx):
        if self.bet_active is False:
            await ctx.send("No bet is currently running")
            return

        with contextlib.suppress(discord.Forbidden):
            await ctx.message.add_reaction("⏳")

        self.bet_active = False

        async def payout_callback(interaction):
            if not await self.bot.is_owner(interaction.user):
                await interaction.response.send_message(
                    "This is not for you", ephemeral=True
                )
                return

            view = discord.ui.View()
            view.add_item(PayoutSelection(self))
            await interaction.response.send_message(view=view, ephemeral=True)

        view = discord.ui.View()
        item = discord.ui.Button(
            style=discord.ButtonStyle.primary, label="Select winning option"
        )
        item.callback = payout_callback
        view.add_item(item)

        await ctx.send(view=view)

        with contextlib.suppress(discord.Forbidden):
            await ctx.message.delete()

    @state_decorator
    async def do_payout(self, winner):
        if self.bet_active:
            return

        winning_option = self.bet_options[winner]
        winners = {}
        full_pot = 0
        winner_bal = 0

        async with self.bot.session as session:
            bets = (await session.scalars(select(models.betting.BetEntries))).all()

            for bet in bets:
                full_pot += Decimal(bet.balance)

                if bet.option_id == winner:
                    winners[bet.user_id] = Decimal(bet.balance)
                    winner_bal += Decimal(bet.balance)

        for user_id, user_bet in winners.items():
            user_bet = winners[user_id]
            winnings = user_bet * (full_pot / winner_bal)

            user = await self.bot.fetch_user(user_id)
            await econ.update_amount(user, winnings, False, "won bet")
            await user.send(
                f"You bet on {winning_option} and won {econ.unmoneyfy(winnings)}"
            )

    @commands.command()
    @commands.is_owner()
    async def cancelbet(self, ctx):
        if self.bet_active is False:
            await ctx.send("No bet is running")
            return

        with contextlib.suppress(discord.Forbidden):
            await ctx.message.add_reaction("⏳")

        await self._cancel_bet()

        with contextlib.suppress(discord.Forbidden):
            await ctx.message.remove_reaction("⏳", self.bot.user)
            await ctx.message.add_reaction("✅")


async def setup(client):
    await client.add_cog(Betting(client))
