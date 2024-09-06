import aiosqlite
import os
import re
import random as rd
import cogs.utils.miscfuncs as mf


if __name__ == "__main__":
    print(
        "If you're reading this, discord.py is trying to load econfuncs.py as a cog. This should not be happening!!!!!"
    )

bank = "./data/database.sqlite"


# insert new row into database
async def new_account(user):
    async with aiosqlite.connect(bank) as db:
        cursor = await db.cursor()
        USER_ID = user.id
        await cursor.execute(
            f'INSERT INTO main(balance, bananas, user_ID, immunity, level, inventory, winloss, invested) values("0", 0, {USER_ID}, 0, 0, NULL, "XXXXXXXXXXXXXXXXXXX", 0)'
        )
        await db.commit()


# get uer's balance, returns int
async def get_bal(user):
    result_userBal = None
    while not result_userBal:
        db = await aiosqlite.connect(bank, timeout=10)
        cursor = await db.cursor()
        USER_ID = user.id
        await cursor.execute(f"SELECT user_id FROM main WHERE user_id={USER_ID}")
        result_userID = await cursor.fetchone()
        if not result_userID:
            await new_account(user)
        else:
            await cursor.execute(f"SELECT balance FROM main WHERE user_id={USER_ID}")
            result_userBal = await cursor.fetchone()
            await cursor.close()
            await db.close()
            return int(result_userBal[0])


async def get_history(user):
    result_userBal = None
    while not result_userBal:
        db = await aiosqlite.connect(bank, timeout=10)
        cursor = await db.cursor()
        USER_ID = user.id
        await cursor.execute(f"SELECT user_id FROM main WHERE user_id={USER_ID}")
        result_userID = await cursor.fetchone()
        if not result_userID:
            return None
        await cursor.execute(f"SELECT balance FROM main WHERE user_id={USER_ID}")
        result_userBal = await cursor.fetchone()
        data = [result_userBal]
        for i in range(1, 10):
            await cursor.execute(f"SELECT user_id FROM old{i} WHERE user_id={USER_ID}")
            result_userID = await cursor.fetchone()
            if not result_userID:
                return None
            await cursor.execute(f"SELECT balance FROM old{i} WHERE user_id={USER_ID}")
            result = await cursor.fetchone()
            data.append(result)
        await cursor.close()
        await db.close()
        return data


# update user's balance
async def update_amount(user, change=0, bonuses=True):
    db = await aiosqlite.connect(bank, timeout=10)
    bal = await get_bal(user)
    USER_ID = user.id
    cursor = await db.cursor()
    change = int(change)
    uncapped = False
    prestieges = await get_prestiege(user)
    if prestieges is not None and bonuses:
        uncapped = True if prestieges[3] else False
        if change > 0:
            change = int(change + (change * (0.025 * prestieges[0])))
        else:
            change = int(change - (change * (0.05 * prestieges[2])))
    if (bal + change) > 9223372036854775807 and not uncapped:
        await cursor.execute(
            f"UPDATE main SET balance = 9223372036854775807 WHERE user_id={USER_ID}"
        )
    else:
        await cursor.execute(
            f"UPDATE main SET balance = {bal + change} WHERE user_id={USER_ID}"
        )
    await db.commit()
    await cursor.close()
    await db.close()
    return await get_bal(user)


# get user's level, returns int
async def get_level(user):
    result_userBal = None
    while not result_userBal:
        db = await aiosqlite.connect(bank, timeout=10)
        cursor = await db.cursor()
        USER_ID = user.id
        await cursor.execute(f"SELECT user_id FROM main WHERE user_id={USER_ID}")
        result_userID = await cursor.fetchone()
        if not result_userID:
            await new_account(user)
        else:
            await cursor.execute(f"SELECT level FROM main WHERE user_id={USER_ID}")
            result_userBal = await cursor.fetchone()
            await cursor.close()
            await db.close()
            return result_userBal[0]


# update user's level
async def update_level(user, change=0):
    db = await aiosqlite.connect(bank, timeout=10)
    await get_bal(user)
    USER_ID = user.id
    cursor = await db.cursor()
    if change == 0:
        return await get_bal(user)
    await cursor.execute(
        f"UPDATE main SET level = level + {change} WHERE user_id={USER_ID}"
    )
    await db.commit()
    await cursor.close()
    await db.close()
    return await get_bal(user)


# get user's bananas, returns int
async def get_banana(user):
    result_userBal = None
    while not result_userBal:
        db = await aiosqlite.connect(bank, timeout=10)
        cursor = await db.cursor()
        USER_ID = user.id
        await cursor.execute(f"SELECT user_id FROM main WHERE user_id={USER_ID}")
        result_userID = await cursor.fetchone()
        if not result_userID:
            await new_account(user)
        else:
            await cursor.execute(f"SELECT bananas FROM main WHERE user_id={USER_ID}")
            result_userBal = await cursor.fetchone()
            await cursor.close()
            await db.close()
            return result_userBal[0]


