import asyncio
import json
import time
import tomllib
from datetime import timedelta

import discord
from discord.ext import commands

import utils.miscfuncs as mf

with open("config.toml", "rb") as f:
    config = tomllib.load(f)


def array_to_string(arr):
    x = ", ".join(str(x) for x in arr)
    return x


async def get_json():
    with open("automod.json") as f:
        return json.load(f)


async def save_json(data):
    with open("automod.json", "w") as f:
        json.dump(data, f, indent=4)


async def send_webhook(ctx, name, avatar, message):
    try:
        webhooks = await ctx.webhooks()
        if webhooks:
            webhook = webhooks[0]
        else:
            webhook = await ctx.create_webhook(name="Nocaro_NPC", reason="TEEHEE")
        msg = await webhook.send(content=message, avatar_url=avatar, username=name)
    except:  # noqa: E722
        msg = await ctx.send(f"{name}: {message}")
    return msg


class Moderation(commands.Cog):
    """Basic Moderation commands."""

    def __init__(self, client):
        self.client = client

    # events
    @commands.Cog.listener()
    async def on_ready(self):
        print("Moderation loaded.")
        for guild in self.client.guilds:
            if guild.id in config["blacklists"]["blacklisted_dms"]:
                await guild.leave()
                me = await self.client.fetch_user(config["general"]["owner_id"])
                await me.send(f"Left blacklisted server: {guild.name}: `{guild.id}`")

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        if guild.id in config["blacklists"]["blacklisted_dms"]:
            await guild.leave()
            me = await self.client.fetch_user(config["general"]["owner_id"])
            await me.send(f"Left blacklisted server: {guild.name}: `{guild.id}`")

    @commands.hybrid_command()
    @commands.has_permissions(moderate_members=True)
    async def timeout(self, ctx, member: discord.Member, length: int = 5):
        """Timeout someone."""
        max_time = 2419200
        if length > max_time:
            length = max_time
        current_time = discord.utils.utcnow()
        future_time = current_time + timedelta(seconds=length)
        await member.timeout(future_time, reason="Timeout")
        await ctx.send(
            f"{member.mention} has been timed out for `{length}` seconds, this timeout will expire on `{future_time.strftime('%Y-%m-%d %H:%M:%S')}` UTC <t:{int(time.time()) + length}:R>."
        )

    # commands
    @commands.hybrid_command()
    @commands.has_permissions(manage_messages=True)
    async def clear(self, ctx, amount=5 + 1):
        """Clean messages."""
        await ctx.channel.purge(limit=amount)

    @commands.hybrid_command()
    @commands.has_permissions(ban_members=True, manage_messages=True)
    async def messageban(self, ctx, member: discord.Member):
        """Find and delete all messages in a server from one individual"""
        await ctx.send(
            "Ok working on it, this will take a long time. Type yes to confirm"
        )
        msg = await self.client.wait_for(
            "message", check=lambda m: m.author == ctx.author
        )
        if msg.content != "yes":
            return
        for channel in ctx.guild.text_channels:
            await channel.send(f"Now checking {channel.mention}...")
            await channel.purge(
                limit=None,
                check=lambda m: m.author == member,
                bulk=True,
                reason="Bulk deleted",
            )
        for vc in ctx.guild.voice_channels:
            await vc.send(f"Now checking {vc.mention}...")
            await vc.purge(
                limit=None,
                check=lambda m: m.author == member,
                bulk=True,
                reason="Bulk deleted",
            )
        await ctx.send("Done!")

    @commands.hybrid_command()
    async def blacklistme(self, ctx, length: int = 0):
        if length < 0:
            await ctx.send(
                "You can't blacklist yourself for a negative amount of time."
            )
            return
        if length == 0:
            await ctx.send(
                "Please specify a time in seconds that you'd like to blacklist yourself for."
            )
            return
        if length < 86_400:  # 1 day
            await ctx.send("You can't blacklist yourself for less than 1 day.")
            return
        await ctx.reply(
            "WARNING!!! READ THIS EXTREMELY CAREFULLY.\n\nBy running this command, you are blacklisting yourself from the bot. This means you will not be able to use any of the bot's commands. Additionally, users will not be able to interact with you via the economy commands. You will not be able to remove this blacklist yourself. Additionally, the bot owner will not remove this blacklist unless you can prove that this was not placed by you. Please type `I absolutely positively confirm that I want to blacklist myself from the bot.` to confirm."
        )

        def check(m):
            return (
                m.author == ctx.author
                and m.channel == ctx.channel
                and m.content
                == "I absolutely positively confirm that I want to blacklist myself from the bot."
            )

        try:
            await self.client.wait_for("message", check=check, timeout=30)
        except asyncio.TimeoutError:
            await ctx.send("You took too long to confirm.")
            return
        await mf.blacklist_user(ctx.author.id, int(time.time()) + length)
        await ctx.send("User successfully blacklisted.")

    @commands.command()
    @commands.is_owner()
    async def blacklist(self, ctx, member: discord.Member, length: int = 0):
        if length < 0:
            await ctx.send("You can't blacklist someone for a negative amount of time.")
            return
        if length == 0:
            await ctx.send(
                "Please specify a time in seconds that you'd like to blacklist this user for."
            )
            return
        await mf.blacklist_user(member.id, int(time.time()) + length)
        await ctx.send("User successfully blacklisted.")

    @commands.hybrid_command()
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason=None):
        """Ban someone."""
        await member.ban(reason=reason)
        await ctx.send("User has been banned")

    @commands.hybrid_command()
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason=None):
        """Kick someone."""
        await member.kick(reason=reason)
        await ctx.send("User has been kicked")


