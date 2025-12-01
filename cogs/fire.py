import csv
import io
import logging
import time as t

import anyio
import asyncpg
import discord
from discord.ext import commands, tasks
from sqlalchemy import delete, select, update

import models
from utils.achievements import get_achievement
from utils.miscfuncs import generic_checks

fire = "🔥"

log = logging.getLogger(__name__)


def serialize_attachments(attachments: list[discord.Attachment]) -> str:
    # semicolon-separated URLs
    return ";".join(a.url for a in attachments) if attachments else ""


def serialize_reactions(reactions: list[discord.Reaction]) -> str:
    # "emoji:count|emoji:count"
    if not reactions:
        return ""
    parts = []
    for r in reactions:
        emoji = str(r.emoji)  # handles custom + unicode
        parts.append(f"{emoji}:{r.count}")
    return "|".join(parts)


async def _write_rows_async(csvf, rows: list[list[str]]):
    """Use csv.writer on a StringIO buffer, then write once to the async file."""
    if not rows:
        return
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerows(rows)
    await csvf.write(buf.getvalue())


async def _ensure_header(csvfile: str, fields: list[str]):
    path = anyio.Path(csvfile)
    if await path.exists():
        # only write header if empty
        stat = await path.stat()
        if stat.st_size > 0:
            return
    async with await anyio.open_file(
        csvfile, "a+", encoding="utf8", newline=""
    ) as csvf:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(fields)
        await csvf.write(buf.getvalue())


