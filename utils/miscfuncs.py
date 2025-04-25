import random as rd
import time

import aiosqlite
from PIL import Image, ImageDraw

if __name__ == "__main__":
    print(
        "If you're reading this, discord.py is trying to load miscfuncs.py as a cog. This should not be happening!!!!!"
    )

bank = "./data/database.sqlite"


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


async def is_blacklisted(*args):
    async with aiosqlite.connect(bank, timeout=10) as db:
        cursor = await db.cursor()
        current_time = get_unix()
        for user_id in args:
            await cursor.execute(
                f"SELECT * FROM blacklist WHERE user_id={user_id} AND (timestamp > {current_time} OR timestamp = 0)"
            )
            result = await cursor.fetchone()
            if result:
                return True, result[1]
    return False, 0


async def blacklist_user(user_id, timestamp):
    async with aiosqlite.connect(bank, timeout=10) as db:
        cursor = await db.cursor()
        await cursor.execute(
            f"INSERT INTO blacklist (user_id, timestamp) VALUES ({user_id}, {timestamp})"
        )
        await db.commit()


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
