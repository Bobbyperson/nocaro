import discord
import random
import os
import asyncio
from discord.ext import commands
from discord.ext import tasks
from pretty_help import PrettyHelp
import config


async def main():
    # start the client
    async with client:
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py"):
                await client.load_extension(f"cogs.{filename[:-3]}")
        await client.start(config.token)


intents = discord.Intents().all()
client = commands.Bot(command_prefix=",", intents=intents, help_command=PrettyHelp())


@tasks.loop(seconds=30)
async def change_status(statuses):
    await client.change_presence(activity=discord.Game(random.choice(statuses)))


@client.command(hidden=True)
async def load(ctx, extension):
    if ctx.author.id == config.owner_id:
        await client.load_extension(f"cogs.{extension}")
        await ctx.send(f"{extension} loaded.")
    if ctx.author.id != config.owner_id:
        await ctx.send("no")


@client.command(hidden=True)
async def unload(ctx, extension):
    if ctx.author.id == config.owner_id:
        await client.unload_extension(f"cogs.{extension}")
        await ctx.send(f"{extension} unloaded.")

    if ctx.author.id != config.owner_id:
        await ctx.send("no")


@client.command(hidden=True)
async def reload(ctx, extension):
    if ctx.author.id == config.owner_id:
        await client.unload_extension(f"cogs.{extension}")
        await ctx.send(f"{extension} unloaded.")
        await client.load_extension(f"cogs.{extension}")
        await ctx.send(f"{extension} loaded.")
    else:
        await ctx.send("no")


async def guilds():
    return client.guilds


async def users():
    return client.users


@client.event
async def on_ready():
    print("I am ready.")
    statuses = [
        ",help | ,invite",
        f"Currently in {str(len(await guilds()))} guilds",
        f"I can see {str(len(await users()))} users",
    ]
    change_status.start(statuses)
    try:
        synced = await client.tree.sync()
        print(f"Sycned {len(synced)} commands!")
    except Exception as e:
        print(e)


discord.utils.setup_logging()
asyncio.run(main())
