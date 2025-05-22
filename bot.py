import asyncio
import os
import random
import tomllib

import discord
from discord.ext import commands, tasks
from pretty_help import PrettyHelp
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from models import Base

with open("config.toml", "rb") as f:
    config = tomllib.load(f)


async def main():
    if not os.path.exists("data/database.sqlite"):
        os.makedirs("data", exist_ok=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    # start the client
    async with client:
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py"):
                await client.load_extension(f"cogs.{filename[:-3]}")
        await client.start(config["general"]["token"])


engine = create_async_engine("sqlite+aiosqlite:///data/database.sqlite", echo=None)
Session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

intents = discord.Intents().all()
client = commands.Bot(
    command_prefix=config["general"]["prefix"],
    intents=intents,
    help_command=PrettyHelp(),
)


@tasks.loop(seconds=30)
async def change_status():
    statuses = [
        ",help | ,invite",
        f"Currently in {len(client.guilds)} guilds",
        f"I can see {len(client.users)} users",
    ]
    await client.change_presence(activity=discord.Game(random.choice(statuses)))


@client.command(hidden=True)
async def load(ctx, extension):
    if ctx.author.id == config["general"]["owner_id"]:
        await client.load_extension(f"cogs.{extension}")
        await ctx.send(f"{extension} loaded.")
    if ctx.author.id != config["general"]["owner_id"]:
        await ctx.send("no")


@client.command(hidden=True)
async def unload(ctx, extension):
    if ctx.author.id == config:
        await client.unload_extension(f"cogs.{extension}")
        await ctx.send(f"{extension} unloaded.")

    if ctx.author.id != config["general"]["owner_id"]:
        await ctx.send("no")


@client.command(hidden=True)
async def reload(ctx, extension):
    if ctx.author.id == config["general"]["owner_id"]:
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
    change_status.start()
    try:
        synced = await client.tree.sync()
        print(f"Sycned {len(synced)} commands!")
    except Exception as e:
        print(e)


if __name__ == "__main__":
    discord.utils.setup_logging()
    asyncio.run(main())
