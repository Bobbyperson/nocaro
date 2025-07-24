import os
import random as rd
import re
import time
from decimal import Decimal, getcontext

import anyio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models
import utils.miscfuncs as mf
from __main__ import Session
from utils.achievements import get_achievement, money_achievements_list

if __name__ == "__main__":
    print(
        "If you're reading this, discord.py is trying to load econfuncs.py as a cog. This should not be happening!!!!!"
    )

bank = "./data/database.sqlite"

getcontext().prec = 200  # crank precision way up

# max 64 bit signed integer
MAX_INT = (2 ** (64 - 1)) - 1


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


# insert new row into database
@session_decorator
async def new_account(session, user):
    acc = models.economy.Main(
        balance="0",
        bananas=0,
        user_ID=user.id,
        immunity=0,
        level=0,
        inventory=None,
        winloss="XXXXXXXXXXXXXXXXXXX",
        invested=0,
    )
    session.add(acc)

    return acc


@session_decorator
async def get_or_create_account(session, user):
    result = await session.execute(
        select(models.economy.Main).where(models.economy.Main.user_ID == user.id)
    )
    user_main = result.scalars().first()
    if user_main is None:
        user_main = await new_account(session, user)
    return user_main


# get uer's balance, returns int
@session_decorator
async def get_bal(session, user):
    user_main = await get_or_create_account(session, user)
    return int(user_main.balance)


# update user's balance
@session_decorator
async def update_amount(
    session, user, change=0, bonuses=True, tracker_reason="unknown"
):
    user_main = await get_or_create_account(session, user)
    bal = int(user_main.balance)
    change = int(change)
    uncapped = False
    prestieges = await get_prestiege(session, user)
    if prestieges is not None and bonuses:
        if change > 0:
            change = int(
                Decimal(change)
                + (Decimal(change) * (Decimal("0.025") * Decimal(prestieges[0])))
            )
        else:
            change = int(
                Decimal(change)
                - (Decimal(change) * (Decimal("0.05") * Decimal(prestieges[2])))
            )
    if prestieges is not None:
        uncapped = True if prestieges[3] else False
    new_balance = bal + change
    if new_balance > int(Decimal(10) ** 99):
        # python interally stores 1e99 as a float, which causes precision issues when converted to an int
        # additionally, str(1e99) returns '1e+99', which for some reason, cannot be converted back to an int
        # Decimal(1e99) returns '1E+99', which is also not convertible to an int
        # so we have to use Decimal(10) ** 99 to get the correct value, and to avoid issues when storing it in the db
        new_balance = int(Decimal(10) ** 99)
        excess = Decimal(bal) + Decimal(change) - int(Decimal(10) ** 99)
        user_main.balance = str(new_balance)
        session.add(
            models.economy.History(
                user_id=user.id,
                amount=str(excess),
                reason=tracker_reason,
                time=int(time.time()),
            )
        )
    elif not uncapped and new_balance > MAX_INT:
        new_balance = MAX_INT
        excess = bal + change - MAX_INT
        user_main.balance = str(new_balance)
        session.add(
            models.economy.History(
                user_id=user.id,
                amount=str(excess),
                reason=tracker_reason,
                time=int(time.time()),
            )
        )
    else:
        user_main.balance = str(new_balance)
        session.add(
            models.economy.History(
                user_id=user.id,
                amount=str(change),
                reason=tracker_reason,
                time=int(time.time()),
            )
        )
    for achievement in money_achievements_list:
        if not await achievement.is_achieved(user):
            if achievement.needed_progress <= new_balance:
                await achievement.unlock(user)
                await user.send("Milestone reached: " + str(achievement))
                if achievement.internal_name == "halfway_point":
                    await user.send(
                        mf.starspeak(
                            [
                                "NEARLY SO NEARLY THERE",
                                "AT THE END SOMETHING WAITS",
                                "SOMETHING FOR ONE OR MANY",
                                "",
                                "DO NOT SHARE THIS COMMUNICATION",
                            ]
                        )
                    )
    if new_balance < 0:
        mogul_moves = await get_achievement("mogul_moves")
        if not await mogul_moves.is_achieved(user):
            await mogul_moves.unlock(user)
            await user.send(f"Achievement Get! {mogul_moves!s}")
    if new_balance > 0 and bal > 0 and new_balance / bal <= 0.1:
        better_left_than_dead = await get_achievement("better_left_than_dead")
        if not await better_left_than_dead.is_achieved(user):
            await better_left_than_dead.unlock(user)
            await user.send(f"Achievement Get! {better_left_than_dead!s}")


