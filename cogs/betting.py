import asyncio
from collections import Counter

import aiosqlite
import discord
from discord.ui import Select, View
from discord.ext import commands, tasks

import utils.econfuncs as econ

bank = "./data/database.sqlite"

class BetNotEnoughBal(Exception):
    pass

class BetNotRunning(Exception):
    pass

class BetMaxxer(Exception):
    pass

class BetModal(discord.ui.Modal, title='BetModal'):

    def __init__(self, cog, index=0):
        super().__init__()
        self.cog = cog
        self.index = index
        self.option = self.cog.bet_options[index]
        self.title = f"Betting on {self.option}"

    amount = discord.ui.TextInput(
        label='Amount',
        placeholder='1',
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = econ.moneyfy(self.amount.value)
        except ValueError:
            await interaction.response.send_message(f'{self.amount.value} is not a valid number', ephemeral=True)
            return

        if value <= 0:
            await interaction.response.send_message(f'You cannot bet that amount', ephemeral=True)
            return

        try:
            await self.cog.add_bet(interaction.user, self.index, value)
        except BetNotEnoughBal:
            await interaction.response.send_message(f'You do not have enough balance to make that bet', ephemeral=True)
            return
        except BetNotRunning:
            await interaction.response.send_message(f'No bet is currently running', ephemeral=True)
            return
        except BetMaxxer:
            await interaction.response.send_message(f'The Central Betting Authority has refused to accept your money due to evidence of laundering', ephemeral=True)
            return

        await interaction.response.send_message(f'You have bet {value} on {self.option}', ephemeral=True)


class Betting(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bet_message = None
        self.bet_view = None
        self.bet_options = []
        self.bet_values = []
        self.update_bet.add_exception_type(asyncio.TimeoutError)
        self.update_bet.add_exception_type(discord.errors.DiscordServerError)

    def button_callback(self, index):
        async def inner(interaction):
            if self.update_bet.is_running():
                await interaction.response.send_modal(BetModal(self, index))
            else:
                await interaction.response.send_message(f'No bet is currently running', ephemeral=True)
        return inner

    async def add_bet(self, user: discord.User | discord.Member, index: int, amount: int):
        if not self.update_bet.is_running():
            raise BetNotRunning()

        if await econ.checkmax(user):
            raise BetMaxxer()

        value = self.bet_values[index]
        if not user.id in value:
            value[user.id] = 0

        user_bal = await econ.get_bal(user)
        if user_bal < amount:
            raise BetNotEnoughBal()

        option = self.bet_options[index]

        await econ.update_amount(user, -amount, False, f"bet {amount} on {option}")
        value[user.id] += amount

    @commands.command()
    @commands.is_owner()
    async def createbet(self, ctx, *, options: str):
        await ctx.message.delete()
        if self.update_bet.is_running():
            await ctx.send('a bet is still running')
            return

        bet_options = [x.strip() for x in options.split(",")]
        if leb(bet_options) > 25:
            await ctx.send('only up to 25 bet options can be set')
            return

        self.bet_options = options.split(",")
        self.bet_values = []
        self.bet_view = discord.ui.View()

        embed = discord.Embed(title="Betting")
        for i, option in enumerate(self.bet_options):
            item = discord.ui.Button(
                style=discord.ButtonStyle.primary,
                label=option
            )
            item.callback = self.button_callback(i)
            self.bet_view.add_item(item)

            embed.add_field(
                name=option,
                value=f"`0`",
                inline=True
            )
            self.bet_values.append({})


        self.bet_message = await ctx.send(embed=embed, view=self.bet_view)

        self.update_bet.start()

    @tasks.loop(seconds=10.0)
    async def update_bet(self):
        print("update bet")
        if self.bet_message:
            self.votes = Counter()  # Reset the votes counter at the beginning
            cache_msg = await self.bet_message.channel.fetch_message(
                self.bet_message.id
            )

            embed = discord.Embed(title="Betting")
            for i, option in enumerate(self.bet_options):
                val = sum(self.bet_values[i].values())
                embed.add_field(
                    name=option,
                    value=f"`{val}`",
                    inline=True
                )
            await self.bet_message.edit(embed=embed, view=self.bet_view)

    @commands.command()
    @commands.is_owner()
    async def payoutbet(self, ctx, index: int):
        await ctx.message.delete()
        if self.update_bet.is_running():
            await ctx.send("Bet is still running")
            return

        winner = index
        option = self.bet_options[winner]

        total_pot = 0
        for a in self.bet_values:
            for b in a.values():
                total_pot += b

        winner_pot = 0
        # Calculate how big the winner pot was
        for bal in self.bet_values[winner].values():
            winner_pot += bal

        for user_id, bal in self.bet_values[winner].items():
            winnings = total_pot * (b / winner_pot)
            user = await self.bot.fetch_user(user_id)
            await econ.update_amount(user, winnings, False, f"won bet on {option}")

        await ctx.send(f"{option} has won, winners have received their share of the payout")        

    @commands.command()
    @commands.is_owner()
    async def cancelbet(self, ctx):
        if self.update_bet.is_running():
            await ctx.send("Bet is still running")
            return

        for index, value in enumerate(self.bet_values):
            option = self.bet_options[index]
            for user_id, amount in value.items():
                user = await self.bot.fetch_user(user_id)
                await econ.update_amount(user, amount, False, f"refunded bet on {option}")

            value.clear()

        await ctx.send("everyone has been refunded")

    @commands.command()
    @commands.is_owner()
    async def disablebet(self, ctx):
        """Disable the Bet"""
        self.update_bet.cancel()
        await ctx.send("Bet has been disabled.")

    @commands.command()
    @commands.is_owner()
    async def resumebet(self, ctx):
        """Resume a bet"""
        self.update_bet.start()
        await ctx.send("Bet has been resumed.")


async def setup(client):
    await client.add_cog(Betting(client))