#     @commands.group(invoke_without_command=True)
#     @commands.has_permissions(manage_messages=True)
#     async def automod(self, ctx):
#         """Basic Automod"""
#         await ctx.send(
#             "This is a barebones automod command which utilizes regex. Available sub commands: `create`, `remove`, `list`, `edit`, `report`"
#         )

#     @automod.command(name="create")
#     async def automod_create(self, ctx, name: str = None, regex: str = None, punishment: str = None, replacements: str = ""):  # type: ignore
#         if name == None and regex == None and punishment == None:
#             await ctx.send(
#                 """Create an automod rule. Supply the name, regex, punishment, and replacements if required by punishment.
# Example: `,automod create "Swearing" "shit|fuck" "censor" "!@#$"`
# This will create a rule which will censor any messages containing "shit" or "fuck". And replace them with !@#$.
# `shit|fuck` is a very basic example of regex, but any can go here.
# Available punishments: `delete, slander, censor, replace`. Delete does not require replacements as an argument.
# To add multiple regex, simply separate them with `|||`. Example: `awesome_regex1|||awesome_regex2`
# If your punishment is slander or replace, you can also add multiple arguments with `|||`.
# **Any arguments with spaces MUST BE SURROUNDED IN QUOTES.**"""
#             )
#             return
#         if name == None or regex == None or punishment == None:
#             await ctx.send("Arguments not provided or not provided in correct order!")
#             return
#         if punishment not in ["delete", "slander", "censor", "replace"]:
#             await ctx.send("Not a valid punishment!")
#             return
#         if punishment in ["slander", "censor", "replace"]:
#             if replacements == "":
#                 await ctx.send(
#                     f"`Replacements`, which is required argument for `{punishment}`, has not been provided.\nFor censor mode, it is expecting several characters like %&#@ to replace a word with. \nFor slander mode, it is expecting whole strings to replace the entire message with.\n For replace mode, its expecting one word to replace with another word."
#                 )
#         data = await get_json()
#         try:  # i cannot dump data into a non-existing key so i have to do this sinfulness, probably a better method, i do not care!
#             data["servers"][f"{ctx.guild.id}"]
#         except:
#             data["servers"][f"{ctx.guild.id}"] = {}
#         try:
#             data["servers"][f"{ctx.guild.id}"]["rules"]
#         except:
#             data["servers"][f"{ctx.guild.id}"]["rules"] = {}
#         data["servers"][f"{ctx.guild.id}"]["rules"][name] = (
#             {  # if i ever look at this code again i will vomit
#                 "regex": regex.split("|||"),
#                 "punishment": f"{punishment}",
#                 "replacement": [],
#             }
#         )
#         if punishment != "delete":
#             if punishment in ["replace", "slander"]:
#                 replacements = replacements.split("|||")
#             else:
#                 replacements = [
#                     replacements[i : i + 1] for i in range(0, len(replacements), 1)
#                 ]  # split string into array for censoring
#             data["servers"][f"{ctx.guild.id}"]["rules"][name][
#                 "replacement"
#             ] = replacements
#         # data["servers"][f"{ctx.guild.id}"]["rules"][name][regex][punishment][replacements]
#         await asyncio.sleep(1)
#         await save_json(data)
#         await ctx.send(
#             f"Successfully created `{name}` with regex `{regex}` with `{punishment}` as punishment."
#         )

