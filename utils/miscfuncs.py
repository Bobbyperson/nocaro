import functools
import random as rd
import time

import discord
from discord.ext import commands
from PIL import Image, ImageDraw
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import models
from __main__ import Session
from utils.econfuncs import checkmax

if __name__ == "__main__":
    print(
        "If you're reading this, discord.py is trying to load miscfuncs.py as a cog. This should not be happening!!!!!"
    )

bank = "./data/database.sqlite"


# TODO update every callsite to pass sessions explicitly
# until then this will be used as a stop-gap solution
def session_decorator(func):
    async def wrapped(*args, **kwargs):
        session = None
        if not isinstance(args[0], AsyncSession):
            session = Session()
            args = list(args)
            args.insert(0, session)

        try:
            retval = await func(*args, **kwargs)
        except:
            if session is not None:
                await session.rollback()
            raise
        else:
            if session is not None:
                await session.commit()
        finally:
            if session is not None:
                await session.close()

        return retval

    return wrapped


def generic_checks(
    blacklist_check=True, max_check=True, ignored_check=True, dm_check=True
):
    def decorator(func):
        @functools.wraps(func)
        async def wrapped(*args, **kwargs):
            ctx = None

            for arg in args:
                if isinstance(arg, commands.Context):
                    ctx = arg
                    blacklist = await is_blacklisted(arg.author.id)
                    if dm_check and isinstance(arg.channel, discord.channel.DMChannel):
                        await ctx.send("Command may not be used in a DM.")
                        return False
                    if ignored_check and await is_ignored(arg.channel.id):
                        await arg.author.send(
                            "The channel you sent that command in is ignored, try a bot channel instead."
                        )
                        return False
                    if blacklist_check and blacklist[0]:
                        await arg.send("You are blacklisted from Nocaro.")
                        return False
                    if max_check and await checkmax(arg.author):
                        await arg.send(
                            "Your body is too weak from the endless games. Maybe you should attempt to `,enterthecave`."
                        )
                        return False
                    break

            if ctx:
                for arg in args:
                    if isinstance(arg, discord.Member | discord.User):
                        if blacklist_check and await is_blacklisted(arg.id):
                            await ctx.send(
                                "The person you invoked is blacklisted from Nocaro."
                            )
                            return False

            return await func(*args, **kwargs)

        return wrapped

    return decorator


def clean_username(name):  # fuck you ralkinson!!!!!!!!!
    return name.strip("`")


# turn [1,2,3] to "1, 2, 3"
def array_to_string(arr):
    x = ", ".join(str(x) for x in arr)
    return x


def get_unix():
    return int(time.time())


# turn 1000000 into 1,000,000
def commafy(num):
    return format(int(num), ",d")


# function for turning seconds into human readable time
async def human_time_duration(seconds):
    TIME_DURATION_UNITS = (
        ("week", 60 * 60 * 24 * 7),
        ("day", 60 * 60 * 24),
        ("hour", 60 * 60),
        ("minute", 60),
        ("second", 1),
    )
    if seconds == 0:
        lol = rd.randint(1, 9)
        return f"0.{lol} seconds"
    parts = []
    for unit, div in TIME_DURATION_UNITS:
        amount, seconds = divmod(int(seconds), div)
        if amount > 0:
            parts.append("{} {}{}".format(amount, unit, "" if amount == 1 else "s"))
    return ", ".join(parts)


async def send_webhook(ctx, name, avatar, message):
    try:
        webhooks = await ctx.channel.webhooks()
        if webhooks:
            webhook = webhooks[0]
        else:
            webhook = await ctx.channel.create_webhook(
                name="Nocaro_NPC", reason="npc event"
            )
        msg = await webhook.send(content=message, avatar_url=avatar, username=name)
    except:
        try:
            msg = await ctx.send(f"{name}: {message}")
        except:
            msg = await ctx.channel.send(f"{name}: {message}")
    return msg


