import asyncio
import time

import discord
from discord import ButtonStyle, Interaction
from discord.ext import commands
from discord.ui import Button, View


class MyButtonView(View):
    def __init__(self):
        super().__init__()
        self.value = None

    @discord.ui.button(label="Click Me!", style=ButtonStyle.primary)
    async def my_button(self, button: Button, interaction: Interaction):
        self.value = interaction
        self.stop()


class Example(commands.Cog):
    def __init__(self, client):
        self.client = client

    # events
    @commands.Cog.listener()
    async def on_ready(self):
        print("Example ready")

    @commands.command(aliases=["pong"], hidden=True)
    async def ping(self, ctx):
        """
        pong!
        :param ctx:
        :return: a message containing the API and websocket latency in ms.
        """
        start = time.perf_counter()
        message = await ctx.send("Ping...")
        end = time.perf_counter()
        duration = (end - start) * 1000
        await message.edit(
            content=f"🏓 Pong!\n"
            f"API Latency: `{round(duration)}ms`\n"
            f"Websocket Latency: `{round(self.client.latency * 1000)}ms`"
        )

    @commands.command(hidden=True)
    async def invite(self, ctx):
        await ctx.send(
            "https://discord.com/api/oauth2/authorize?client_id=746934062446542925&permissions=277632642112&scope=bot%20applications.commands"
        )

    @commands.command(hidden=True)
    async def play(self, ctx):
        await ctx.send("please use the < prefix for music")

    @commands.command(hidden=True)
    async def btest(self, ctx):
        # Send a message with a button
        view = MyButtonView()
        await ctx.send("Click the button or send me a message!", view=view)

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        # Wrap coroutines in tasks explicitly
        message_task = asyncio.create_task(self.client.wait_for("message", check=check))
        button_task = asyncio.create_task(view.wait())

        done, pending = await asyncio.wait(
            [message_task, button_task], return_when=asyncio.FIRST_COMPLETED
        )
        # Check what was completed
        if view.value:
            # Button was clicked
            await ctx.send("You clicked the button, good job!")
            await view.response.defer()
        else:
            # Message was sent
            message = done.pop().result()
            await ctx.send(f"You sent a message: {message.content}")

        # Cancel any pending tasks if they're still running
        for task in pending:
            task.cancel()

        # Maybe give a treat or a pat for getting this far, you smart doggo

    @commands.command(hidden=True)
    async def bot(self, ctx):
        await ctx.send(",human")


async def setup(client):
    await client.add_cog(Example(client))