#     @automod.command(name="remove")
#     async def automod_remove(self, ctx, name: str = None):
#         if name == None:
#             await ctx.send("Please provide a rule to delete.")
#         data = await get_json()
#         try:
#             data["servers"][f"{ctx.guild.id}"]["rules"][name]
#         except:
#             await ctx.send("That rule does not exist!")
#             return
#         del data["servers"][f"{ctx.guild.id}"]["rules"][name]
#         await save_json(data)
#         await ctx.send(f"Rule {name} successfully removed")

#     @automod.command(name="list")
#     async def automod_list(self, ctx, name: str = None):
#         data = await get_json()
#         try:
#             rules = data["servers"][f"{ctx.guild.id}"][
#                 "rules"
#             ]  # this fucking sucks | TODO: anything but this
#         except:
#             await ctx.send("You do not have any rules setup!")
#             return
#         if name == None:
#             await ctx.send(
#                 f"Your current rules are {array_to_string(rules)}. For more information on a rule re-run this command with that rule's name."
#             )
#             return
#         try:
#             data["servers"][f"{ctx.guild.id}"]["rules"][name]
#         except:
#             await ctx.send("Not a valid rule!")
#             return
#         regex = data["servers"][f"{ctx.guild.id}"]["rules"][name]["regex"]
#         punishment = data["servers"][f"{ctx.guild.id}"]["rules"][name]["punishment"]
#         replacement = data["servers"][f"{ctx.guild.id}"]["rules"][name]["replacement"]
#         await ctx.send(
#             f"{name} info:\nRegex: {regex}\nPunishment: {punishment}\nReplacement: {replacement}"
#         )

#     @automod.command(name="edit")
#     async def automod_edit(self, ctx):
#         await ctx.send(
#             "For now, to edit a command, simply run the create command but with the same rule name."
#         )

#     @automod.command(name="report")
#     async def automod_report(self, ctx, arg: str = None):
#         if arg == None:
#             await ctx.send(
#                 "To turn on moderation logs, re-run this command with the channel id you want logs to appear. To turn it off and on again later, re-run this command with `on` or `off`"
#             )
#             return
#         data = await get_json()
#         try:
#             data["servers"][f"{ctx.guild.id}"]["reports"]
#         except:
#             data["servers"][f"{ctx.guild.id}"]["reports"] = {
#                 "send": True,
#                 "channel": "",
#             }
#         if arg not in ["on", "off"]:
#             log_chnl = await self.client.fetch_channel(arg)
#             if log_chnl == None:
#                 await ctx.send("This channel does not exist!")
#                 return
#             if log_chnl.guild != ctx.guild:
#                 await ctx.send("This channel is not in this server!")
#                 return
#             try:
#                 await log_chnl.send("I will now send automod logs in this channel.")
#             except:
#                 await ctx.send("I can't send messages there!")
#                 return
#             data["servers"][f"{ctx.guild.id}"]["reports"]["channel"] = arg
#             await ctx.send(f"Logging set to {log_chnl.mention}")
#         else:
#             if arg == "on":
#                 data["servers"][f"{ctx.guild.id}"]["reports"]["send"] = True
#                 await ctx.send("Logging turned on.")
#             else:
#                 data["servers"][f"{ctx.guild.id}"]["reports"]["send"] = False
#                 await ctx.send("Logging turned off.")
#         await save_json(data)

