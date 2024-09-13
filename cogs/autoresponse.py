import aiosqlite
import discord
from discord.ext import commands

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
        if message.author == self.client.user:
            return
        elif message.author.bot:
            return
        elif await self.check_ignored(message.channel):
            return
        elif self.client.user.mentioned_in(message):
            await message.channel.send(message.author.mention)
        match str.lower(message.content):
            case "the dark knight":
                await message.channel.send(
                    'Did you know in the batman movie "The Dark Knight Rises" there is a split second scene where you can see a cameraman?',
                    file=discord.File("camera.jpg", "camera.jpg"),
                )
            case "etterna":
                await message.channel.send("OSU!!!")
            case "touhou":
                await message.channel.send("toe hoe")
            case "owo":
                await message.channel.send("uwu")
            case "uwu":
                await message.channel.send("owo")
            case "pandavert":
                await message.channel.send(":panda_face:")
            case "sponsor":
                await message.channel.send(
                    "today's annoying auto response message is sponsored by RAID: Shadow Legends."
                )
            case "min min":
                await message.channel.send("i fucking hate min min")
            case "hate these autoresponses":
                await message.channel.send("oh yeah? i don't like you either buster")
            case "quack":
                await message.channel.send("quack")
            case "ryan gosling":
                await message.channel.send("he's literally me")
            case "jackbox":
                jackbox = "<:GO:893517923472277536>"
                await message.add_reaction(jackbox)
            case "pick it up":
                await message.channel.send("SKAAAAAAAAAA!")


async def setup(client):
    await client.add_cog(Autoresponse(client))
