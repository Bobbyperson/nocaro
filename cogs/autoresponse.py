import discord
from discord.ext import commands
import random as rd
import aiosqlite

bank = "./data/database.sqlite"


class Autoresponse(commands.Cog):
    def __init__(self, client):
        self.client = client

    # events
    @commands.Cog.listener()
    async def on_ready(self):
        print("autoresponse ready")

    async def check_ignored(self, channel):
        async with aiosqlite.connect(bank) as db:
            cursor = await db.cursor()
            await cursor.execute(
                "SELECT * FROM ignore WHERE channelID = ?", (channel.id,)
            )
            result = await cursor.fetchone()
            if result is not None:
                return True
            else:
                return False

    @commands.Cog.listener()
    async def on_message(self, message):
        reactto = str.lower(message.content)
        andy = rd.randint(1, 57)
        if message.author == self.client.user:
            return
        elif message.author.bot:
            return
        elif await self.check_ignored(message.channel):
            return
        elif self.client.user.mentioned_in(message):
            await message.channel.send(message.author.mention)
        elif "the dark knight" in reactto:
            await message.channel.send(
                'Did you know in the batman movie "The Dark Knight Rises" there is a split second scene where you can see a cameraman?',
                file=discord.File("camera.jpg", "camera.jpg"),
            )
        elif "etterna" in reactto:
            await message.channel.send("OSU!!!")
        elif "touhou" in reactto:
            await message.channel.send("toe hoe")
        elif "owo" == reactto:
            await message.channel.send("uwu")
        elif "uwu" == reactto:
            await message.channel.send("owo")
        elif "pandavert" in reactto:
            await message.channel.send(":panda_face:")
        elif "sponsor" in reactto:
            await message.channel.send(
                "today's annoying auto response message is sponsored by RAID: Shadow Legends."
            )
        elif "min min" in reactto:
            await message.channel.send("i fucking hate min min")
        elif "hate these autoresponses" in reactto:
            await message.channel.send("oh yeah? i don't like you either buster")
        elif "quack" in reactto:
            await message.channel.send("quack")
        elif "ryan gosling" in reactto:
            await message.channel.send("he's literally me")
        elif "jackbox" in reactto:
            jackbox = "<:GO:893517923472277536>"
            await message.add_reaction(jackbox)
        elif andy <= 55:
            if "send andy pics" in reactto:
                await message.channel.send(
                    "Andy image get!",
                    file=discord.File("./andy/" + f"{andy}" + ".jpg", "Andy.jpg"),
                )
        elif andy >= 55:
            if "send andy pics" in reactto:
                await message.channel.send(
                    "Andy video get!",
                    file=discord.File("./andy/" + f"{andy}" + ".mp4", "Andy.mp4"),
                )
        elif "pick it up" in reactto:
            await message.channel.send("SKAAAAAAAAAA!")


async def setup(client):
    await client.add_cog(Autoresponse(client))