# get user's level, returns int
@session_decorator
async def get_level(session, user):
    user_main = await get_or_create_account(session, user)
    return user_main.level


# update user's level
@session_decorator
async def update_level(session, user, change=0):
    if change == 0:
        return

    user_main = await get_or_create_account(session, user)
    user_main.level += change


# get user's bananas, returns int
@session_decorator
async def get_banana(session, user):
    user_main = await get_or_create_account(session, user)
    return user_main.bananas


# update user's bananas
@session_decorator
async def update_banana(session, user, change=0):
    user_main = await get_or_create_account(session, user)
    user_main.bananas += change


# get user's immunity, return int
@session_decorator
async def get_immunity(session, user):
    user_main = await get_or_create_account(session, user)
    return user_main.immunity


# update user's immunity
@session_decorator
async def update_immunity(session, user, change=0):
    user_main = await get_or_create_account(session, user)
    user_main.immunity = change


# get user's inventory, returns array
@session_decorator
async def get_inv(session, user) -> list | None:
    user_main = await get_or_create_account(session, user)
    userinv = user_main.inventory
    if not userinv:
        return None
    return userinv[0].split(",")


# add item to user's inventory
@session_decorator
async def add_item(session, user, item):
    inventory = await get_inv(session, user)
    if not inventory:
        inventory = []
    items = item.split()
    for thing in items:
        inventory.append(thing)
    if len(inventory) > 1:
        c_inv = ",".join(str(x) for x in inventory).strip("[]")
    else:
        c_inv = inventory[0]

    user_main = await get_or_create_account(session, user)
    user_main.inventory = c_inv


# remove item from user's inventory
@session_decorator
async def remove_item(session, user, item):
    inventory = await get_inv(session, user)
    if not inventory:
        inventory = []
    inventory.remove(item)
    c_inv = ",".join(str(x) for x in inventory).strip("[]")

    user_main = await get_or_create_account(session, user)
    user_main.inventory = c_inv


@session_decorator
async def checkmax(session, user):
    amnt = await get_bal(session, user)
    prestieges = await get_prestiege(session, user)
    if amnt >= int(Decimal(10) ** 99):
        dif = amnt - int(Decimal(10) ** 99)
        await update_amount(session, user, amnt - dif)
        return True
    if prestieges and prestieges[3]:
        return False
    if amnt >= MAX_INT:  # int limt
        dif = amnt - MAX_INT
        await update_amount(session, user, amnt - dif)
        return True
    if amnt == MAX_INT:
        return True
    return False


# get winloss, returns string
@session_decorator
async def get_winloss(session, user):
    """_summary_

    Args:
        user (discord.User): discord user object

    Returns:
        string: wllw
    """
    user_main = await get_or_create_account(session, user)
    return user_main.winloss


# update winloss, expects only one letter, anything else will do nothing
@session_decorator
async def update_winloss(session, user, wl):
    if len(wl) > 1:  # idiot proofing
        return

    current = str(await get_winloss(session, user))
    if len(current) >= 20:
        current = current[1:]
    current = current + wl
    user_main = await get_or_create_account(session, user)
    user_main.winloss = current


# returns X,X,X,X,etc... as str
@session_decorator
async def formatted_winloss(session, user):
    current = await get_winloss(session, user)
    formatted = []
    for i in range(len(current)):
        if current[i] == "w":
            formatted.append(":green_square:")
        elif current[i] == "l":
            formatted.append(":red_square:")
        elif current[i] == "X":
            formatted.append(":x:")
        elif current[i] == "t":
            formatted.append(":black_large_square:")
        elif current[i] == "b":
            formatted.append(":white_check_mark:")
        else:
            formatted.append(":question:")
    return mf.array_to_string(formatted)


# get random map
async def get_random_item():
    file_path = "maps/maps.txt"
    async with await anyio.open_file(file_path) as f:
        maps = [line.rstrip() for line in await f.readlines()]
        item = rd.choice(maps)
        return item


# get specific map
async def get_item(item):
    file_path = "maps/maps.txt"
    if os.path.exists(file_path):
        async with await anyio.open_file(file_path, encoding="utf-8") as f:
            maps = [line.rstrip() for line in await f.readlines()]
            for thing in maps:
                if item in thing:
                    return thing
    else:
        return None