def draw_rotated_text(image, angle, xy, text, fill, *args, **kwargs):
    """Draw text at an angle into an image, takes the same arguments
        as Image.text() except for:

    :param image: Image to write text into
    :param angle: Angle to write text at
    """
    # get the size of our image
    width, height = image.size
    max_dim = max(width, height)

    # build a transparency mask large enough to hold the text
    mask_size = (max_dim * 2, max_dim * 2)
    mask = Image.new("L", mask_size, 0)

    # add text to mask
    draw = ImageDraw.Draw(mask)
    draw.text((max_dim, max_dim), text, 255, *args, **kwargs)

    if angle % 90 == 0:
        # rotate by multiple of 90 deg is easier
        rotated_mask = mask.rotate(angle)
    else:
        # rotate an an enlarged mask to minimize jaggies
        bigger_mask = mask.resize((max_dim * 8, max_dim * 8), resample=Image.BICUBIC)
        rotated_mask = bigger_mask.rotate(angle).resize(
            mask_size, resample=Image.LANCZOS
        )

    # crop the mask to match image
    mask_xy = (max_dim - xy[0], max_dim - xy[1])
    b_box = (*mask_xy, mask_xy[0] + width, mask_xy[1] + height)
    mask = rotated_mask.crop(b_box)

    # paste the appropriate color, with the text transparency mask
    color_image = Image.new("RGBA", image.size, fill)
    image.paste(color_image, mask)


@session_decorator
async def is_blacklisted(session, *args):
    current_time = get_unix()
    for user_id in args:
        result = (
            await session.execute(
                select(models.database.Blacklist).where(
                    models.database.Blacklist.user_id == user_id,
                    or_(
                        models.database.Blacklist.timestamp > current_time,
                        models.database.Blacklist.timestamp == 0,
                    ),
                )
            )
        ).scalar_one_or_none()
        if result:
            return True, result.user_id
    return False, 0


@session_decorator
async def blacklist_user(session, user_id, timestamp):
    async with session.begin():
        session.add(models.database.Blacklist(user_id=user_id, timestamp=timestamp))
        pass


@session_decorator
async def is_ignored(session, channel_id):
    return (
        await session.scalars(
            select(models.database.Ignore).where(
                models.database.Ignore.channelID == channel_id
            )
        )
    ).one_or_none() is not None


def human_time_to_seconds(*args) -> int:
    if not args or len(args) == 0:
        return 0

    if len(args) == 1:
        time = args[0]
        unit = time[-1]
        try:
            value = float(time[:-1])
        except ValueError:
            return -1

        match unit:
            case "m":
                return int(value * 60)
            case "h":
                return int(value * 60 * 60)
            case "d":
                return int(value * 60 * 60 * 24)
            case "w":
                return int(value * 60 * 60 * 24 * 7)
            case "M":
                return int(value * 60 * 60 * 24 * 30)
            case "y":
                return int(value * 60 * 60 * 24 * 365)
            case "_":
                return int(value)

    value = 0
    for i, arg in enumerate(args):
        if i == 0:
            try:
                time = float(arg)
            except ValueError:
                return -1
            continue

        match arg:
            case "s" | "second" | "seconds" | "sec":
                value += float(time)
            case "m" | "minute" | "minutes" | "min":
                value += float(time) * 60
            case "h" | "hour" | "hours" | "hr" | "hrs":
                value += float(time) * 60 * 60
            case "d" | "day" | "days":
                value += float(time) * 60 * 60 * 24
            case "w" | "week" | "weeks":
                value += float(time) * 60 * 60 * 24 * 7
            case "M" | "month" | "months":
                value += float(time) * 60 * 60 * 24 * 30
            case "y" | "year" | "years":
                value += float(time) * 60 * 60 * 24 * 365

    return int(value)


# input: ["string1", "string2", "string3"]
# output: a formatted string with stars
def starspeak(strings, max_width=64, min_stars=3, max_stars=6) -> str:
    stars = ["*", ".", "˚", "☆", "✦", "˳", "·", "˖", "✶", "⋆", "✧̣̇"]
    final = []
    final.append(" " * max_width)
    final.append(" " * max_width)
    for string in strings:
        if max_width < len(string):
            raise ValueError("Text is longer than maximum width.")

        # left / right padding
        left = (max_width - len(string)) // 2
        right = max_width - len(string) - left
        final.append(f"{' ' * left}{string}{' ' * right}")
    final.append(" " * max_width)
    final.append(" " * max_width)
    for i, string in enumerate(final):
        amount_of_spaces = string.count(" ")
        if amount_of_spaces <= 3:
            continue
        for char in string:
            if char != " ":
                stars_to_make = min(
                    rd.randint(min_stars // 2, max_stars // 2), amount_of_spaces
                )
                break
        else:
            stars_to_make = min(rd.randint(min_stars, max_stars), amount_of_spaces)
        for _ in range(stars_to_make):
            index = rd.randint(0, len(string) - 1)
            while string[index] != " ":
                index = rd.randint(0, len(string) - 1)
            string = string[:index] + rd.choice(stars) + string[index + 1 :]
        final[i] = string

    return "```\n" + "\n".join(final) + "```"
