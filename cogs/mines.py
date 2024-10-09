import random as rd

import discord
from discord.ext import commands


class MineButton(discord.ui.Button):
    def __init__(self, label, is_mine, chance):
        super().__init__(label=label, emoji="❓", style=discord.ButtonStyle.primary)
        self.is_mine = is_mine

    async def callback(self, interaction: discord.Interaction):
        self.disabled = True
        if self.is_mine:
            self.emoji = "💣"
            self.style = discord.ButtonStyle.red
            self.view.money_earned = 0
            for child in self.view.children:
                child.disabled = True
            await interaction.response.edit_message(
                content="💥 Game Over!",
                view=self.view,
            )
            self.view.stop()
        else:
            self.emoji = "💰"
            self.style = discord.ButtonStyle.green
            fraction = 1 / self.chance
            self.view.successful_clicks += 1
            self.view.money_earned += self.view.bet * fraction
            self.view.money_earned = round(self.view.money_earned, 2)
            await interaction.response.edit_message(
                content=f"Money earned: {self.view.money_earned}", view=self.view
            )


class CashOutButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="💰 Cash Out", style=discord.ButtonStyle.green)

    async def callback(self, interaction: discord.Interaction):
        for child in self.view.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"You cashed out! Total money earned: {self.view.money_earned}",
            view=self.view,
        )
        self.view.stop()


class MinesView(discord.ui.View):
    def __init__(self, chance, bet):
        super().__init__()
        self.money_earned = 0
        self.message = None  # Will be set later
        self.bet = bet
        self.successful_clicks = 0

        # Add the grid of mine buttons
        for i in range(5):
            for j in range(5):
                label = str(i * 5 + j + 1)
                is_mine = rd.randint(1, chance) == 1
                button = MineButton(label=label, is_mine=is_mine)
                self.add_item(button)

        self.add_item(CashOutButton())

    async def on_timeout(self):
        for button in self.children:
            button.disabled = True
        await self.message.edit(view=self)


class Mines(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command()
    async def mines(self, ctx, amount: int = 0):
        if amount <= 0:
            await ctx.send(
                """Welcome to Mines!
A few of these blocks are bombs!
Click as many as you like, then cash out when you're done.
Please enter a valid bet amount to start playing."""
            )
            return

        await ctx.send("Let's play Mines!")
        chance = 8
        bet = amount
        view = MinesView(chance, bet)
        message = await ctx.send(
            content=f"Money earned: {view.money_earned}", view=view
        )
        view.message = message
        await view.wait()
        if view.money_earned > 0:
            await ctx.send(f"You earned a total of {view.money_earned}!")
        else:
            await ctx.send("You lost bozo.")


async def setup(bot):
    await bot.add_cog(Mines(bot))