# update user's bananas
async def update_banana(user, change=0):
    db = await aiosqlite.connect(bank, timeout=10)
    await get_bal(user)
    USER_ID = user.id
    cursor = await db.cursor()
    if change == 0:
        return await get_bal(user)
    await cursor.execute(
        f"UPDATE main SET bananas = bananas + {change} WHERE user_id={USER_ID}"
    )
    await db.commit()
    await cursor.close()
    await db.close()
    return await get_bal(user)


# get user's immunity, return int
async def get_immunity(user):
    result_userBal = None
    while not result_userBal:
        db = await aiosqlite.connect(bank, timeout=10)
        cursor = await db.cursor()
        USER_ID = user.id
        await cursor.execute(f"SELECT user_id FROM main WHERE user_id={USER_ID}")
        result_userID = await cursor.fetchone()
        if not result_userID:
            await new_account(user)
        else:
            await cursor.execute(f"SELECT immunity FROM main WHERE user_id={USER_ID}")
            result_userImmunity = await cursor.fetchone()
            await db.close()
            return result_userImmunity[0]


# update user's immunity
async def update_immunity(user, change=0):
    db = await aiosqlite.connect(bank, timeout=10)
    await get_immunity(user)
    USER_ID = user.id
    cursor = await db.cursor()
    if change == 0:
        return await get_immunity(user)
    await cursor.execute(f"UPDATE main SET immunity = {change} WHERE user_id={USER_ID}")
    await db.commit()
    await cursor.close()
    await db.close()
    return await get_immunity(user)


# get user's inventory, returns array
async def get_inv(user) -> list:
    result_userInv = None
    while not result_userInv:
        db = await aiosqlite.connect(bank, timeout=10)
        cursor = await db.cursor()
        USER_ID = user.id
        await cursor.execute(f"SELECT user_id FROM main WHERE user_id={USER_ID}")
        result_userID = await cursor.fetchone()
        if not result_userID:
            await new_account(user)
        else:
            await cursor.execute(f"SELECT inventory FROM main WHERE user_id={USER_ID}")
            result_userInv = await cursor.fetchone()
            if not result_userInv[0]:
                await cursor.close()
                return None
            c_inv = result_userInv[0].split(",")
            await cursor.close()
            await db.close()
            return c_inv


# add item to user's inventory
async def add_item(user, item):
    db = await aiosqlite.connect(bank, timeout=10)
    cursor = await db.cursor()
    USER_ID = user.id
    inventory = await get_inv(user)
    if not inventory:
        inventory = []
    items = item.split()
    for thing in items:
        inventory.append(thing)
    if len(inventory) > 1:
        c_inv = ",".join(str(x) for x in inventory).strip("[]")
    else:
        c_inv = inventory[0]
    await cursor.execute(
        f'UPDATE main SET inventory = "{c_inv}" WHERE user_id={USER_ID}'
    )
    await db.commit()
    await cursor.close()
    await db.close()


# remove item from user's inventory
async def remove_item(user, item):
    db = await aiosqlite.connect(bank, timeout=10)
    cursor = await db.cursor()
    USER_ID = user.id
    inventory = await get_inv(user)
    if inventory:
        inventory = inventory
    else:
        inventory = []
    inventory.remove(item)
    c_inv = ",".join(str(x) for x in inventory).strip("[]")
    await cursor.execute(
        f'UPDATE main SET inventory = "{c_inv}" WHERE user_id={USER_ID}'
    )
    await db.commit()
    await cursor.close()
    await db.close()


async def checkmax(user):
    amnt = await get_bal(user)
    prestieges = await get_prestiege(user)
    if prestieges:
        if prestieges[3]:
            return False
    if amnt > 9223372036854775807:  # int limt
        dif = amnt - 9223372036854775807
        await update_amount(user, amnt - dif)
        return True
    if amnt == 9223372036854775807:
        return True
    return False


# get winloss, returns string
async def get_winloss(user):
    """_summary_

    Args:
        user (discord.User): discord user object

    Returns:
        string: wllw
    """
    result_userBal = None
    while not result_userBal:
        db = await aiosqlite.connect(bank, timeout=10)
        cursor = await db.cursor()
        USER_ID = user.id
        await cursor.execute(f"SELECT user_id FROM main WHERE user_id={USER_ID}")
        result_userID = await cursor.fetchone()
        if not result_userID:
            await new_account(user)
        else:
            await cursor.execute(f"SELECT winloss FROM main WHERE user_id={USER_ID}")
            result_userBal = await cursor.fetchone()
            await cursor.close()
            await db.close()
            return result_userBal[0]


# update winloss, expects only one letter, anything else will do nothing
async def update_winloss(user, wl):
    if len(wl) > 1:  # idiot proofing
        return
    db = await aiosqlite.connect(bank, timeout=10)
    cursor = await db.cursor()
    USER_ID = user.id
    current = str(await get_winloss(user))
    if len(current) >= 20:
        current = current[1:]
    current = current + wl
    await cursor.execute(
        f'UPDATE main SET winloss = "{current}" WHERE user_id={USER_ID}'
    )
    await db.commit()
    await cursor.close()
    await db.close()