class Fire(commands.Cog):
    """Starboard if it were awesome..."""

    def __init__(self, client):
        self.client = client
        self.weekly.add_exception_type(asyncpg.PostgresConnectionError)
        self.weekly.start()

    def cog_unload(self):
        self.weekly.cancel()

    async def add_msg(self, reacts, msg, fb_msg_id, fbid, emoji):
        cid = msg.channel.id
        mid = msg.id
        gid = msg.guild.id
        uid = msg.author.id
        message = msg.content
        insane = msg.created_at
        unix = insane.timestamp()

        async with self.client.session as session:
            async with session.begin():
                session.add(
                    models.fire.Fire(
                        reacts=reacts,
                        channel_id=cid,
                        message_id=mid,
                        guild_id=gid,
                        user_id=uid,
                        fb_id=fbid,
                        message=message,
                        attachments=None,
                        timestamp=int(unix),
                        fb_msg_id=fb_msg_id,
                        emoji=emoji,
                    )
                )

    async def edit_msg(self, reacts, msg):
        mid = msg.id
        message = msg.content
        message = message.replace(r"'", r"''")
        async with self.client.session as session:
            async with session.begin():
                await session.execute(
                    update(models.fire.Fire)
                    .where(models.fire.Fire.message_id == mid)
                    .values(message=message, reacts=reacts)
                )

    async def get_element(self, element, value_name, value):
        try:
            value_attr = getattr(models.fire.Fire, value_name)
        except AttributeError:
            return None

        async with self.client.session as session:
            result = (
                await session.scalars(
                    select(models.fire.Fire).where(value_attr == value)
                )
            ).one_or_none()

        if result:
            return getattr(result, element)
        return None

    async def delete_element(self, value_name, value):
        try:
            value_attr = getattr(models.fire.Fire, value_name)
        except AttributeError:
            return None

        async with self.client.session as session:
            async with session.begin():
                await session.execute(
                    delete(models.fire.Fire).where(value_attr == value)
                )

    async def add_to_board(self, added_msg, fireboard, total_reacts, emoji):
        exists = await self.get_element("fb_msg_id", "message_id", added_msg.id)
        if not exists:
            em = discord.Embed(
                color=discord.Color(0xFA43EE), description=added_msg.content
            )
            em.add_field(
                name="Original",
                value=f"[Message Link](https://discord.com/channels/{added_msg.guild.id}/{added_msg.channel.id}/{added_msg.id})",
                inline=True,
            )
            em.timestamp = added_msg.created_at
            em.set_author(name=added_msg.author.name, icon_url=added_msg.author.avatar)
            if added_msg.attachments:
                file = added_msg.attachments[0]
                spoiler = file.is_spoiler()
                if not spoiler and file.url.lower().endswith(
                    ("png", "jpeg", "jpg", "gif", "webp")
                ):
                    em.set_image(url=file.url)
                elif spoiler:
                    em.add_field(
                        name="Attachment",
                        value=f"||[{file.filename}]({file.url})||",
                        inline=False,
                    )
                else:
                    em.add_field(
                        name="Attachment",
                        value=f"[{file.filename}]({file.url})",
                        inline=False,
                    )
            if emoji == "unfire":
                newfb = await fireboard.send(
                    content=f"<:unfire:1128853116129923093> **{total_reacts}**",
                    embed=em,
                )
            else:
                newfb = await fireboard.send(
                    content=f"{fire} **{total_reacts}**", embed=em
                )
                get_fireboarded = await get_achievement("get_fireboarded")
                frequent_firerer = await get_achievement("frequent_firerer")
                firestarter = await get_achievement("firestarter")
                if not await get_fireboarded.is_achieved(added_msg.author):
                    await get_fireboarded.unlock(added_msg.author)
                    await added_msg.author.send(f"Achievement Get! {get_fireboarded!s}")
                if not await frequent_firerer.is_achieved(added_msg.author):
                    await frequent_firerer.add_progress(added_msg.author, 1)
                    if await frequent_firerer.is_achieved(added_msg.author):
                        await added_msg.author.send(
                            f"Achievement Get! {frequent_firerer!s}"
                        )
                if not await firestarter.is_achieved(added_msg.author):
                    await firestarter.add_progress(added_msg.author, 1)
                    if await firestarter.is_achieved(added_msg.author):
                        await added_msg.author.send(f"Achievement Get! {firestarter!s}")

            # newfb = await fireboard.send(f"{added_msg.author.name}'s message '{added_msg.content}' has {total_reacts} {fire}.")
            await self.add_msg(total_reacts, added_msg, newfb.id, fireboard.id, emoji)
        else:
            existing_message = await fireboard.fetch_message(exists)
            emoji = await self.get_element("emoji", "message_id", added_msg.id)
            if emoji == "unfire":
                await existing_message.edit(
                    content=f"<:unfire:1128853116129923093> **{total_reacts}**"
                )
            else:
                await existing_message.edit(content=f"{fire} **{total_reacts}**")
            await self.edit_msg(total_reacts, added_msg)

    # events
    @commands.Cog.listener()
    async def on_ready(self):
        log.info("Fire ready")

    @commands.hybrid_command()
    @generic_checks(max_check=False)
    async def howtofire(self, ctx):
        await ctx.send(
            "Create a channel named #fireboard, give me permission to talk there, and then I will automatically post messages with 5 :fire: reactions. Also, once a week I'll list the most fired messages."
        )

    @commands.command(hidden=True)
    @commands.is_owner()
    async def downloadserver(self, ctx):
        fields = [
            "userid",
            "username",
            "content",
            "messageid",
            "attachments",
            "reactions",
        ]
        await ctx.send("ok i am downloading, this will take an extremely long time")

        for channel in ctx.guild.text_channels:
            csvfile = f"{channel.id}.csv"
            await _ensure_header(csvfile, fields)

            await ctx.send(f"ok doing {channel.name}")
            log.debug(f"ok doing {channel.name}")

            count = 0
            batch = []
            BATCH_SIZE = 5000

            async with await anyio.open_file(
                csvfile, "a+", encoding="utf8", newline=""
            ) as csvf:
                async for message in channel.history(limit=None, oldest_first=True):
                    count += 1
                    if count % 10000 == 0:
                        log.debug(count)

                    row = [
                        str(message.author.id),
                        message.author.name,
                        message.content.replace("\r\n", "\n"),  # keep it tidy
                        str(message.id),
                        serialize_attachments(message.attachments),
                        serialize_reactions(message.reactions),
                    ]
                    batch.append(row)

                    if len(batch) >= BATCH_SIZE:
                        await _write_rows_async(csvf, batch)
                        batch.clear()

                # flush the last partial batch
                if batch:
                    await _write_rows_async(csvf, batch)

            await ctx.send(
                f"successfully downloaded {count} messages from {channel.name}"
            )

        await ctx.send("ok done")
        log.debug("ok done")

    @commands.command(hidden=True)
    @commands.is_owner()
    async def downloadchannel(self, ctx, channel: discord.TextChannel):
        fields = [
            "userid",
            "username",
            "content",
            "messageid",
            "attachments",
            "reactions",
        ]
        csvfile = f"{channel.id}.csv"
        await _ensure_header(csvfile, fields)

        await ctx.send(f"ok doing {channel.name}")

        i = 0
        batch = []
        BATCH_SIZE = 5000

        async with await anyio.open_file(
            csvfile, "a+", encoding="utf8", newline=""
        ) as csvf:
            async for message in channel.history(limit=None, oldest_first=True):
                i += 1
                row = [
                    str(message.author.id),
                    message.author.name,
                    message.content.replace("\r\n", "\n"),
                    str(message.id),
                    serialize_attachments(message.attachments),
                    serialize_reactions(message.reactions),
                ]
                batch.append(row)

                if len(batch) >= BATCH_SIZE:
                    await _write_rows_async(csvf, batch)
                    batch.clear()

            if batch:
                await _write_rows_async(csvf, batch)

        await ctx.reply(f"ok done, found {i} messages")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        fire = "🔥"
        if not payload.guild_id:
            return
        react_channel = self.client.get_channel(payload.channel_id)
        added_msg = await react_channel.fetch_message(payload.message_id)
        react = payload.emoji.name
        total_reacts = 0
        if react_channel.name in [
            "flop-or-fire",
            "fireboard",
            "unfireboard",
        ]:
            return
        if react != fire and react != "unfire":
            return
        if len(added_msg.reactions) == 1:  # wooo i love inconsistencies woooo
            total_reacts = added_msg.reactions[0].count
        else:
            for i, reaction in enumerate(added_msg.reactions):
                if reaction.emoji == react:
                    total_reacts = added_msg.reactions[i].count
                    break
        if react == fire and total_reacts >= 5:
            fireboard = None
            for channel in added_msg.guild.text_channels:
                if channel.name == "fireboard":
                    fireboard = channel
                    break
            if fireboard:
                if fireboard.id == react_channel.id:
                    return
                await self.add_to_board(added_msg, fireboard, total_reacts, "fire")
        elif react == "unfire" and total_reacts >= 5:
            fireboard = None
            for channel in added_msg.guild.text_channels:
                if channel.name == "unfireboard":
                    fireboard = channel
                    break
            if fireboard:
                if fireboard.id == react_channel.id:
                    return
                await self.add_to_board(added_msg, fireboard, total_reacts, "unfire")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        fire = "🔥"
        react_channel = self.client.get_channel(payload.channel_id)
        added_msg = await react_channel.fetch_message(payload.message_id)
        react = payload.emoji.name
        total_reacts = 0
        if react_channel.name in [
            "flop-or-fire",
            "fireboard",
            "unfireboard",
        ]:
            return
        if react != fire and react != "unfire":
            return
        if len(added_msg.reactions) == 1:  # wooo i love inconsistencies woooo
            total_reacts = added_msg.reactions[0].count
        else:
            for i, reaction in enumerate(added_msg.reactions):
                if reaction.emoji == react:
                    total_reacts = added_msg.reactions[i].count
                    break
        if react == fire and total_reacts >= 5:
            fireboard = None
            for channel in added_msg.guild.text_channels:
                if channel.name == "fireboard":
                    fireboard = channel
                    break
            if fireboard:
                if fireboard.id == react_channel.id:
                    return
                await self.add_to_board(added_msg, fireboard, total_reacts, "fire")
        elif react == "unfire" and total_reacts >= 5:
            fireboard = None
            for channel in added_msg.guild.text_channels:
                if channel.name == "unfireboard":
                    fireboard = channel
                    break
            if fireboard:
                if fireboard.id == react_channel.id:
                    return
                await self.add_to_board(added_msg, fireboard, total_reacts, "unfire")

    @commands.command(hidden=True)
    @generic_checks(max_check=False)
    async def unix(self, ctx):
        await ctx.send("The current unix time is `" + (str(int(t.time()))) + "`")

    @tasks.loop(seconds=30)
    async def weekly(self):
        CUTOFF = 604800  # 7 days

        async def get_pointer():
            async with self.client.session as session:
                async with session.begin():
                    result = (
                        await session.scalars(
                            select(models.fire.Misc).where(
                                models.fire.Misc.pointer == "weeklyFire"
                            )
                        )
                    ).one_or_none()

                    if result is not None:
                        return int(result.data)

                    now = int(t.time())
                    session.add(models.fire.Misc(pointer="weeklyFire", data=now))
                    return now

        async def bump_pointer(old):
            async with self.client.session as session:
                async with session.begin():
                    await session.execute(
                        update(models.fire.Misc)
                        .where(models.fire.Misc.pointer == "weeklyFire")
                        .values(data=old + CUTOFF)
                    )

        async def top_messages_since(unix_now: int) -> list[models.fire.Fire]:
            cutoff = unix_now - CUTOFF
            async with self.client.session as session:
                return (
                    await session.scalars(
                        select(models.fire.Fire)
                        .where(
                            models.fire.Fire.timestamp > cutoff,
                            models.fire.Fire.emoji == "fire",
                        )
                        .order_by(models.fire.Fire.reacts.desc())
                    )
                ).all()

        try:
            old = await get_pointer()
            now = int(t.time())
            if now <= old + CUTOFF:
                return  # not time yet

            for server in self.client.guilds:
                fireboard = next(
                    (ch for ch in server.text_channels if ch.name == "fireboard"), None
                )
                if not fireboard:
                    continue

                results = await top_messages_since(now)
                server_msgs = [m for m in results if m.fb_id == fireboard.id]

                top5 = server_msgs[:5]

                if not top5:
                    continue

                lines = [
                    "Congrats to the following people for getting the top 5 hottest messages this week:"
                ]
                for m in top5:
                    try:
                        user = await self.client.fetch_user(int(m.user_id))
                        user_display = user.mention
                    except Exception:
                        log.warning("weekly: couldn't fetch user %s", m.user_id)
                        user_display = str(m.user_id)

                    lines.append(
                        f"{fire} **{m.reacts}** - {user_display} - "
                        f"https://discord.com/channels/{m.guild_id}/{m.channel_id}/{m.message_id}"
                    )

                await fireboard.send("\n".join(lines))

            await bump_pointer(old)

        except Exception:
            # Log but don't let the task die
            log.exception("weekly loop crashed")

    @commands.hybrid_command()
    @generic_checks(max_check=False)
    async def highestfire(self, ctx, channel: discord.TextChannel = None):
        if not channel:
            async with self.client.session as session:
                result = (
                    await session.scalars(
                        select(models.fire.Fire)
                        .where(
                            models.fire.Fire.guild_id == ctx.guild.id,
                            models.fire.Fire.emoji == "fire",
                        )
                        .order_by(models.fire.Fire.reacts.desc())
                        .limit(1)
                    )
                ).one_or_none()
            if not result:
                await ctx.send(
                    "something went wrong, either there are no fire reacts in this server, or my creator is a dumbass. the latter is more likely."
                )
                return
            await ctx.send(
                f"https://discord.com/channels/{result.guild_id}/{result.channel_id}/{result.message_id}"
            )
        else:
            async with self.client.session as session:
                result = (
                    await session.scalars(
                        select(models.fire.Fire)
                        .where(
                            models.fire.Fire.channel_id == channel.id,
                            models.fire.Fire.emoji == "fire",
                        )
                        .order_by(models.fire.Fire.reacts.desc())
                        .limit(1)
                    )
                ).one_or_none()
            if not result:
                await ctx.send(
                    "something went wrong, either there are no fire reacts in this server, or my creator is a dumbass. the latter is more likely."
                )
                return
            await ctx.send(
                f"https://discord.com/channels/{result.guild_id}/{result.channel_id}/{result.message_id}"
            )

    @commands.hybrid_command()
    @generic_checks(max_check=False)
    async def highestunfire(self, ctx, channel: discord.TextChannel = None):
        if not channel:
            async with self.client.session as session:
                result = (
                    await session.scalars(
                        select(models.fire.Fire)
                        .where(
                            models.fire.Fire.guild_id == ctx.guild.id,
                            models.fire.Fire.emoji == "unfire",
                        )
                        .order_by(models.fire.Fire.reacts.desc())
                        .limit(1)
                    )
                ).one_or_none()
            if not result:
                await ctx.send(
                    "something went wrong, either there are no fire reacts in this server, or my creator is a dumbass. the latter is more likely."
                )
                return
            await ctx.send(
                f"https://discord.com/channels/{result.guild_id}/{result.channel_id}/{result.message_id}"
            )
        else:
            async with self.client.session as session:
                result = (
                    await session.scalars(
                        select(models.fire.Fire)
                        .where(
                            models.fire.Fire.channel_id == channel.id,
                            models.fire.Fire.emoji == "unfire",
                        )
                        .order_by(models.fire.Fire.reacts.desc())
                        .limit(1)
                    )
                ).one_or_none()
            if not result:
                await ctx.send(
                    "something went wrong, either there are no fire reacts in this server, or my creator is a dumbass. the latter is more likely."
                )
                return
            await ctx.send(
                f"https://discord.com/channels/{result.guild_id}/{result.channel_id}/{result.message_id}"
            )

    @commands.hybrid_command()
    @generic_checks(max_check=False)
    async def fireleaderboard(self, ctx, fire: str | None = None):
        # get users, count fire for each, display on leaderboard
        if not fire:
            fire = "fire"
        data = {}
        messageids = []
        async with self.client.session as session:
            results = (await session.scalars(select(models.fire.Fire))).all()
        for result in results:
            if result.message_id not in messageids and result.emoji == fire:
                messageids.append(result.message_id)
                try:
                    data[f"{result.user_id}"] += result.reacts
                except KeyError:
                    data[f"{result.user_id}"] = result.reacts
        # sort dictionary by value
        sorted_data = {
            k: v
            for k, v in sorted(data.items(), key=lambda item: item[1], reverse=True)
        }
        em = discord.Embed(title="Top 10 Fire Havers", color=discord.Color(0xFA43EE))
        index = 0
        for key, value in sorted_data.items():
            if index == 10:
                break
            index += 1
            bal = value
            user_id = key
            try:
                username = await self.client.fetch_user(user_id)
                em.add_field(name=f"{index}. {username}", value=f"{bal}", inline=False)
            except:
                index -= 1
        await ctx.send(embed=em)


async def setup(client):
    await client.add_cog(Fire(client))