#     @commands.Cog.listener()
#     async def on_message(self, message):
#         if message.author.bot:
#             return

#         data = await get_json()
#         try:
#             server_data = data["servers"][f"{message.guild.id}"]
#         except KeyError:
#             return

#         replacements = message.content
#         broken_rules = []
#         punishments = []
#         for rule, rule_data in server_data["rules"].items():
#             for regex in rule_data["regex"]:
#                 pattern = re.compile(regex, re.IGNORECASE)
#                 if pattern.search(message.content):
#                     broken_rules.append(rule)
#                     punishments.append(rule_data["punishment"])

#         if broken_rules:
#             bot_guild = message.guild.get_member(self.client.user.id)
#             bot_permissions = [
#                 perm[0] for perm in bot_guild.guild_permissions if perm[1]
#             ]
#             if (
#                 "manage_messages" in bot_permissions
#                 or "administrator" in bot_permissions
#             ):
#                 await message.delete()
#                 await self.handle_punishments(
#                     message, broken_rules, punishments, replacements, server_data
#                 )

#     async def handle_punishments(
#         self, message, broken_rules, punishments, replacements, server_data
#     ):
#         log_msg = f"Message `{message.content}` from {message.author.mention} deleted due to `{array_to_string(broken_rules)}`"
#         if len(broken_rules) == 1:
#             punishment = punishments[0]
#             if punishment == "censor":
#                 await send_webhook(
#                     message.channel,
#                     message.author.display_name,
#                     str(message.author.avatar_url),
#                     self.censor_message(replacements, broken_rules[0], server_data),
#                 )
#                 log_msg = f"Message `{message.content}` from {message.author.mention} censored due to `{array_to_string(broken_rules)}`"
#             elif punishment == "slander":
#                 await send_webhook(
#                     message.channel,
#                     message.author.display_name,
#                     str(message.author.avatar_url),
#                     self.slander_message(broken_rules[0], server_data),
#                 )
#                 log_msg = f"Message `{message.content}` from {message.author.mention} slandered due to `{array_to_string(broken_rules)}`"
#             elif punishment == "replace":
#                 await send_webhook(
#                     message.channel,
#                     message.author.display_name,
#                     str(message.author.avatar_url),
#                     self.replace_message(replacements, broken_rules[0], server_data),
#                 )
#                 log_msg = f"Message `{message.content}` from {message.author.mention} replaced due to `{array_to_string(broken_rules)}`"

#         if len(broken_rules) > 1:
#             log_msg += "\nMultiple rules were broken, to avoid automod exploits, the message has just been deleted."

#         if server_data["reports"]["send"]:
#             log_channel = await self.client.fetch_channel(
#                 server_data["reports"]["channel"]
#             )
#             await log_channel.send(log_msg)

#     def censor_message(self, message, rule, server_data):
#         def get_censored_char(chars, length):
#             return "".join(random.choice(chars) for _ in range(length))

#         pattern = re.compile(rule, re.IGNORECASE)
#         while True:
#             match = pattern.search(message)
#             if match is None:
#                 break
#             replacement = get_censored_char(
#                 server_data["rules"][rule]["replacement"], len(match[0])
#             )
#             message = message[: match.start()] + replacement + message[match.end() :]
#         return message

#     def slander_message(self, rule, server_data):
#         replacement = random.choice(server_data["rules"][rule]["replacement"])
#         return replacement

#     def replace_message(self, message, rule, server_data):
#         def get_replacement_char(chars, length):
#             return random.choice(chars) * length

#         pattern = re.compile(rule, re.IGNORECASE)
#         while True:
#             match = pattern.search(message)
#             if match is None:
#                 break
#             replacement = get_replacement_char(
#                 server_data["rules"][rule]["replacement"], len(match[0])
#             )
#             message = message[: match.start()] + replacement + message[match.end() :]
#         return message


async def setup(client):
    await client.add_cog(Moderation(client))