# returns X,X,X,X,etc... as str
async def formatted_winloss(user):
    current = await get_winloss(user)
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
    with open(file_path, "r") as f:
        maps = [line.rstrip() for line in f.readlines()]
        item = rd.choice(maps)
        return item


# get specific map
async def get_item(item):
    file_path = "maps/maps.txt"
    if os.path.exists(file_path):
        with open(file_path, encoding="utf-8") as f:
            maps = [line.rstrip() for line in f.readlines()]
            for thing in maps:
                if item in thing:
                    return thing
    else:
        return None


def moneyfy(amount):
    try:
        # Check if amount is None or not a string or number
        if amount is None:
            return 0

        # Try converting directly to float then to int
        try:
            return int(float(amount))
        except ValueError:
            pass  # If it fails, move on to the string handling part

        # String handling for suffixes
        negative = False
        if str(amount)[0] == "-":
            amount = str(amount)[1:]
            negative = True

        temp = re.compile(r"((?:\d*\.)?\d+)([a-zA-Z]+)")
        match = temp.match(str(amount))
        if match:
            res = match.groups()
            multi_by = 1  # Start with a multiplier of 1
            for letter in res[1]:
                if letter == "h":
                    multi_by *= 1e2
                elif letter == "k":
                    multi_by *= 1e3
                elif letter == "m":
                    multi_by *= 1e6
                elif letter == "b":
                    multi_by *= 1e9
                elif letter == "t":
                    multi_by *= 1e12
                elif letter == "q":
                    multi_by *= 1e15
                elif letter == "Q":
                    multi_by *= 1e18
                else:
                    multi_by *= 1
            total = float(res[0]) * multi_by
            if negative:
                total = -total
            return int(total)
    except Exception as e:
        # Catch any unexpected errors and bark about them
        print(f"Caught an unexpected error: {e}")
        return 0

    # If amount doesn't match any pattern, return 0
    return 0


def unmoneyfy(amount):  # converts int to string, so 1,000 to 1k
    if isinstance(amount, str):
        amount = amount.strip(",")
        amount = int(amount)
    if (amount % 1000000000000000) == 0:
        return f"{int(amount/1000000000000000)}q"
    if (amount % 1000000000000) == 0:
        return f"{int(amount/1000000000000)}t"
    if (amount % 1000000000) == 0:
        return f"{int(amount/1000000000)}b"
    if (amount % 1000000) == 0:
        return f"{int(amount/1000000)}m"
    if (amount % 1000) == 0:
        return f"{int(amount/1000)}k"
    return amount


def formatMoneyForEndUser(amount):
    if type(unmoneyfy(amount)) is int:
        return mf.commafy(amount)
    else:
        return unmoneyfy(amount)


async def get_investment(user):
    result_userBal = None
    while not result_userBal:
        db = await aiosqlite.connect(bank, timeout=10)
        cursor = await db.cursor()
        USER_ID = user.id
        await cursor.execute(f"SELECT user_id FROM main WHERE user_id={USER_ID}")
        result_userID = await cursor.fetchone()
        if not result_userID:
            await new_account(user)
        else:
            await cursor.execute(f"SELECT invested FROM main WHERE user_id={USER_ID}")
            result_userBal = await cursor.fetchone()
            await cursor.close()
            await db.close()
            return result_userBal[0]


async def add_investment(user, amount):
    db = await aiosqlite.connect(bank, timeout=10)
    cursor = await db.cursor()
    USER_ID = user.id
    await cursor.execute(
        f"UPDATE main SET invested = invested + {amount} WHERE user_id={USER_ID}"
    )
    await db.commit()
    await cursor.close()
    await db.close()


async def log_prestiege(user, pres):
    async with aiosqlite.connect(bank) as db:
        async with db.cursor() as cursor:
            await cursor.execute(
                f"SELECT user_id FROM prestiege WHERE user_id = {user.id}"
            )
            exists = await cursor.fetchone()
            if not exists:
                await cursor.execute(
                    f"INSERT INTO prestiege(user_id, pres1, pres2, pres3, pres4, pres5) values({user.id}, 0, 0, 0, 0, 0)"
                )
            await cursor.execute(
                f"UPDATE prestiege SET pres{pres} = pres{pres} + 1 WHERE user_id = {user.id}"
            )
        await db.commit()


async def get_prestiege(user):
    async with aiosqlite.connect(bank) as db:
        async with db.cursor() as cursor:
            await cursor.execute(
                f"SELECT user_id FROM prestiege WHERE user_id = {user.id}"
            )
            exists = await cursor.fetchone()
            if exists is None:
                return None
            await cursor.execute(f"SELECT * FROM prestiege WHERE user_id = {user.id}")
            results = await cursor.fetchone()
            return [results[2], results[3], results[4], results[5], results[6]]