SUFFIX_EXP = {
    "h": 2,
    "k": 3,
    "m": 6,
    "b": 9,
    "t": 12,
    "q": 15,
    "Q": 18,
    "s": 21,
    "S": 24,
    "o": 27,
    "n": 30,
    "d": 33,
    "u": 36,
    "D": 39,
}


def moneyfy(amount):
    if amount is None:
        return 0

    if isinstance(amount, int):
        return amount

    if isinstance(amount, str):
        amount = amount.replace(",", "").replace(" ", "")

    if str(amount).lstrip("-").isdigit():
        return int(amount)

    neg = str(amount).startswith("-")
    if neg:
        amount = str(amount)[1:]

    m = re.fullmatch(r"((?:\d*\.)?\d+)([a-zA-Z]+)", str(amount))
    if not m:
        return 0

    num, letters = m.groups()
    exp = sum(SUFFIX_EXP.get(ch, 0) for ch in letters)  # total exponent
    total = Decimal(num) * (Decimal(10) ** exp)
    if neg:
        total = -total
    return int(total)


def unmoneyfy(amount):  # converts int to string, so 1,000 to 1k
    if isinstance(amount, str):
        amount = amount.strip(",")
        amount = int(amount)

    if amount >= 1e39:
        return f"{amount / 1e39:.2f}".rstrip("0").rstrip(".") + "D"
    if amount >= 1e36:
        return f"{amount / 1e36:.2f}".rstrip("0").rstrip(".") + "u"
    if amount >= 1e33:
        return f"{amount / 1e33:.2f}".rstrip("0").rstrip(".") + "d"
    if amount >= 1e30:
        return f"{amount / 1e30:.2f}".rstrip("0").rstrip(".") + "n"
    if amount >= 1e27:
        return f"{amount / 1e27:.2f}".rstrip("0").rstrip(".") + "o"
    if amount >= 1e24:
        return f"{amount / 1e24:.2f}".rstrip("0").rstrip(".") + "S"
    if amount >= 1e21:
        return f"{amount / 1e21:.2f}".rstrip("0").rstrip(".") + "s"
    if amount >= 1e18:
        return f"{amount / 1e18:.2f}".rstrip("0").rstrip(".") + "Q"
    if amount >= 1e15:
        return f"{amount / 1e15:.2f}".rstrip("0").rstrip(".") + "q"
    if amount >= 1e12:
        return f"{amount / 1e12:.2f}".rstrip("0").rstrip(".") + "t"
    if amount >= 1e9:
        return f"{amount / 1e9:.2f}".rstrip("0").rstrip(".") + "b"
    if amount >= 1e6:
        return f"{amount / 1e6:.2f}".rstrip("0").rstrip(".") + "m"
    if amount >= 1e3:
        return f"{amount / 1e3:.2f}".rstrip("0").rstrip(".") + "k"

    return amount


@session_decorator
async def get_investment(session, user):
    user_main = await get_or_create_account(session, user)
    return user_main.invested


@session_decorator
async def add_investment(session, user, amount):
    user_main = await get_or_create_account(session, user)
    user_main.invested += amount


@session_decorator
async def get_or_create_prestiege(session, user):
    result = await session.execute(
        select(models.economy.Prestiege).where(
            models.economy.Prestiege.user_id == user.id,
        )
    )
    row = result.scalars().first()
    if row is None:
        row = models.economy.Prestiege(
            user_id=user.id, pres1=0, pres2=0, pres3=0, pres4=0, pres5=0
        )
        session.add(row)
    return row


@session_decorator
async def log_prestiege(session, user, pres):
    entry = await get_or_create_prestiege(session, user)
    setattr(entry, f"pres{pres}", getattr(entry, f"pres{pres}") + 1)


@session_decorator
async def get_prestiege(session, user):
    user_main = await get_or_create_prestiege(session, user)
    maximum_overdrive = await get_achievement("maximum_overdrive")
    total = (
        user_main.pres1
        + user_main.pres2
        + user_main.pres3
        + user_main.pres4
        + user_main.pres5
    )
    if not await maximum_overdrive.is_achieved(user) and total > 0:
        if total >= 7:
            await maximum_overdrive.unlock(user)
            await user.send(f"Achievement Get! {maximum_overdrive!s}")
        else:
            await maximum_overdrive.set_progress(user, total, overwrite=True)
    return [
        user_main.pres1,
        user_main.pres2,
        user_main.pres3,
        user_main.pres4,
        user_main.pres5,
    ]
