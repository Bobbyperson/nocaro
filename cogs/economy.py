# top 10 ancient texts undecipherable by humans
import asyncio
import datetime
import io
import math
import os
import random as rd
import sys
import time
import tomllib
import traceback
from collections import Counter
from typing import ClassVar

import anyio
import asyncpg
import discord
import matplotlib.pyplot as plt
import pyttsx3
from discord import FFmpegPCMAudio
from discord.ext import commands, menus, tasks
from discord.ui import Button, View
from matplotlib.dates import DateFormatter
from matplotlib.ticker import FuncFormatter
from PIL import Image, ImageDraw, ImageFont
from pydub import AudioSegment
from sqlalchemy import Integer, cast, delete, select, text

import models
import utils.econfuncs as econ
import utils.miscfuncs as misc

with open("config.toml", "rb") as f:
    config = tomllib.load(f)


class InventorySource(menus.ListPageSource):
    def __init__(self, data):
        super().__init__(data, per_page=25)

    async def format_page(self, menu, entries):
        embed = discord.Embed(color=discord.Color.blurple())
        embed.description = "\n".join(entries)
        embed.set_footer(text=f"Page {menu.current_page + 1}/{self.get_max_pages()}")
        return embed

    @menus.button("\N{BLACK LEFT-POINTING TRIANGLE}")
    async def on_previous_page(self, payload):
        self.page -= 1
        if self.page < 0:
            self.page = 0
        await self.message.edit(embed=self.compose_embed())

    @menus.button("\N{BLACK RIGHT-POINTING TRIANGLE}")
    async def on_next_page(self, payload):
        self.page += 1
        if self.page > len(self.source) // 25:
            self.page = len(self.source) // 25
        await self.message.edit(embed=self.compose_embed())


class MineButton(discord.ui.Button):
    def __init__(self, is_mine, chance):
        super().__init__(emoji="❓", style=discord.ButtonStyle.primary)
        self.is_mine = is_mine
        self.chance = chance

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.view.user:
            return
        self.disabled = True
        if self.is_mine:
            self.emoji = "💣"
            self.style = discord.ButtonStyle.red
            for child in self.view.children:
                child.disabled = True
                if isinstance(child, MineButton):
                    if child.is_mine:
                        child.emoji = "💣"
                    else:
                        child.emoji = "💰"
            await interaction.response.edit_message(
                content=f"# Mines!\n💥 Game Over! Potential earnings lost: {econ.unmoneyfy(self.view.money_earned)}",
                view=self.view,
            )
            self.view.money_earned = 0
            self.view.stop()
        else:
            self.emoji = "💰"
            self.style = discord.ButtonStyle.green
            fraction = 1 / self.chance
            self.view.successful_clicks += 1
            self.view.money_earned += self.view.bet * fraction
            # TODO
            # self.view.money_earned = (self.view.bet / 1000) * (
            #     (2**self.view.successful_clicks)
            #     / ((self.chance / 2) / (self.view.successful_clicks))
            # )
            self.view.money_earned = round(self.view.money_earned, 2)
            await interaction.response.edit_message(
                content=f"# Mines!\nBouge Bucks earned: {econ.unmoneyfy(self.view.money_earned)}",
                view=self.view,
            )


class CashOutButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="", emoji="✅", style=discord.ButtonStyle.green)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.view.user:
            return
        for child in self.view.children:
            child.disabled = True
            if isinstance(child, MineButton):
                if child.is_mine:
                    child.emoji = "💣"
                else:
                    child.emoji = "💰"
        await interaction.response.edit_message(
            content=f"# Mines!\nYou cashed out! Total Bouge Bucks earned: {econ.unmoneyfy(self.view.money_earned)}",
            view=self.view,
        )
        self.view.stop()


class MinesView(discord.ui.View):
    def __init__(self, chance, bet, user):
        super().__init__()
        self.money_earned = 0
        self.message = None  # Will be set later
        self.bet = bet
        self.successful_clicks = 0
        self.timeout = 30
        self.timedout = False
        self.user = user

        for i in range(5):
            for j in range(5):
                if i == 0 and j == 0:
                    continue
                is_mine = rd.randint(1, chance) == 1
                button = MineButton(is_mine=is_mine, chance=chance)
                self.add_item(button)

        self.add_item(CashOutButton())

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
            if isinstance(child, MineButton):
                if child.is_mine:
                    child.emoji = "💣"
                else:
                    child.emoji = "💰"
        self.timedout = True
        self.stop()


class Card:
    def __init__(self, name, value, suit):
        self.name = name
        self.value = value
        self.suit = suit

    def __str__(self):
        return f"{self.name}{self.suit}"

    def get_color(self):
        if self.suit in ["♤", "♧"]:
            return "black"
        else:
            return "red"


class Deck:
    suits: ClassVar[list[str]] = ["♤", "♡", "♧", "♢"]

    def __init__(self):
        self.cards = []
        for suit in self.suits:
            self.cards.append(Card("A", 11, suit))
            self.cards.append(Card("2", 2, suit))
            self.cards.append(Card("3", 3, suit))
            self.cards.append(Card("4", 4, suit))
            self.cards.append(Card("5", 5, suit))
            self.cards.append(Card("6", 6, suit))
            self.cards.append(Card("7", 7, suit))
            self.cards.append(Card("8", 8, suit))
            self.cards.append(Card("9", 9, suit))
            self.cards.append(Card("10", 10, suit))
            self.cards.append(Card("J", 10, suit))
            self.cards.append(Card("Q", 10, suit))
            self.cards.append(Card("K", 10, suit))

    def draw(self):
        return self.cards.pop(0)

    def shuffle(self):
        rd.shuffle(self.cards)

    def debug(self):
        bruh = ""
        for card in self.cards:
            bruh += f"{card.name}|{card.suit},"
        return bruh


class Hand:
    def __init__(self, *args):
        self.stood = False
        self.cards = [arg for arg in args]

    def add_card(self, card: Card):
        self.cards.append(card)

    def get_value(self):
        value = 0
        for card in self.cards:
            value += card.value
        if value > 21:
            value = 0
            for card in self.cards:
                if card.name != "A":
                    value += card.value
            for card in self.cards:
                if card.name == "A":
                    if value + 11 > 21:
                        value += 1
                    else:
                        value += 11
            if value > 21:  # failsafe for a fuck ton of aces
                value = 0
                for card in self.cards:
                    if card.name == "A":
                        value += 1
                    else:
                        value += card.value
        return value

    def get_formatted_value(self):
        value = 0
        soft = False
        for card in self.cards:
            value += card.value
        if value > 21:
            value = 0
            for card in self.cards:
                if card.name != "A":
                    value += card.value
            for card in self.cards:
                if card.name == "A":
                    if value + 11 > 21:
                        value += 1
                    else:
                        value += 11
                        soft = True
            if value > 21:  # failsafe for a fuck ton of aces
                value = 0
                for card in self.cards:
                    if card.name == "A":
                        value += 1
                    else:
                        value += card.value
            if value > 21:
                return str(value)
            else:
                if soft:
                    return f"Soft {value}"
                return f"Hard {value}"
        if value == 21 and len(self.cards) == 2:
            return "Blackjack 21"
        for card in self.cards:
            if card.name == "A":
                return f"Soft {value}"
        return str(value)

    def remove_card(self, pos: int):
        return self.cards.pop(pos)

    def show(self):
        return ", ".join(f"{card.name}{card.suit}" for card in self.cards)


class Player:
    def __init__(self, hand: Hand):
        self.hands = [hand]

    def can_double(self, cost, total, hand_id):
        if (
            len(self.hands[hand_id].cards) == 2
            # and len(self.hands[0].cards) == 2
            and total > cost
        ):
            return True
        return False

    def can_split(self, cost, total, hand_id):
        if (
            len(self.hands[hand_id].cards) == 2
            and self.hands[hand_id].cards[0].value == self.hands[hand_id].cards[1].value
            and total > cost
        ):
            return True
        return False

    def split(self, hand_id, new_card, replacement_card):
        split_card = self.hands[hand_id].remove_card(1)
        self.hands[hand_id].add_card(replacement_card)
        self.hands.append(Hand(split_card, new_card))


class Dealer(Hand):
    def get_dealer_show_card(self):
        return self.cards[0]


class Economy(commands.Cog):
    """Main Gambling and Economy commands."""

    def __init__(self, client):
        self.client = client
        self.award_map.add_exception_type(asyncpg.PostgresConnectionError)
        self.award_map.start()

    def cog_unload(self):
        self.award_map.cancel()

    # create database if none exists
    @commands.Cog.listener()
    async def on_ready(self):
        print("Economy ready")

    @commands.hybrid_command(aliases=["graph", "timeline"])
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def history(
        self, ctx, user: discord.User | None = None, *, timeframe: str = "1 day"
    ):
        """Check your Bouge Buck history/trends."""
        if not user:
            user = ctx.author

        timeframe_args = timeframe.split()
        timeframe_seconds = misc.human_time_to_seconds(*timeframe_args)
        if timeframe_seconds == -1:
            return await ctx.send(
                "Invalid timeframe. Be sure you did not use numerical words."
            )

        current_balance = await econ.get_bal(user)
        async with ctx.typing():
            async with self.client.session as session:
                result = (
                    await session.scalars(
                        select(models.economy.History).where(
                            models.economy.History.user_id == user.id,
                            models.economy.History.time
                            > (int(time.time()) - timeframe_seconds),
                        )
                    )
                ).all()

            if not result:
                return await ctx.send(
                    f"No history found within the last {timeframe}, please try specifying a longer timeframe."
                )

            last_result_timestamp = result[-1].time

            x = []
            y = []

            balance = current_balance

            # Add the current balance as the starting point
            x.append(datetime.datetime.fromtimestamp(time.time()))
            y.append(balance)

            # Process transactions in reverse order to reconstruct balances
            for history in reversed(result):
                balance -= int(history.amount)
                x.append(datetime.datetime.fromtimestamp(history.time))
                y.append(balance)

            # Reverse the lists to have them in chronological order
            x.reverse()
            y.reverse()

            # Plotting
            plt.figure(figsize=(10, 5))
            plt.plot(x, y, marker=None)
            plt.xlabel("Time")
            plt.ylabel("Balance")
            plt.title(f"Bouge Buck Balance History for {user.display_name}")
            plt.grid(True)

            # Date formatting
            if int(time.time()) - last_result_timestamp < 60 * 60 * 24 + 1:
                date_format = DateFormatter("%Y-%m-%d %H:%M")
            elif int(time.time()) - last_result_timestamp < 60 * 60 * 24 * 30 + 1:
                date_format = DateFormatter("%Y-%m-%d")
            else:
                date_format = DateFormatter("%Y-%m")
            plt.gca().xaxis.set_major_formatter(date_format)
            plt.gcf().autofmt_xdate()

            # Format y-axis
            ax = plt.gca()
            ax.yaxis.set_major_formatter(
                FuncFormatter(lambda x, pos: econ.unmoneyfy(x))
            )

            plt.tight_layout()

            with io.BytesIO() as img:
                plt.savefig(img, format="png")
                img.seek(0)
                plt.close()

                await ctx.reply(
                    file=discord.File(fp=img, filename="history.png"),
                    content=f"{user.name}'s Bouge Buck history",
                )

    @commands.command(hidden=True)
    async def moneytest(self, ctx, amount):
        await ctx.send(misc.commafy(econ.moneyfy(amount)))

    @commands.hybrid_command()
    @commands.max_concurrency(1, per=commands.BucketType.guild, wait=False)
    async def bougegram(
        self, ctx, difficulty: str | None = None, bet: str | None = None
    ):
        """Typing game. VC required."""
        if isinstance(ctx.channel, discord.channel.DMChannel):
            await ctx.send("Command may not be used in a DM.")
            return
        bet = econ.moneyfy(bet)
        blacklisted = await misc.is_blacklisted(ctx.author.id)
        if blacklisted[0]:
            await ctx.send(
                "Either you or the person you invoked are blacklisted from this bot."
            )
            return
        if await econ.checkmax(ctx.author) is True:
            await ctx.send(
                "You attempt to play the best game but you can't, your body is too weak from the endless games. Maybe you should attempt to `,enterthecave`."
            )
            return
        if difficulty is None:
            await ctx.send(
                """**Welcome to bougegram!**
This is a game where you try to type a word the bot says within a certain amount of time.
To start, please choose a difficulty:
**Easy**: A toned down version for beginniners or those on phones.
**Normal**: The intended way to play the game.
**Hard**: Increased word length with decreased time to answer.
**Insane**: Hard on crack.
**Impossible**: For those who thought insane was easy. 100 rounds with long words and 0.5 seconds to respond to each.
Example command: `,bougegram normal 100`"""
            )
            return
        if difficulty.lower() not in ["easy", "normal", "hard", "insane", "impossible"]:
            await ctx.send("Not a valid difficulty!")
            return
        if bet > await econ.get_bal(ctx.author):
            await ctx.send("You don't have enough bouge bucks!")
            return
        if bet < 0:
            await ctx.send("You can't bet negative bouge bucks!")
            return

        def joingame(m):
            return m.content.lower() == "join" or m.content.lower() == "skip"

        def skipcheck(m):
            return m.content.lower() == "skip" and m.author in players

        async def faster(vc):
            await asyncio.sleep(1)
            vc.play(FFmpegPCMAudio("audio/faster.mp3"))
            while vc.is_playing():
                await asyncio.sleep(0.1)

        async def checkgame(
            singleplayer=False, players=[]
        ):  # True: continue game, False: end game
            if singleplayer and len(players) == 1:
                return True
            if len(players) == 1:
                return False
            if players != []:
                return True
            if players == []:
                return False
            return True  # catch all, probably not needed

        async def notify_loss(messages, w1a, players):
            player_pass = []
            for message in messages:
                if (
                    message.author in players
                    and message.content.lower() == w1a
                    and message.author not in player_pass
                ):
                    player_pass.append(message.author)  # add to win list

            def remove_duplicates_from_lists(list1, list2):
                return list(filter(lambda element: element not in list2, list1))
                # https://stackoverflow.com/a/65289081

            if len(players) > len(player_pass):
                playerstomsg = remove_duplicates_from_lists(players, player_pass)
            else:
                playerstomsg = remove_duplicates_from_lists(player_pass, players)
            msg_to_send = ""
            if len(players) == len(playerstomsg):
                await ctx.send(
                    f"Everyone got out on the same word! You each get {int(bet / len(players))} bouge bucks!"
                )
                for player in players:
                    await econ.update_amount(
                        player, int(bet / len(players)), False, "bougegram"
                    )
                    await econ.update_amount(player, -1 * bet, False, "bougegram")
            else:
                for player in playerstomsg:  # notify players
                    msg_to_send += f"{player.mention} got out on {w1a}!\n"
                    await econ.update_amount(player, -1 * bet, False, "bougegram")
                if msg_to_send != "":
                    await ctx.send(msg_to_send)
            return player_pass

        async def play_word(threshold=1000, min_length=3, max_length=5):
            w1 = rd.choice(words)
            w1a = w1.split(".")[1]
            wlc = int(w1.split(".")[0])
            # vc = await ctx.voice_client.connect()
            met_threshold = False
            while not met_threshold:
                if (
                    wlc <= threshold
                    and len(w1a) >= min_length
                    and len(w1a) <= max_length
                ):
                    met_threshold = True
                else:
                    w1 = rd.choice(words)
                    w1a = w1.split(".")[1]
                    wlc = int(w1.split(".")[0])
            vc.play(FFmpegPCMAudio(f"bougegram/{w1}"))
            while vc.is_playing():
                await asyncio.sleep(0.1)
            vc.play(FFmpegPCMAudio(f"bougegram/{w1}"))
            while vc.is_playing():
                await asyncio.sleep(0.1)
            return w1a

        words = os.listdir("bougegram/")
        user = ctx.author
        voice_status = user.voice
        players = [ctx.author]
        end_check = misc.get_unix() + 60
        if voice_status is None:
            await ctx.send("You need to be in a voice channel to play!")
            return
        start_msg = await ctx.reply(
            f"Starting a game of Bouge Gram on {difficulty} mode!!!! Type `join` to join! There is currently 1 player in the game. The current pot is {bet}! Starting <t:{end_check}:R>..."
        )
        voice_channel = user.voice.channel
        vc = await voice_channel.connect()
        engine = pyttsx3.init()
        engine.save_to_file(
            f"A bouge gram game is starting in {ctx.channel.name}! The difficulty is {difficulty} and the bet is {bet} bouge bucks! Go there and type join to join!",
            f"{ctx.channel.id}.mp3",
        )
        engine.runAndWait()
        sound1 = AudioSegment.from_file(f"{ctx.channel.id}.mp3", format="mp3")
        sound2 = AudioSegment.from_file("audio/madibanocaro.mp3", format="mp3")
        combined = sound1 + sound2
        combined.export(f"{voice_channel.id}.mp3", format="mp3")
        vc.play(FFmpegPCMAudio(f"{voice_channel.id}.mp3"))
        while misc.get_unix() < end_check:
            try:
                join_msg = await self.client.wait_for(
                    "message", check=joingame, timeout=1
                )
            except TimeoutError:
                continue
            if (
                join_msg is not None
                and join_msg.content.lower() == "skip"
                and join_msg.author == ctx.author
            ):
                break
            if join_msg.author in players and join_msg.content.lower() == "join":
                await join_msg.reply("You have already joined!")
            elif join_msg.content.lower() == "skip":
                await join_msg.reply("You cannot skip!")
            else:
                if await econ.get_bal(join_msg.author) < bet:
                    await join_msg.reply("You don't have enough bouge bucks!")
                else:
                    if await econ.checkmax(join_msg.author):
                        await ctx.send(
                            "You attempt to join the best game but you can't, your body is too weak from the endless games. Maybe you should attempt to `,enterthecave`."
                        )
                    else:
                        players.append(join_msg.author)
                        await join_msg.add_reaction("✅")
                        await start_msg.edit(
                            content=f"Starting a game of Bouge Gram on {difficulty} mode!!!! Type `join` to join! There are currently {len(players)} in the game. The current pot is {bet * len(players)}! Starting <t:{end_check}:R>..."
                        )
        await start_msg.edit(
            content="This game is very simple. Type the word before you hear this sound. The time to answer will shorten when you hear this sound. Last one standing wins. On your mark, get ready, go!"
        )
        try:
            vc.stop()
        except discord.errors.ClientException:
            pass
        singleplayer = False
        if len(players) == 1:
            singleplayer = True
        if voice_status is not None:
            voice_channel = user.voice.channel
            # vc = await voice_channel.connect()
            await asyncio.sleep(2)
            if singleplayer:
                vc.play(FFmpegPCMAudio("audio/singleplayer.WAV"))
                while vc.is_playing():
                    await asyncio.sleep(0.1)
                vc.play(FFmpegPCMAudio("audio/done.mp3"))
                while vc.is_playing():
                    await asyncio.sleep(0.1)
            else:
                vc.play(FFmpegPCMAudio("audio/start.mp3"))
                try:
                    skip_msg = await self.client.wait_for(
                        "message", check=skipcheck, timeout=20
                    )
                except TimeoutError:
                    skip_msg = None
                    while vc.is_playing():
                        await asyncio.sleep(0.1)
                # contrary to what you may think, this is not useless.
                if skip_msg is not None and skip_msg.content == "skip":
                    vc.stop()
                    await asyncio.sleep(0.1)
                    vc.play(FFmpegPCMAudio("audio/skip.wav"))
                    while vc.is_playing():
                        await asyncio.sleep(0.1)
                    vc.play(FFmpegPCMAudio("audio/done.mp3"))
                    while vc.is_playing():
                        await asyncio.sleep(0.1)

            async def play_round(
                time=5,
                plays=10,
                players=players,
                vc=vc,
                threshold=1000,
                min_length=3,
                max_length=5,
            ):
                for _ in range(plays):
                    if not await checkgame(singleplayer, players):
                        break
                    w1a = await play_word(threshold, min_length, max_length)
                    await asyncio.sleep(time)
                    # play done sound here
                    await ctx.send(w1a)
                    messages = list()
                    async for message in ctx.channel.history(limit=len(players * 5)):
                        messages.append(
                            message
                        )  # get messages, self.client.wait_for simply waits too much for that to work; possible rate limit
                    player_pass = []
                    player_pass = await notify_loss(messages, w1a, players)
                    players = player_pass  # update players
                    vc.play(FFmpegPCMAudio("audio/done.mp3"))
                    while vc.is_playing():
                        await asyncio.sleep(0.1)
                if await checkgame(singleplayer, players):
                    await faster(vc)
                return players

            match difficulty:
                case "easy":
                    seconds = [8, 5, 4, 2]
                    rounds = [8, 10, 15, 20]
                    freq = [1000, 3000, 5000, 10000]
                    min_length = [3, 4, 5, 6]
                    max_length = [5, 6, 7, 8]
                case "normal":
                    seconds = [5, 3, 2, 1]
                    rounds = [8, 10, 15, 20]
                    freq = [1000, 3000, 5000, 10000]
                    min_length = [3, 4, 5, 6]
                    max_length = [5, 6, 7, 8]
                case "hard":
                    seconds = [4, 3, 2, 1]
                    rounds = [10, 15, 20, 25]
                    freq = [5000, 5000, 5000, 10000]
                    min_length = [6, 7, 8, 9]
                    max_length = [10, 10, 11, 12]
                case "insane":
                    seconds = [3, 2, 1, 0.5]
                    rounds = [20, 20, 20, 20]
                    freq = [10000, 10000, 10000, 10000]
                    min_length = [8, 9, 10, 11]
                    max_length = [12, 12, 12, 12]
                case "impossible":
                    seconds = [0.5, 0.5, 0.5, 0.5]
                    rounds = [25, 25, 25, 25]
                    freq = [10000, 10000, 10000, 10000]
                    min_length = [6, 6, 6, 6]
                    max_length = [15, 15, 15, 15]
                case _:
                    seconds = [5, 3, 2, 1]
                    rounds = [8, 10, 15, 20]
                    freq = [1000, 3000, 5000, 10000]
                    min_length = [3, 4, 5, 6]
                    max_length = [5, 6, 7, 8]
            initial_players = players
            # level 1
            players = await play_round(
                seconds[0],
                rounds[0],
                players,
                vc,
                freq[0],
                min_length[0],
                max_length[0],
            )
            # level 2
            players = await play_round(
                seconds[1],
                rounds[1],
                players,
                vc,
                freq[1],
                min_length[1],
                max_length[1],
            )
            # level 3
            players = await play_round(
                seconds[2],
                rounds[2],
                players,
                vc,
                freq[2],
                min_length[2],
                max_length[2],
            )
            # level 4
            players = await play_round(
                seconds[3],
                rounds[3],
                players,
                vc,
                freq[3],
                min_length[3],
                max_length[3],
            )
            if len(players) == 1:
                await ctx.send(
                    f"{players[0].mention} has won the game! {players[0].mention} has earned {bet * len(initial_players)} bouge bucks!!!!!"
                )
                await econ.update_amount(
                    players[0], bet * len(initial_players), tracker_reason="bougegram"
                )
                vc.play(FFmpegPCMAudio("audio/victory.mp3"))
                while vc.is_playing():
                    await asyncio.sleep(0.1)
            elif players == [] and singleplayer:
                await ctx.send("End of practice!")
            elif players == []:
                await ctx.send("Everyone got out on the same word. Too bad!")
            elif players != []:
                win_msg = f"The following players have won the game! The total reward will be split evenly between them! Each player gets {int(round(bet / len(players), 0))}\n"
                for player in players:
                    await econ.update_amount(
                        player,
                        int(round((bet * initial_players) / len(players), 0)),
                        tracker_reason="bougegram",
                    )
                    win_msg += f"{player.mention} "
                await ctx.send(win_msg)
                vc.play(FFmpegPCMAudio("audio/victory.mp3"))
                while vc.is_playing():
                    await asyncio.sleep(0.1)
            await asyncio.sleep(1)
            vc.play(FFmpegPCMAudio("audio/end.mp3"))
            while vc.is_playing():
                await asyncio.sleep(0.1)
            await vc.disconnect()
            os.remove(f"{ctx.channel.id}.mp3")
            os.remove(f"{voice_channel.id}.mp3")

    @commands.hybrid_command(aliases=["wl"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def winloss(self, ctx, member: discord.Member = None):
        """Check the amount of games you've won and lost."""
        if not member:
            member = ctx.author
        winloss = await econ.formatted_winloss(member)
        good = "".join(winloss.split(", "))
        await ctx.send(f"{member}'s winloss: {good}")

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        chance = rd.randint(1, 35)
        if chance != 1:
            return
        blacklisted = await misc.is_blacklisted(ctx.author.id)
        if blacklisted[0]:
            return

        def check_yes(moosage):
            return (
                moosage.author == ctx.author
                and moosage.channel == ctx.channel
                and moosage.content.lower() in ["yes", "no"]
            )

        def check_wallet(moosage):
            return (
                moosage.author == ctx.author
                and moosage.channel == ctx.channel
                and moosage.content.lower() in ["turn in", "keep"]
            )

        def check_offer(moosage):
            if moosage.author == ctx.author and moosage.channel == ctx.channel:
                if moosage.content.lower() == "deny":
                    return True
                try:
                    econ.moneyfy(moosage.content)
                    return True
                except ValueError:
                    return False
            return False

        async def peppy_say(msg):
            await misc.send_webhook(
                ctx=ctx,
                name="Peppy",
                avatar="https://bleach.my-ey.es/7FW3uUo.png",
                message=msg,
            )

        async def mrekk_say(msg):
            await misc.send_webhook(
                ctx=ctx,
                name="Mrekk",
                avatar="https://wolf.girlsare.life/4jVQKJZ.png",
                message=msg,
            )

        if ctx.command not in [
            self.client.get_command("blackjack"),
            self.client.get_command("slots"),
            self.client.get_command("doubleornothing"),
            self.client.get_command("quickdraw"),
            self.client.get_command("shareorsteal"),
            self.client.get_command("bougegram"),
            self.client.get_command("map"),
            self.client.get_command("daily"),
            self.client.get_command("unbox"),
            self.client.get_command("balance"),
            self.client.get_command("poker"),
            self.client.get_command("dealornodeal"),
            self.client.get_command("steal"),
            self.client.get_command("mines"),
            self.client.get_command("horserace"),
            self.client.get_command("coinflip"),
        ]:
            return
        try:
            webhooks = await ctx.channel.webhooks()
            if webhooks:
                webhook = webhooks[0]
            else:
                webhook = await ctx.channel.create_webhook(
                    name="Nocaro_NPC", reason="TEEHEE"
                )
        except (discord.errors.Forbidden, discord.errors.HTTPException, AttributeError):
            return
        if await econ.checkmax(ctx.author):
            return
        event = rd.randint(1, 4)
        bal = await econ.get_bal(ctx.author)
        per = rd.randint(1, 15) / 100
        if event == 1:
            if bal > 1000:
                amnt = int(bal * per)
            else:
                amnt = 100
            await peppy_say(
                f"{ctx.author.mention}! I need your help! \nCould you please give me {misc.commafy(amnt)} bouge bucks to finish my next map? I'll give you some of the earnings when I'm done. (**yes**/**no**)"
            )
            try:
                moosage = await self.client.wait_for(
                    "message", check=check_yes, timeout=30
                )
            except TimeoutError:
                await peppy_say(
                    f"{ctx.author.mention}! What a shame... I guess I'll just have to finish my map without you. <:POUT:847472552393179182>"
                )
                return
            if moosage.content.lower() == "yes":
                await econ.update_amount(
                    ctx.author, (-1 * amnt), tracker_reason="event"
                )
                await peppy_say(f"{ctx.author.mention}! Thank you! I'll be back soon!")
                await asyncio.sleep(rd.randint(120, 180))
                if rd.randint(1, 3) != 1:
                    await peppy_say(
                        f"{ctx.author.mention}! I'm back! My map is a banger! Here's your cut of the profit (**{misc.commafy(int(amnt * 2.1))} bouge bucks**). Maybe next time I'll ask you for an osu lazer investment.",
                    )
                    await econ.update_amount(
                        ctx.author, int(amnt * 2.1), tracker_reason="event"
                    )
                else:
                    await peppy_say(
                        f"{ctx.author.mention}! I'm back! My map fucking sucked! I've gone bankrupt so I can't really give you your bouge bucks back. Maybe next time I'll ask you for an osu lazer investment.",
                    )
            elif moosage.content.lower() == "no":
                await peppy_say(
                    f"{ctx.author.mention}! What a shame... I guess I'll just have to finish my map without you. <:POUT:847472552393179182>"
                )
            # await webhook.delete()
        elif event == 2:
            if bal > 10000:
                amnt = int(bal * per)
            else:
                amnt = 1000
            await webhook.send(
                content=f"{ctx.author.mention}! Hey I found a wallet with {misc.commafy(amnt)} bouge bucks in it, should we turn it in or keep it? (**turn in**, **keep**)",
                username="Peppy",
                avatar_url="https://bleach.my-ey.es/7FW3uUo.png",
            )
            try:
                moosage = await self.client.wait_for(
                    "message", check=check_wallet, timeout=30
                )
            except TimeoutError:
                await webhook.send(
                    content=f"{ctx.author.mention} uhhhh ok I guess I'll keep it for myself...",
                    username="Peppy",
                    avatar_url="https://bleach.my-ey.es/7FW3uUo.png",
                )
                return
            if moosage.content.lower() == "turn in":
                await webhook.send(
                    content=f"{ctx.author.mention} Ok, I'll go turn it in.",
                    username="Peppy",
                    avatar_url="https://bleach.my-ey.es/7FW3uUo.png",
                )
                await asyncio.sleep(rd.randint(120, 180))
                if rd.randint(1, 2) == 1:
                    await webhook.send(
                        content=f"Hey {ctx.author.mention} is that you? The Division of Returning Cash Holdings (DORCH) said you turned in my wallet. When I got it back I bet it all on slots and got the jackpot! I wanted to come and reward your honesty, because if it weren't for you I wouldn't have won. Here's **{misc.commafy(int(amnt * 2.25))}** bouge bucks.",
                        username="Mrekk",
                        avatar_url="https://wolf.girlsare.life/4jVQKJZ.png",
                    )
                    await econ.update_amount(
                        ctx.author, int(amnt * 2.25), tracker_reason="event"
                    )
                    return
                else:
                    await webhook.send(
                        content=f"Hey {ctx.author.mention} is that you? The Division of Returning Cash Holdings (DORCH) said you turned in my wallet. When I got it back I bet it all on slots and lost it all. Thank you for your honesty.",
                        username="Mrekk",
                        avatar_url="https://wolf.girlsare.life/4jVQKJZ.png",
                    )
                    return
            if moosage.content.lower() == "keep":
                await webhook.send(
                    content=f"{ctx.author.mention} Ok, here it is.",
                    username="Peppy",
                    avatar_url="https://bleach.my-ey.es/7FW3uUo.png",
                )
                await econ.update_amount(ctx.author, amnt, tracker_reason="event")
                if rd.randint(1, 4) == 1:
                    await asyncio.sleep(rd.randint(120, 180))
                    await webhook.send(
                        content=f"Hey {ctx.author.mention}! You're the bastard that took my wallet!",
                        username="Mrekk",
                        avatar_url="https://wolf.girlsare.life/4jVQKJZ.png",
                    )
                    await asyncio.sleep(3)
                    await ctx.channel.send(
                        f"Before you can even react, he takes his bouge bucks back, plus a little extra, and then runs away. (You lose {misc.commafy(int(amnt * 1.25))} bouge bucks.)"
                    )
                    await econ.update_amount(
                        ctx.author, int(amnt * -1.25), tracker_reason="event"
                    )
        elif event == 3:
            amnt = int(bal * per) if bal > 1000 else 100
            last_offer = amnt
            scam = rd.randint(0, 3)
            minimum_sell = int(amnt // (2 * rd.random() + 1))
            true_value = int(amnt // (1.25 * rd.random() + 1))
            decrease_amount = 0.05
            sold = False
            await peppy_say(
                f"Hey {ctx.author.mention}, I bought this tournament badge a while back but I don't want it anymore. It's been appraised at {misc.commafy(amnt)} $BB. How much will you give me for it? (Type an offer or say deny)"
            )
            while not sold:
                try:
                    moosage = await self.client.wait_for(
                        "message", check=check_offer, timeout=30
                    )
                except TimeoutError:
                    await peppy_say(
                        f"{ctx.author.mention}! Fine. I'll sell it to someone else."
                    )
                    return
                if moosage.content.lower() == "deny":
                    await peppy_say("Your loss.")
                    return
                offer = econ.moneyfy(moosage.content)
                if offer >= minimum_sell and offer <= bal:
                    sold = True
                    await peppy_say("Sold! Enjoy.")
                    await econ.update_amount(
                        ctx.author, -1 * offer, tracker_reason="event"
                    )
                elif offer < minimum_sell:
                    if minimum_sell > last_offer:
                        await peppy_say("You're ridiculous, nevermind.")
                        return
                    last_offer = int(last_offer * (1 - decrease_amount))
                    await peppy_say(
                        f"Really? Can't you give me a little bit more? How about {misc.commafy(last_offer)}. (Type a new offer or deny)"
                    )
            await asyncio.sleep(rd.randint(120, 180))
            await mrekk_say(
                f"{ctx.author.mention} Wait.... Let me see that tournament badge you have there..."
            )
            await asyncio.sleep(3)
            if scam == 1:
                await mrekk_say("Why do you have a fake ass tournament badge?")
            else:
                await mrekk_say(
                    f"I simply must buy that tournament badge, how's **{misc.commafy(true_value)} $BB** sound? Good? Great! Thanks."
                )
                await econ.update_amount(ctx.author, true_value, tracker_reason="event")
                await asyncio.sleep(2)
                await ctx.send(
                    "Before you can react, he swipes the badge away and scuttles off grinning to himself."
                )
        elif event == 4:
            amnt = int(bal * per) if bal > 1000 else 100
            payout = amnt * rd.randint(8, 20)
            cost = amnt * rd.randint(1, 2)
            await peppy_say(
                f"{ctx.author.mention} Hey, I bought this lottery ticket, but I don't want it anymore. I bought it for {misc.commafy(cost * 2)} but I'll sell it to you for **{misc.commafy(cost)}**. The lottery payout is **{misc.commafy(payout)}**, do you want it? (**Yes**, **No**)"
            )

            try:
                moosage = await self.client.wait_for(
                    "message", check=check_yes, timeout=30
                )
            except TimeoutError:
                await peppy_say(
                    f"{ctx.author.mention}! Nevermind I guess I'll keep it."
                )
                return
            if moosage.content.lower() == "yes":
                await econ.update_amount(ctx.author, -1 * cost, tracker_reason="event")
                await peppy_say("Ok, here you go.")
                await asyncio.sleep(rd.randint(120, 180))
                low_number = rd.randint(10000, 99989)
                winning = low_number + rd.randint(1, 10)
                chosen = low_number + rd.randint(1, 10)
                await ctx.send(
                    f"The lottery is now closed! And the winning number is.... **{winning}**!"
                )
                await asyncio.sleep(2)
                await ctx.send(
                    f"{ctx.author.mention} You look down and check your ticket... **{chosen}**."
                )
                await asyncio.sleep(2)
                if chosen == winning:
                    await ctx.send(
                        f"Congratulations! You've won the lottery! Here's your prize of **{misc.commafy(payout)}**!"
                    )
                    await econ.update_amount(ctx.author, payout, tracker_reason="event")
            elif moosage.content.lower() == "no":
                await peppy_say(
                    f"{ctx.author.mention}! Nevermind I guess I'll keep it."
                )
                await asyncio.sleep(rd.randint(120, 180))
                low_number = rd.randint(10000, 99989)
                winning = low_number + rd.randint(1, 10)
                chosen = low_number + rd.randint(1, 10)
                await ctx.send(
                    f"The lottery is now closed! And the winning number is.... **{winning}**!"
                )
                await asyncio.sleep(2)
                if chosen == winning:
                    await peppy_say(
                        f"Hey {ctx.author.mention}! Good thing you didn't take that ticket! I just won!"
                    )
                else:
                    await peppy_say("aw man, wish i was able to sell that ticket")

    # silly
    @commands.command(hidden=True)
    @commands.is_owner()
    async def rig(self, ctx, game, onoff):
        await ctx.send(f"Rigging {game} set to {onoff}")

    @commands.command(aliases=["rtb"])
    async def ridethebus(self, ctx, bet: str | None = None):
        if bet is None:
            await ctx.send("You need to specify a bet!")
            return
        if await econ.checkmax(ctx.author):
            await ctx.send(
                "You attempt to ride the bus but you can't, your body is too weak from the endless games. Maybe you should attempt to `,enterthecave`."
            )
            return
        bet = econ.moneyfy(bet)
        if bet < 0:
            await ctx.send("You can't bet negative bouge bucks!")
            return
        if bet > await econ.get_bal(ctx.author):
            await ctx.send("You don't have enough bouge bucks!")
            return
        deck = Deck()
        deck.shuffle()
        cards = [deck.draw(), deck.draw(), deck.draw(), deck.draw()]
        for card in cards:
            match card.name:
                case "J":
                    card.value = 11
                case "Q":
                    card.value = 12
                case "K":
                    card.value = 13
                case "A":
                    card.value = 14
        await econ.update_amount(ctx.author, -1 * bet, tracker_reason="ridethebus")
        await ctx.send("For double your bet, **red** or **black**?")
        try:
            msg = await self.client.wait_for(
                "message",
                check=lambda m: m.author == ctx.author
                and m.channel == ctx.channel
                and m.content
                and m.content in ["red", "black", "r", "b"],
                timeout=30,
            )
        except TimeoutError:
            await ctx.send("You took too long! I'm keeping your bouge bucks.")
            await econ.update_winloss(ctx.author, "l")
            return
        if msg.content == "r":
            msg.content = "red"
        if msg.content == "b":
            msg.content = "black"
        if msg.content == cards[0].get_color():
            await ctx.send(
                f"Cards: {cards[0]!s}\nCorrect! For triple your bouge bucks, will the next card be **higher**, **lower**, or would you like to **cash out**?"
            )
        else:
            await ctx.send(
                f"Cards: {cards[0]!s}\nIncorrect! You lose {misc.commafy(bet)} bouge bucks."
            )
            await econ.update_winloss(ctx.author, "l")
            return
        try:
            msg = await self.client.wait_for(
                "message",
                check=lambda m: m.author == ctx.author
                and m.channel == ctx.channel
                and m.content
                and m.content in ["higher", "lower", "cash out", "h", "l", "c"],
                timeout=30,
            )
        except TimeoutError:
            await ctx.send("You took too long! I'm keeping your bouge bucks.")
            await econ.update_winloss(ctx.author, "l")
            return
        correct = "higher" if cards[0].value <= cards[1].value else "lower"
        if msg.content == "h":
            msg.content = "higher"
        if msg.content == "l":
            msg.content = "lower"
        if msg.content == "c":
            msg.content = "cash out"
        if msg.content == "cash out":
            await ctx.send(f"You cashed out with {misc.commafy(bet * 2)} bouge bucks!")
            await econ.update_amount(ctx.author, bet * 2, tracker_reason="ridethebus")
            await econ.update_winloss(ctx.author, "w")
            return
        if msg.content == correct:
            await ctx.send(
                f"Cards: {cards[0]!s}, {cards[1]!s}\nCorrect! For quadruple your bouge bucks, will the next card be **in**, **out**, or would you like to **cash out**?"
            )
        else:
            await ctx.send(
                f"Cards: {cards[0]!s}, {cards[1]!s}\nIncorrect! You lose {misc.commafy(bet)} bouge bucks."
            )
            await econ.update_winloss(ctx.author, "l")
            return
        try:
            msg = await self.client.wait_for(
                "message",
                check=lambda m: m.author == ctx.author
                and m.channel == ctx.channel
                and m.content
                and m.content in ["in", "out", "cash out", "i", "o", "c"],
                timeout=30,
            )
        except TimeoutError:
            await ctx.send("You took too long! I'm keeping your bouge bucks.")
            await econ.update_winloss(ctx.author, "l")
            return
        if cards[0].value >= cards[1].value:
            if cards[2].value <= cards[0].value and cards[2].value >= cards[1].value:
                correct = "in"
            else:
                correct = "out"
        else:
            if cards[2].value >= cards[0].value and cards[2].value <= cards[1].value:
                correct = "in"
            else:
                correct = "out"
        if msg.content == "i":
            msg.content = "in"
        if msg.content == "o":
            msg.content = "out"
        if msg.content == "c":
            msg.content = "cash out"
        if msg.content == "cash out":
            await ctx.send(f"You cashed out with {misc.commafy(bet * 3)} bouge bucks!")
            await econ.update_amount(ctx.author, bet * 3, tracker_reason="ridethebus")
            await econ.update_winloss(ctx.author, "w")
            return
        if msg.content == correct:
            await ctx.send(
                f"Cards: {cards[0]!s}, {cards[1]!s}, {cards[2]!s}\nCorrect! For twenty times your bet, what is the suit of the next card? (or cash out)"
            )
        else:
            await ctx.send(
                f"Cards: {cards[0]!s}, {cards[1]!s}, {cards[2]!s}\nIncorrect! You lose {misc.commafy(bet)} bouge bucks."
            )
            await econ.update_winloss(ctx.author, "l")
            return
        try:
            msg = await self.client.wait_for(
                "message",
                check=lambda m: m.author == ctx.author
                and m.channel == ctx.channel
                and m.content
                and m.content
                in ["hearts", "diamonds", "clubs", "spades", "cash out", "c"],
                timeout=30,
            )
        except TimeoutError:
            await ctx.send("You took too long! I'm keeping your bouge bucks.")
            await econ.update_winloss(ctx.author, "l")
            return
        if msg.content == "c":
            msg.content = "cash out"
        if msg.content == "cash out":
            await ctx.send(f"You cashed out with {misc.commafy(bet * 4)} bouge bucks!")
            await econ.update_amount(ctx.author, bet * 4, tracker_reason="ridethebus")
            await econ.update_winloss(ctx.author, "w")
            return
        match cards[3].suit:
            case "♤":
                suit = "spades"
            case "♡":
                suit = "hearts"
            case "♢":
                suit = "diamonds"
            case "♧":
                suit = "clubs"
        if msg.content == suit:
            await ctx.send(
                f"Cards: {cards[0]!s}, {cards[1]!s}, {cards[2]!s}, {cards[3]!s}\nCorrect! You win **{misc.commafy(bet * 20)}** bouge bucks!"
            )
            await econ.update_amount(ctx.author, bet * 20, tracker_reason="ridethebus")
            await econ.update_winloss(ctx.author, "b")
        else:
            await ctx.send(
                f"Cards: {cards[0]!s}, {cards[1]!s}, {cards[2]!s}, {cards[3]!s}\nIncorrect! You lose **{misc.commafy(bet)}** bouge bucks."
            )
            await econ.update_winloss(ctx.author, "l")

    @commands.hybrid_command()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def unbox(self, ctx, amount: int = 1):
        """Use a banana to unbox a map."""
        banana = await econ.get_banana(ctx.author)
        blacklisted = await misc.is_blacklisted(ctx.author.id)
        if blacklisted[0]:
            await ctx.send("You are blacklisted from this bot!")
            return
        if amount < 1:
            await ctx.send(
                "i am going to claw my way down your throat and rip out your very soul"
            )
            return
        if banana < amount:
            await ctx.send("You don't have enough bouge bananas to unbox!")
            return
        if amount > 5:
            await ctx.send("5 maximum!")
            return
        full_message = "You just unboxed:\n"
        for _ in range(amount):
            item = await econ.get_random_item()
            item_id = item.split("|")[0]
            just_name = item.split("|")[1]
            await econ.add_item(ctx.author, item_id)
            full_message += f"`{just_name}`!\nhttps://assets.ppy.sh/beatmaps/{item_id}/covers/cover@2x.jpg\n"
        await econ.update_banana(ctx.author, -1 * amount)
        unbox_msg = await ctx.reply(f"Unboxing {amount} maps...")
        await asyncio.sleep(3)
        await unbox_msg.edit(content=full_message)

    @commands.hybrid_command()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def tradein(
        self,
        ctx,
        map1: str | None = None,
        map2: str | None = None,
        map3: str | None = None,
        map4: str | None = None,
        map5: str | None = None,
    ):
        """Trade-in 5 maps for 1 banana."""
        blacklisted = await misc.is_blacklisted(ctx.author.id)
        if blacklisted[0]:
            await ctx.send(
                "Either you or the person you invoked are blacklisted from this bot."
            )
            return
        """Trade in 5 maps for 1 banana."""
        if map1 is None or map2 is None or map3 is None or map4 is None or map5 is None:
            await ctx.send("You did not specify a map! You must specify 5.")
            return
        user_maps = await econ.get_inv(ctx.author)
        maps_to_delete = [map1, map2, map3, map4, map5]
        # check if any duplicates
        if len(maps_to_delete) != len(set(maps_to_delete)):
            await ctx.send("You cannot trade in duplicates!")
            return
        for map in maps_to_delete:
            if map not in user_maps:
                await ctx.send(f"You do not own {map}!")
                return
        for map in maps_to_delete:
            await econ.remove_item(ctx.author, map)
        await ctx.send("Tradein successful.")
        await econ.update_banana(ctx.author, 1)

    @commands.hybrid_command(aliases=["levelup", "prestiege"])
    @commands.cooldown(1, 43200, commands.BucketType.user)
    async def bbtobananapipeline(self, ctx):
        """Prestiege to earn bouge bananas."""
        blacklisted = await misc.is_blacklisted(ctx.author.id)
        if blacklisted[0]:
            await ctx.send("You are blacklisted from this bot.")
            return

        def check(moosage):
            return (
                moosage.author == ctx.author
                and moosage.channel == ctx.channel
                and moosage.content.lower() in ["yes", "no"]
            )

        bal = await econ.get_bal(ctx.author)
        level = await econ.get_level(ctx.author)
        reqamnt = 20000 + (1000 * (level + 1))
        earn = math.ceil(
            (
                math.log(bal / 6000, 10)
                + (2 * math.log(bal / 6000, 10) - 1)
                + math.sqrt(bal / 35000)
            )
            / 1.15
        )
        if bal < reqamnt:
            await ctx.send(
                f"Not enough bouge bucks to prestige, you need {misc.commafy(reqamnt)}!"
            )
            ctx.command.reset_cooldown(ctx)
            return
        await ctx.reply(
            f"If you prestige, you'll lose all of your bouge bucks (**{misc.commafy(bal)}**), you'll earn **{earn} bouge bananas**, and you will become **level {level + 1}**. Are you absolutely sure you want to prestige? (**yes**/**no**)"
        )
        try:
            msg = await self.client.wait_for(
                "message", check=check, timeout=15
            )  # 15 seconds to reply
        except TimeoutError:
            await ctx.send("Timeout...")
            return
        if msg.content.lower() == "yes":
            await econ.update_amount(
                ctx.author, -1 * bal, False, tracker_reason="prestige"
            )
            await econ.update_banana(ctx.author, earn)
            await econ.update_level(ctx.author, 1)
            await ctx.send(
                f"You are now level {level + 1}, you have earned {earn} bouge bananas, and you have lost all of your bouge bucks!"
            )
            return
        if msg.content.lower() == "no":
            await ctx.send("<:WTF:871245957168246835>")
            ctx.command.reset_cooldown(ctx)

    @commands.hybrid_command()
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    async def trade(self, ctx, member: discord.Member = None):
        """Trade with another user."""
        if await econ.checkmax(ctx.author):
            await ctx.send(
                "You attempt to trade but you can't, your body is too weak from the endless games. Maybe you should attempt to `,enterthecave`."
            )
            return
        if member is None:
            await ctx.send("You need to specify a member to trade with!")
            return
        blacklisted = await misc.is_blacklisted(ctx.author.id, member.id)
        if blacklisted[0]:
            await ctx.send(
                "Either you or the person you invoked are blacklisted from this bot."
            )
            return
        prestiege = await econ.get_prestiege(ctx.author)
        if prestiege and prestiege[4]:
            await ctx.send("You cannot trade $BB with this person.")
        prestiege = await econ.get_prestiege(ctx.author)
        if prestiege and prestiege[4]:
            await ctx.send("You cannot trade $BB.")
        if await econ.checkmax(member):
            await ctx.send("You cannot trade with this person. They have work to do.")
            return
        if member == ctx.author:
            await ctx.send("You can't trade with yourself!")
            return
        if member.bot:
            await ctx.send("You can't trade with a bot!")
            return

        authorbal = await econ.get_bal(ctx.author)
        invitedbal = await econ.get_bal(member)
        authorbananas = await econ.get_banana(ctx.author)
        invitedbananas = await econ.get_banana(member)
        authorinv = await econ.get_inv(ctx.author)
        invitedinv = await econ.get_inv(member)

        def authorcheck(msg):
            args = msg.content.split("|")
            if len(args) == 3:
                try:
                    bucks = int(args[0])
                    bananas = int(args[1])
                except ValueError:
                    return False
                if bucks < 0 or bananas < 0:
                    return False
                if bucks > 10_000_000_000:
                    return False
                if bucks > authorbal or bananas > authorbananas:
                    return False
                if args[2] == "None":
                    return True
                maps = args[2].split(" ")
                for map in maps:
                    try:
                        int(map)
                    except ValueError:
                        return False
                for map in maps:
                    if map not in authorinv:
                        return False
                if msg.author == ctx.author and msg.channel == ctx.channel:
                    return True
            return False

        def invitedcheck(msg):
            args = msg.content.split("|")
            if len(args) == 3:
                try:
                    bucks = int(args[0])
                    bananas = int(args[1])
                except ValueError:
                    return False
                if bucks < 0 or bananas < 0:
                    return False
                if bucks > 10_000_000_000:
                    return False
                if bucks > invitedbal or bananas > invitedbananas:
                    return False
                if args[2] == "None":
                    return True
                maps = args[2].split(" ")
                for map in maps:
                    try:
                        int(map)
                    except ValueError:
                        return False
                for map in maps:
                    if map not in invitedinv:
                        return False
                if msg.author == ctx.author and msg.channel == ctx.channel:
                    return True
            return False

        await ctx.send(
            "Ok listen up you better input this right or we're gonna have big problems.\nPlease type the amount of bouge bucks, bananas, and maps you would like to give away in THIS FUCKING FORMAT:\n`bucks|bananas|maps` or`100|5|123456 654321` (if you don't want to trade maps, type None instead of map ids)\nAlso there is a 10 billion bouge buck limit, please message the bot to arrange a trade for more than this"
        )
        try:
            response1 = await self.client.wait_for(
                "message", check=authorcheck, timeout=60
            )
        except TimeoutError:
            await ctx.reply("Timeout, cancelling...")
            return None
        args1 = response1.content.split("|")
        await ctx.send(
            "ok awesome do the same shit again but for what the other person will be giving you"
        )
        try:
            response2 = await self.client.wait_for(
                "message", check=invitedcheck, timeout=60
            )
        except TimeoutError:
            await ctx.reply("Timeout, cancelling...")
            return None
        args2 = response2.content.split("|")
        await ctx.send(
            f"{member.mention} will be getting {args1[0]} $BB, {args1[1]} bananas, and the following maps: {args1[2]}\n{ctx.author.mention} will be getting {args2[0]} $BB, {args2[1]} bananas, and the following maps: {args2[2]}"
        )
        await asyncio.sleep(1)
        await ctx.send(f"{ctx.author.mention} please type `confirm`")
        try:
            await self.client.wait_for(
                "message",
                check=lambda msg: msg.author == ctx.author and msg.content == "confirm",
                timeout=60,
            )
        except TimeoutError:
            await ctx.reply("Timeout, cancelling...")
            return None
        await ctx.send(f"{member.mention} please type `confirm`")
        try:
            await self.client.wait_for(
                "message",
                check=lambda msg: msg.author == member and msg.content == "confirm",
                timeout=60,
            )
        except TimeoutError:
            await ctx.reply("Timeout, cancelling...")
            return None

        await econ.update_amount(
            ctx.author, -1 * int(args1[0]), False, tracker_reason="trade"
        )
        await econ.update_amount(
            member, -1 * int(args2[0]), False, tracker_reason="trade"
        )
        await econ.update_amount(
            ctx.author, int(args2[0]), False, tracker_reason="trade"
        )
        await econ.update_amount(member, int(args1[0]), False, tracker_reason="trade")
        await econ.update_banana(ctx.author, -1 * int(args1[1]))
        await econ.update_banana(member, -1 * int(args2[1]))
        await econ.update_banana(ctx.author, int(args2[1]))
        await econ.update_banana(member, int(args1[1]))
        if args1[2] != "None":
            for map in args1[2].split(" "):
                await econ.remove_item(ctx.author, map)
                await econ.add_item(member, map)
        if args2[2] != "None":
            for map in args2[2].split(" "):
                await econ.remove_item(member, map)
                await econ.add_item(ctx.author, map)
        await ctx.send("Trade successful!")

    @commands.hybrid_command(aliases=["inv"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def inventory(self, ctx, member: discord.Member = None):
        """Check your inventory."""
        if not member:
            member = ctx.author
        blacklisted = await misc.is_blacklisted(ctx.author.id, member.id)
        if blacklisted[0]:
            await ctx.send(
                "Either you or the person you invoked are blacklisted from this bot."
            )
            return
        inventory = await econ.get_inv(member)
        if not inventory:
            await ctx.send("You have no items in your inventory.")
            return

        items = {}
        for name in inventory:
            item = await econ.get_item(name)
            if item in items:
                items[item] += 1
            else:
                items[item] = 1

        # Sort items by count descending and then by item name
        formatted_items = sorted(
            [f"x{count} | {item}" for item, count in items.items()],
            key=lambda x: (
                -int(x.split("x")[1].split(" |")[0]),
                x.split("|")[-1].strip(),
            ),
        )

        pages = menus.MenuPages(
            source=InventorySource(formatted_items), clear_reactions_after=True
        )
        await pages.start(ctx)

    @commands.hybrid_command()
    @commands.cooldown(1, 1, commands.BucketType.user)
    async def mapinfo(self, ctx, id: str | None = None):
        """Check a map's info."""
        if not id:
            await ctx.send("Please specify an ID.")
            return
        data = await econ.get_item(id)
        if data is not None:
            cool_id = data.split("|")[0]
            await ctx.reply(
                f"`{data}`!\nhttps://assets.ppy.sh/beatmaps/{cool_id}/covers/cover@2x.jpg"
            )
        else:
            await ctx.send("Unknown item!")

    @commands.command(aliases=["spl"], hidden=True)
    @commands.is_owner()
    async def sql(self, ctx, command: str | None = None):
        if not command:
            await ctx.send("Please provide an SQL command to run.")
            return

        await ctx.send(f"Executing: {command}")

        try:
            async with self.client.session as session:
                result = await session.execute(text(command))
                if result.returns_rows:
                    result = result.all()
                else:
                    result = []

                await ctx.send(result)

                # Ask user if they want to commit the changes
                await ctx.send(
                    "Do you want to commit these changes? Reply with 'yes' or 'no'."
                )
                try:
                    msg = await self.client.wait_for(
                        "message",
                        check=lambda m: m.author == ctx.author
                        and m.channel == ctx.channel,
                        timeout=60,
                    )
                    if msg.content.lower() == "yes":
                        await session.commit()
                        await ctx.send("Changes committed!")
                    else:
                        await session.rollback()
                        await ctx.send("Changes rolled back.")
                except TimeoutError:
                    await session.rollback()
                    await ctx.send("Confirmation timeout. Changes rolled back.")

        except Exception as e:
            print(type(e))
            print(e)
            await ctx.send(f"Error: {e!s}")

        # Note: With the use of context managers, we don't need to manually close the db and cursor anymore.

    @commands.hybrid_command()
    @commands.cooldown(1, 1, commands.BucketType.user)
    async def delete(self, ctx, item: int | None = None):
        """Delete a map from your inventory."""
        inventory = econ.get_inv(ctx.author)
        if not item:
            await ctx.send("Choose an item to delete")
            return
        if item in inventory:
            await econ.remove_item(ctx.author, item)
            await ctx.send("Item removed")
        else:
            await ctx.send("You don't have that item")

    # meh, this is a bit of a mess, but it works
    @commands.hybrid_command()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def profile(self, ctx, member: discord.Member = None):
        """Check all of your stats."""
        if isinstance(ctx.channel, discord.channel.DMChannel):
            await ctx.send("Command may not be used in a DM.")
            return

        member = member or ctx.author
        blacklisted = await misc.is_blacklisted(ctx.author.id, member.id)
        if blacklisted[0]:
            await ctx.send(
                "Either you or the person you invoked are blacklisted from this bot."
            )
            return
        img = await self.generate_profile_image(member)

        with io.BytesIO() as image_binary:
            img.save(image_binary, "PNG")
            image_binary.seek(0)

            await ctx.send(
                file=discord.File(fp=image_binary, filename="profile.png"),
                content=f"{member}'s profile",
            )

    async def generate_profile_image(self, member: discord.Member):
        funny = rd.randint(1, 100)
        amount = await econ.get_bal(member)
        level = (
            sum(await econ.get_prestiege(member))
            if await econ.get_prestiege(member)
            else 0
        )
        bananas = await econ.get_banana(member)

        msg = f"{amount} bouge buck{'s' if amount != 1 else ''}"
        bmsg = f"{bananas} banana{'s' if bananas != 1 else ''}"
        lmsg = f"{level} level"

        img = Image.open("templates/profile.png")
        draw = ImageDraw.Draw(img)
        my_font = ImageFont.truetype("fonts/monbaiti.ttf", 48)
        if amount > 9_999_999_999:  # 9.9 billion
            my_font = ImageFont.truetype("fonts/monbaiti.ttf", 42)
        if amount > 999_999_999_999:  # 999.9 billion
            my_font = ImageFont.truetype("fonts/monbaiti.ttf", 36)

        if funny == 1:
            self.draw_text_centered(draw, msg, (500, 550, 190), my_font)
            self.draw_text_centered(draw, lmsg, (500, 550, -100), my_font)
            self.draw_text_centered(draw, bmsg, (500, 550, 230), my_font)
        else:
            self.draw_text_centered(draw, msg, (500, 550, 175), my_font)
            self.draw_text_centered(draw, lmsg, (500, 550, -240), my_font)
            self.draw_text_centered(draw, bmsg, (500, 550, 220), my_font)

        return img

    def draw_text_centered(self, draw, text, pos, font):
        wid, hig, y_offset = pos
        w, h = font.getbbox(text)[2:4]
        x = (wid - w) / 2
        y = (hig - h) / 2 + y_offset
        draw.text((x, y), text, fill="white", font=font)

    @commands.hybrid_command()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def level(self, ctx, member: discord.Member = None):
        """Check your level."""
        if isinstance(ctx.channel, discord.channel.DMChannel):
            await ctx.send("Command may not be used in a DM.")
            return
        if not member:
            member = ctx.author
        blacklisted = await misc.is_blacklisted(ctx.author.id, member.id)
        if blacklisted[0]:
            await ctx.send(
                "Either you or the person you invoked are blacklisted from this bot."
            )
            return
        level = (
            sum(await econ.get_prestiege(member))
            if await econ.get_prestiege(member)
            else 0
        )
        msg = f"level {level}"
        img = Image.open("templates/level.png")
        draw = ImageDraw.Draw(img)
        my_font = ImageFont.truetype("fonts/monbaiti.ttf", 48)
        w, h = my_font.getbbox(msg)[2:4]
        wid, hig = (500, 500)
        draw.text(((wid - w) / 2, (hig - h) / 2 + 150), msg, fill="white", font=my_font)
        with io.BytesIO() as image_binary:
            img.save(image_binary, "PNG")
            image_binary.seek(0)
            await ctx.send(
                file=discord.File(image_binary, "level.png"),
                content=f"{member}'s level",
            )

    @commands.hybrid_command()
    @commands.cooldown(1, 86400, commands.BucketType.user)
    async def daily(self, ctx):
        """Get bananas."""
        blacklisted = await misc.is_blacklisted(ctx.author.id)
        if blacklisted[0]:
            await ctx.send(
                "Either you or the person you invoked are blacklisted from this bot."
            )
            return
        bananas = rd.randint(2, 4)
        await econ.update_banana(ctx.author, bananas)
        await ctx.reply(f"You just got {bananas} bananas! Come back in 24 hours!")

    @commands.hybrid_command(aliases=["bananas"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def banana(self, ctx, member: discord.Member = None):
        """Check how many bananas you have."""
        if isinstance(ctx.channel, discord.channel.DMChannel):
            await ctx.send("Command may not be used in a DM.")
            return
        if not member:
            member = ctx.author
        blacklisted = await misc.is_blacklisted(ctx.author.id, member.id)
        if blacklisted[0]:
            await ctx.send(
                "Either you or the person you invoked are blacklisted from this bot."
            )
            return
        amount = await econ.get_banana(member)
        if amount == 1:
            msg = f"{amount} banana"
        else:
            msg = f"{amount} bananas"
        img = Image.open("templates/banana.png")
        draw = ImageDraw.Draw(img)
        my_font = ImageFont.truetype("fonts/monbaiti.ttf", 48)
        w, h = my_font.getbbox(msg)[2:4]
        funnymsg = [
            "awesome",
            "how",
            "gunga banana",
            "yoo",
            "hddt players will say its fake",
            "haters will say",
            "xarr",
            "i just ,daily'd",
            "monkey",
        ]
        funny = rd.randint(0, len(funnymsg) - 1)
        funny_msg = funnymsg[funny]
        small_font = ImageFont.truetype("fonts/monbaiti.ttf", 28)
        w2, h2 = small_font.getbbox(funny_msg)[2:4]
        wid, hig = (500, 500)
        draw.text(((wid - w) / 2, (hig - h) / 2 + 150), msg, fill="white", font=my_font)
        draw.text(
            ((wid - w2) / 2, (hig - h2) / 2 + 210),
            funny_msg,
            fill="white",
            font=small_font,
        )
        with io.BytesIO() as image_binary:
            img.save(image_binary, "PNG")
            image_binary.seek(0)
            await ctx.send(
                file=discord.File(image_binary, "banana.png"),
                content=f"{member}'s bananas",
            )

    # It sends a message with an image of the user's balance.
    @commands.hybrid_command(
        name="balance", aliases=["bal", "bank", "money", "bucks", "dosh", "wonga"]
    )
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def balance(self, ctx, member: discord.Member = None):
        """Check how many bouge bucks you have."""
        if isinstance(ctx.channel, discord.channel.DMChannel):
            await ctx.send("Command may not be used in a DM.")
            return
        if not member:
            member = ctx.author
        blacklisted = await misc.is_blacklisted(ctx.author.id, member.id)
        if blacklisted[0]:
            await ctx.send(
                "Either you or the person you invoked are blacklisted from this bot."
            )
            return
        amount = await econ.get_bal(member)
        img = Image.open("templates/balance.png")
        if member.id == 351048216348721155:  # wyit
            if amount == 1:
                await ctx.send(
                    file=discord.File(fp="templates/wyit.gif", filename="bal.gif"),
                    content=f"{member} has {misc.commafy(amount)} bogue buck",
                )
            else:
                await ctx.send(
                    file=discord.File(fp="templates/wyit.gif", filename="bal.gif"),
                    content=f"{member} has {misc.commafy(amount)} bouge bucks",
                )
            return
        if member.id == 263126803780993024:  # ralkinson
            if amount == 1:
                await ctx.send(
                    file=discord.File(fp="templates/ralkinson.png", filename="bal.png"),
                    content=f"{member} has {misc.commafy(amount)} bogue buck",
                )
            else:
                await ctx.send(
                    file=discord.File(fp="templates/ralkinson.png", filename="bal.png"),
                    content=f"{member} has {misc.commafy(amount)} bouge bucks",
                )
            return
        if member.id == 819235084917276682:  # ned
            if amount == 1:
                await ctx.send(
                    file=discord.File(fp="templates/ned.gif", filename="bal.gif"),
                    content=f"{member} has {misc.commafy(amount)} bogue buck",
                )
            else:
                await ctx.send(
                    file=discord.File(fp="templates/ned.gif", filename="bal.gif"),
                    content=f"{member} has {misc.commafy(amount)} bouge bucks",
                )
            return
        if member.id == 201553786974502912:  # karma
            img = Image.open("templates/karma.jpg")
        wid, hig = (500, 500)
        if amount == 1:
            msg = f"{amount} bouge buck"
        else:
            msg = f"{amount} bouge bucks"
        draw = ImageDraw.Draw(img)
        if member.id == 275336962930638848:
            my_font = ImageFont.truetype("fonts/monbaiti.ttf", 12)
        else:
            my_font = ImageFont.truetype("fonts/monbaiti.ttf", 48)
        if amount > 9_999_999_999:  # 9.9 billion
            my_font = ImageFont.truetype("fonts/monbaiti.ttf", 42)
        if amount > 999_999_999_999:  # 999.9 billion
            my_font = ImageFont.truetype("fonts/monbaiti.ttf", 36)
        w, h = my_font.getbbox(msg)[2:4]
        draw.text(((wid - w) / 2, (hig - h) / 2 + 140), msg, fill="white", font=my_font)
        if amount < 0:
            dumb = ImageFont.truetype("fonts/monbaiti.ttf", 92)
            w, h = dumb.getbbox("BANKRUPT")[2:4]
            xy = [(wid - w) / 2, (hig - h) / 2]
            if rd.randint(1, 10) == 1:
                misc.draw_rotated_text(img, 20, xy, "DUMBASS", "red", dumb)
            else:
                misc.draw_rotated_text(img, 20, xy, "BANKRUPT", "red", dumb)
            small_font = ImageFont.truetype("fonts/monbaiti.ttf", 28)
            w2, h2 = small_font.getbbox(",debtrelief")[2:4]
            draw.text(
                ((wid - w2) / 2, (hig - h2) / 2 + 210),
                ",debtrelief",
                fill="white",
                font=small_font,
            )
        if member.id == 201553786974502912:  # karma
            karma_font = ImageFont.truetype("fonts/monbaiti.ttf", 20)
            w3, h3 = karma_font.getbbox(
                "I broke the game and Austin is the worst bot developer ever"
            )[2:4]
            draw.text(
                ((wid - w3) / 2, (hig - h3) / 2 + 210),
                "I broke the game and Austin is the worst bot developer ever",
                fill="white",
                font=karma_font,
            )
        with io.BytesIO() as image_binary:
            img.save(image_binary, "PNG")
            image_binary.seek(0)
            await ctx.send(
                file=discord.File(fp=image_binary, filename="bal.png"),
                content=(
                    f"{member} has {misc.commafy(amount)} bogue buck" + "s"
                    if amount != 1
                    else ""
                ),
            )

    @commands.hybrid_command()
    @commands.cooldown(1, 72.7, commands.BucketType.user)
    async def map(self, ctx):
        """Map for bouge bucks"""
        if isinstance(ctx.channel, discord.channel.DMChannel):
            await ctx.send("Command may not be used in a DM.")
            return
        if await econ.checkmax(ctx.author):
            await ctx.send(
                "You attempt to map but you can't, your body is too weak from the endless games. Maybe you should attempt to `,enterthecave`."
            )
            return
        blacklisted = await misc.is_blacklisted(ctx.author.id)
        if blacklisted[0]:
            await ctx.send("You are blacklisted from this bot.")
            return
        user = ctx.author
        banger = rd.randint(1, 10)
        earnings = rd.randint(0, 100)
        bangerearn = rd.randint(100, 500)
        if banger == 1:
            await ctx.reply(
                f"you maped and it was a banger, you still didn't get any money but you got {bangerearn} bouge bucks!"
            )
            await econ.update_amount(user, bangerearn, tracker_reason="map")
            return
        if earnings == 0:
            await ctx.reply("your map was so bad you got nothing out of it.")
            return
        if earnings == 1:
            await ctx.reply(
                f"you maped for money but got {earnings!s} bouge buck instead."
            )
            await econ.update_amount(user, earnings, tracker_reason="map")
            return
        await ctx.reply(
            f"you maped for money but got {earnings!s} bouge bucks instead."
        )
        await econ.update_amount(user, earnings, tracker_reason="map")

    # uhhhh i fwuckwed up the ocmmand for hte billionth time... :WAAH: could you pwweettyyywww pweaseewewe fix the cooldown????
    @commands.hybrid_command(aliases=["rob"])
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def steal(self, ctx, member: discord.Member):
        """Steal up to 500 bouge bucks from someone."""
        user = ctx.author
        if isinstance(ctx.channel, discord.channel.DMChannel):
            await ctx.send("Command may not be used in a DM.")
            return
        if await econ.checkmax(ctx.author):
            await ctx.send(
                "You attempt to steal but you can't, your body is too weak from the endless games. Maybe you should attempt to `,enterthecave`."
            )
            return
        if await econ.checkmax(member):
            await ctx.send(
                f"You attempt to steal from {member.name}. As you approach, you notice the state they're in, a husk of their former self. Unnerved, you run away."
            )
            ctx.command.reset_cooldown(ctx)
            return
        blacklisted = await misc.is_blacklisted(ctx.author.id, member.id)
        if blacklisted[0]:
            await ctx.send(
                "Either you or the person you invoked are blacklisted from this bot."
            )
            return
        unix = int(round(time.time(), 0))
        current = await econ.get_immunity(member)
        currentauthor = await econ.get_immunity(ctx.author)
        if current and int(current) > unix:
            await ctx.reply(
                f"Sorry {member} still has protection for {await misc.human_time_duration(current - unix)}."
            )
            ctx.command.reset_cooldown(ctx)
            return
        if currentauthor and currentauthor > unix:
            await ctx.reply("You can't rob while under protection broooooo.")
            ctx.command.reset_cooldown(ctx)
            return
        if not member:
            await ctx.reply("No target specified!")
            ctx.command.reset_cooldown(ctx)
            return
        if member == ctx.author:
            await ctx.reply("you can't rob yourself bro")
            ctx.command.reset_cooldown(ctx)
            return
        user = ctx.author
        victim = member
        victimbucks = await econ.get_bal(victim)
        if victimbucks < 500:
            await ctx.reply("lmaooooo they're poor don't bother")
            ctx.command.reset_cooldown(ctx)
            return
        stealamnt = rd.randint(0, 500)
        fail = rd.randint(1, 10)
        gunga = rd.randint(1, 10)
        if fail == 1:
            await ctx.reply(
                f"{misc.clean_username(user.name)} tried robbing {member} but was caught by Ephemeral! {misc.clean_username(user.name)}"
                f" is in jail and cannot steal or be stolen from for 10 minutes."
            )
            await econ.update_immunity(user, unix + 600)
        else:
            if gunga == 1:
                stealamnt = stealamnt * 10
            await econ.update_amount(user, stealamnt, False, tracker_reason="stealing")
            await econ.update_amount(
                victim, -1 * stealamnt, False, tracker_reason="robbed"
            )
            await econ.update_immunity(victim, unix + 1800)
            await ctx.reply(
                f"{ctx.author} just robbed {stealamnt} bouge bucks from {victim}!!!"
            )
            try:
                await member.send(
                    f"{user} just stole {stealamnt} bouge bucks from you in {ctx.channel.mention}!!!"
                )
            except discord.Forbidden:
                await ctx.send(f"could not dm {victim}")

    @commands.hybrid_command()
    async def checkimmunity(self, ctx, member: discord.Member = None):
        """Check if someone has immunity."""
        if isinstance(ctx.channel, discord.channel.DMChannel):
            await ctx.send("Command may not be used in a DM.")
            return
        unix = int(round(time.time(), 0))
        if not member:
            member = ctx.author
        blacklisted = await misc.is_blacklisted(ctx.author.id, member.id)
        if blacklisted[0]:
            await ctx.send(
                "Either you or the person you invoked are blacklisted from this bot."
            )
            return
        current = await econ.get_immunity(member)
        if current > unix:
            await ctx.reply(
                f"{member} is immune for {await misc.human_time_duration(current - unix)}."
            )
        else:
            await ctx.reply(f"{member} is not immune.")

    # look i did the rewrite
    @commands.hybrid_command(aliases=["bj", "b", "blowjob", "bjrw"])
    @commands.max_concurrency(1, per=commands.BucketType.user, wait=False)
    async def blackjack(self, ctx, amountstr: str | None = None):
        """Blackjack with some special rules"""
        blacklisted = await misc.is_blacklisted(ctx.author.id)
        if blacklisted[0]:
            await ctx.send("You are blacklisted from this bot.")
            return
        if isinstance(ctx.channel, discord.channel.DMChannel):
            await ctx.send("Command may not be used in a DM.")
            return
        if await econ.checkmax(ctx.author):
            await ctx.send(
                "You attempt to gamble but you can't, your body is too weak from the endless games. Maybe you should attempt to `,enterthecave`."
            )
            return
        amount = econ.moneyfy(amountstr)
        if amount == 0:
            await ctx.reply(
                "**Blackjack Info:**\nIn blackjack, the goal of the game is to get as close to 21 as possible without "
                "going over.\nYour hand is being played against the Dealer, who will always hit until 17.\nEverytime "
                "you hit, a new card is added to your hand, Jacks, Queens, and Kings are worth 10, while Aces are "
                "worth 11 or 1 (whichever works).\nWhen you Stand, the Dealer's hand is revealed and your totals are "
                "compared. Whoever is higher without going over 21 wins.\n\nTo start playing, type `,blackjack` follow by the amount "
                "of bouge bucks you want to gamble."
            )
            return
        if amount < 0:
            await ctx.reply("nice try bro")
            return

        def check(moosage):
            return (
                moosage.author == ctx.author
                and moosage.channel == ctx.channel
                and moosage.content.lower()
                in ["hit", "stand", "h", "s", "double", "d", "split", "p", "sp"]
            )

        def yes_no_check(moosage):
            return (
                moosage.author == ctx.author
                and moosage.channel == ctx.channel
                and moosage.content.lower() in ["yes", "no", "y", "n"]
            )

        def ability_check(moosage):
            return (
                moosage.author == ctx.author
                and moosage.channel == ctx.channel
                and moosage.content.lower() in ["power", "advice", "p", "a"]
            )

        def power_check(moosage):
            return (
                moosage.author == ctx.author
                and moosage.channel == ctx.channel
                and moosage.content.lower()
                in ["new", "n", "7", "split", "s", "p", "sp"]
            )

        async def pippi_say(ctx, message):
            pippi_pfp = "https://i.pinimg.com/originals/ab/5d/c8/ab5dc81a2e25ba66dca961079340a3ca.jpg"
            await misc.send_webhook(
                ctx,
                "Pippi",
                pippi_pfp,
                message,
            )

        current = await econ.get_bal(ctx.author)
        if amount > current:
            await ctx.reply("bitch you broke as hell go do some `,map`ing ")
            return
        current -= amount

        deck = Deck()
        deck.shuffle()

        current_hand = 0
        dealer = Dealer(deck.draw(), deck.draw())
        player = Player(Hand(deck.draw(), deck.draw()))
        dealer_show_card = dealer.get_dealer_show_card()

        def get_options():
            options = "**Hit** | **Stand**"
            if player.can_split(amount, current, current_hand):
                options += " | **Split**"
            if player.can_double(amount, current, current_hand):
                options += " | **Double**"
            return options

        def get_player_hands():
            if len(player.hands) == 1:
                return f"You: **{player.hands[0].show()}** | **{player.hands[0].get_formatted_value()}**\n"
            else:
                hands = ""
                for i, hand in enumerate(player.hands):
                    hands += f"{i + 1} -> **{hand.show()}** | **{hand.get_formatted_value()}**\n"
                return hands

        async def score(hand: Hand, dealer: Dealer, double):
            reward = 0
            if len(hand.cards) >= 7 and hand.get_value() <= 21:
                await econ.update_winloss(ctx.author, "b")
                reward += amount * 100
                return (
                    reward,
                    f"You got 7 cards and didn't bust!!!! YOU GET 100X PAYOUT!!!! YOU JUST WON **{misc.commafy(amount * 100)}** BOUGE BUCKS!!!",
                )
            elif len(hand.cards) >= 5 and hand.get_value() <= 21:
                await econ.update_winloss(ctx.author, "w")
                if hand.get_value() == 21:
                    reward += amount * 2 * double
                    return (
                        reward,
                        f"You got 5 cards and didn't bust! You also got blackjack! You win due to 5 card charlie! You just won **{misc.commafy(amount * 2 * double)}** bouge bucks!",
                    )
                else:
                    reward += amount * double
                    return (
                        reward,
                        f"You got 5 cards and didn't bust! You win due to 5 card charlie! You just won **{misc.commafy(amount * double)}** bouge bucks!",
                    )
            elif hand.get_value() == 21:
                if hand.get_value() == 21 == dealer.get_value():
                    await econ.update_winloss(ctx.author, "t")
                    return (
                        reward,
                        f"**Push!** {format(amount, ',d')} bouge bucks returned.",
                    )
                reward += amount * 2 * double
                await econ.update_winloss(ctx.author, "b")
                return (
                    reward,
                    f"Blackjack! You get double payout! You won **{format(amount * 2 * double, ',d')}** bouge bucks!",
                )
            elif dealer.get_value() == 21:
                reward += amount * -1 * double
                await econ.update_winloss(ctx.author, "l")
                return (
                    reward,
                    f"Sorry, you lose. The dealer got a blackjack. You lost **{format(amount * double, ',d')}** bouge bucks.",
                )
            elif hand.get_value() > 21:
                reward += amount * -1 * double
                await econ.update_winloss(ctx.author, "l")
                return (
                    reward,
                    f"Sorry. You busted. You lost **{format(amount * double, ',d')}** bouge bucks.",
                )
            elif dealer.get_value() > 21:
                reward += amount * double
                await econ.update_winloss(ctx.author, "w")
                return (
                    reward,
                    f"Dealer busts. You won **{format(amount * double, ',d')}** bouge bucks!",
                )
            elif hand.get_value() < dealer.get_value():
                reward += amount * -1 * double
                await econ.update_winloss(ctx.author, "l")
                return (
                    reward,
                    f"Sorry. Your score isn't higher than the dealer. You lose **{format(amount * double, ',d')}** bouge bucks.",
                )
            elif hand.get_value() > dealer.get_value():
                reward += amount * double
                await econ.update_winloss(ctx.author, "w")
                return (
                    reward,
                    f"Congratulations. Your score is higher than the dealer. You win **{format(amount * double, ',d')}** bouge bucks.",
                )
            elif hand.get_value() == dealer.get_value():
                await econ.update_winloss(ctx.author, "t")
                return reward, "**Push!** Bouge bucks returned."
            else:
                return reward, "You should never see this message. :)"

        # async def get_scores(player: Player, dealer: Dealer, doubled: int):
        #     if len(player.hands) == 1:
        #         if doubled > 0:
        #             return await score(player.hands[0], dealer, 2)
        #         else:
        #             return await score(player.hands[0], dealer, 1)
        #     else:
        #         rewards = 0
        #         message = ""
        #         for hand in player.hands:
        #             if doubled > 0:
        #                 temp1, temp2 = await score(hand, dealer, 2)
        #             else:
        #                 temp1, temp2 = await score(hand, dealer, 1)
        #             rewards += temp1
        #             message += temp2
        #             message += "\n"
        #             # cannot += a tuple so i have to do this awfulness
        #         return rewards, message

        async def get_scores(player: Player, dealer: Dealer, doubled: list):
            rewards = 0
            message = ""
            for i, hand in enumerate(player.hands):
                if doubled[i]:
                    temp1, temp2 = await score(hand, dealer, 2)
                else:
                    temp1, temp2 = await score(hand, dealer, 1)
                rewards += temp1
                message += temp2
                message += "\n"
            return rewards, message

        betmsg = f"Bet: **{econ.unmoneyfy(amount)}** $BB"
        dealer_hand = f"Dealer: **{dealer_show_card.name}{dealer_show_card.suit}**"
        player_hand = get_player_hands()
        extra_info = ""
        options = get_options()
        main_msg = await ctx.reply(
            betmsg
            + "\n"
            + dealer_hand
            + "\n"
            + player_hand
            + extra_info
            + "\n"
            + options
        )

        async def update_game():
            await main_msg.edit(
                content=betmsg
                + "\n"
                + dealer_hand
                + "\n"
                + player_hand
                + extra_info
                + "\n"
                + options
            )

        # insurance
        if dealer_show_card.name == "A":
            options = "Insurance? **Yes** or **No**. It costs half your bet."
            await update_game()
            try:
                insurance = await self.client.wait_for(
                    "message", check=yes_no_check, timeout=25
                )
            except TimeoutError:
                await ctx.reply(
                    "You didn't respond in time! Assuming **No**. Continue playing normally."
                )
                insurance = None
                options = get_options()
            if insurance is not None and (
                insurance.content.lower() == "yes" or insurance.content.lower() == "y"
            ):
                await econ.update_amount(
                    ctx.author, -1 * (amount // 2), tracker_reason="blackjack"
                )
                if dealer.get_value() == 21:
                    if player.hands[0].get_value() < 21:
                        await ctx.reply(
                            "Dealer has blackjack! Your bouge bucks, including insurance cost, has been returned."
                        )
                        await econ.update_amount(
                            ctx.author,
                            (amount // 2) + amount,
                            tracker_reason="blackjack",
                        )
                        return
                    elif player.hands[0].get_value() == 21:
                        await ctx.reply(
                            f"Both you and the dealer have blackjack! You won {amount} bouge bucks!"
                        )
                        await econ.update_amount(
                            ctx.author, amount, tracker_reason="blackjack"
                        )
                        return
                else:
                    await ctx.reply(
                        "Dealer does not have blackjack, continue playing normally."
                    )
                    options = get_options()
        options = get_options()
        # end insurance
        split = False

        # start pippi
        pippi_chance = rd.randint(1, 50)
        if pippi_chance == 1:
            options = "Answer Pippi."
            await update_game()
            await pippi_say(
                ctx,
                "It looks like you're trying to play blackjack, would you like help with that?",
            )
            try:
                pippi_msg = await self.client.wait_for(
                    "message", check=yes_no_check, timeout=25
                )  # 15 seconds to reply
            except TimeoutError:
                pippi_msg = None
                await pippi_say(ctx, "Fuck you. I didn't want to help anyways.")
                options = get_options()
                await update_game()
            if pippi_msg is not None:
                if pippi_msg.content.lower() in ["yes", "y"]:
                    await pippi_say(
                        ctx,
                        "Alright, would you like some **advice** or a **power**?",
                    )
                    try:
                        pippi_msg = await self.client.wait_for(
                            "message", check=ability_check, timeout=25
                        )  # 15 seconds to reply
                    except TimeoutError:
                        pippi_msg = None
                        await pippi_say(
                            ctx,
                            "Ok, nevermind I guess.",
                        )
                        options = get_options()
                        await update_game()
                    if pippi_msg is not None:
                        if pippi_msg.content.lower() in ["advice", "a"]:
                            if rd.randint(1, 2) == 1:
                                await pippi_say(
                                    ctx,
                                    f"Ok, the next card is **{deck.cards[0].name}**.",
                                )
                            else:
                                await pippi_say(
                                    ctx,
                                    f"Ok, the dealer's hand is **{dealer.get_value()}**.",
                                )
                        if pippi_msg.content.lower() in ["power", "p"]:
                            await pippi_say(
                                ctx,
                                "Ok, would you like a **new** hand, add **7** to the dealer's hand, or **split** your current hand?",
                            )
                            try:
                                pippi_msg = await self.client.wait_for(
                                    "message", check=power_check, timeout=25
                                )  # 15 seconds to reply
                            except TimeoutError:
                                pippi_msg = None
                                await pippi_say(
                                    ctx,
                                    "Ok, nevermind I guess.",
                                )
                                options = get_options()
                                await update_game()
                            if pippi_msg is not None:
                                if pippi_msg.content.lower() in ["new", "n"]:
                                    player.hands[0].cards = [deck.draw(), deck.draw()]
                                    player_hand = get_player_hands()
                                    options = get_options()
                                    await update_game()
                                if pippi_msg.content.lower() == "7":
                                    for i, card in enumerate(deck.cards):
                                        if card.value == 7:
                                            seven_card = deck.cards.pop(i)
                                            dealer.add_card(
                                                seven_card
                                            )  # ensure actual card from deck and no duplicates
                                            break
                                    await pippi_say(ctx, "Ok, done.")
                                    options = get_options()
                                    await update_game()
                                if pippi_msg.content.lower() in [
                                    "split",
                                    "sp",
                                    "s",
                                    "p",
                                ]:
                                    player.split(current_hand, deck.draw(), deck.draw())
                                    split = True
                                    player_hand = get_player_hands()
                                    options = get_options()
                                    await update_game()
                                    await pippi_say(ctx, "Ok, done.")
                else:
                    if rd.randint(1, 5) == 1:
                        await pippi_say(
                            ctx,
                            "https://tenor.com/view/walter-white-walter-falling-breaking-bad-dm4uz3-gif-18078549 ",
                        )
                    else:
                        await pippi_say(ctx, "Alright then.")
                options = get_options()
                await update_game()
        # end pippi
        doubled = [False] * len(player.hands)
        # this is set to zero because you can double on multiple split hands
        done = False
        while not done:
            if split:
                if (
                    player.hands[current_hand].stood
                    and player.hands[current_hand] != player.hands[-1]
                ):
                    current_hand += 1
                extra_info = f"Hand {current_hand + 1}"

            await update_game()
            try:
                msg = await self.client.wait_for("message", check=check, timeout=25)
            except TimeoutError:
                await ctx.reply(
                    "Sorry, you didn't reply in time! Standing automatically."
                )
                while dealer.get_value() < 17:
                    dealer.add_card(deck.draw())
                dealer_hand = (
                    f"Dealer: **{dealer.show()}** | **{dealer.get_formatted_value()}**"
                )
                player_hand = get_player_hands()
                reward, options = await get_scores(player, dealer, doubled)
                await econ.update_amount(ctx.author, reward, tracker_reason="blackjack")
                await update_game()
                return

            if msg.content.lower() in ["hit", "h"]:
                player.hands[current_hand].add_card(deck.draw())
                if player.hands[current_hand].get_value() > 21:
                    player.hands[current_hand].stood = True
                player_hand = get_player_hands()
            elif msg.content.lower() in ["stand", "s"]:
                player.hands[current_hand].stood = True
            elif msg.content.lower() in ["split", "sp", "p"]:
                if player.can_split(amount, current, current_hand):
                    player.split(current_hand, deck.draw(), deck.draw())
                    doubled.append(False)  # Add False for new hand
                    split = True
                    current -= amount
                else:
                    await msg.reply("Forbidden!")
            elif msg.content.lower() in ["double", "d"]:
                if (
                    player.can_double(amount, current, current_hand)
                    and not doubled[current_hand]
                ):
                    doubled[current_hand] = True
                    current -= amount
                    player.hands[current_hand].add_card(deck.draw())
                    player.hands[current_hand].stood = True
                else:
                    await msg.reply("Forbidden!")
            if player.hands[-1].stood:
                done = True
            else:
                options = get_options()
            player_hand = get_player_hands()
        while dealer.get_value() < 17:
            dealer.add_card(deck.draw())
        dealer_hand = (
            f"Dealer: **{dealer.show()}** | **{dealer.get_formatted_value()}**"
        )
        player_hand = get_player_hands()
        reward, options = await get_scores(player, dealer, doubled)
        await econ.update_amount(ctx.author, reward, tracker_reason="blackjack")
        await update_game()

        current = await econ.get_bal(ctx.author)

        button = Button(
            label="Re-bet?",
            style=discord.ButtonStyle.green,
            emoji="🔁",
            disabled=(current < amount),
        )
        dbutton = Button(
            label="Double Bet?",
            style=discord.ButtonStyle.red,
            emoji="⚠️",
            disabled=(current < amount * 2),
        )
        hbutton = Button(
            label="Half Bet?",
            style=discord.ButtonStyle.grey,
            emoji="⬇️",
            disabled=(amount <= 1 or current <= amount // 2),
        )

        async def button_callback(interaction):
            if interaction.user == ctx.author:
                await interaction.response.edit_message(view=None)
                await ctx.invoke(self.client.get_command("blackjack"), amount)

        async def double_callback(interaction):
            if interaction.user == ctx.author:
                await interaction.response.edit_message(view=None)
                await ctx.invoke(self.client.get_command("blackjack"), amount * 2)

        async def half_callback(interaction):
            if interaction.user == ctx.author:
                await interaction.response.edit_message(view=None)
                await ctx.invoke(self.client.get_command("blackjack"), amount // 2)

        button.callback = button_callback
        dbutton.callback = double_callback
        hbutton.callback = half_callback
        view = View(timeout=15)
        view.add_item(button)
        view.add_item(dbutton)
        view.add_item(hbutton)
        await main_msg.edit(view=view)

    @commands.hybrid_command(aliases=["pay", "give", "g"])
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def gift(self, ctx, member: discord.Member = None, amount: str | None = None):
        """Gift someone bouge bucks"""
        amount = econ.moneyfy(amount)
        if isinstance(ctx.channel, discord.channel.DMChannel):
            await ctx.send("Command may not be used in a DM.")
            return
        if await econ.checkmax(ctx.author):
            await ctx.send(
                "You attempt to spread goodwill but you can't, your body is too weak from the endless games. Maybe you should attempt to `,enterthecave`."
            )
            return
        if await econ.checkmax(member):
            await ctx.send("You try to give bouge bucks, but their pockets are full.")
            return
        prestieges = await econ.get_prestiege(ctx.author)
        if prestieges and prestieges[3]:
            await ctx.send(
                "You try to gift the bouge bucks, but you physically cannot make yourself gift it."
            )
            return
        user_prestieges = await econ.get_prestiege(member)
        if user_prestieges and user_prestieges[3]:
            await ctx.send(
                "You try to hand over the bouge bucks, but as you approach them, you realize that this person might be better off without them."
            )
            return
        if member is None:
            await ctx.send("No target specified!")
            return
        if member == ctx.author:
            await ctx.send("you can't gift yourself bro")
            return
        if amount < 0:
            await ctx.send(
                "you can't abuse oversights in my code to steal someone's bouge bucks bro"
            )
            return
        if member.bot:
            await ctx.send("No droids!")
            return
        blacklisted = await misc.is_blacklisted(ctx.author.id, member.id)
        if blacklisted[0]:
            await ctx.send(
                "You or the person you invoked are blacklisted from this bot."
            )
            return
        gifteebal = await econ.get_bal(member)
        if gifteebal < 0:
            if amount > (gifteebal * -1) + 10_000_000_000:  # 10 trillion
                await ctx.send("Max gift is debt + ten billion!")
                return
        else:
            if amount > 10_000_000_000:
                await ctx.send("Max gift is ten billion!")
                return
        user = ctx.author
        giftee = member
        totalmoney = await econ.get_bal(user)
        if totalmoney < amount:
            await ctx.send("you can't gift more than you have bro")
            return
        await econ.update_amount(giftee, amount, False, tracker_reason="gifted")
        await econ.update_amount(user, -1 * amount, False, tracker_reason="gift")
        await ctx.send(f"{ctx.author} just gifted {amount} bouge bucks to {giftee}!!!")

    @commands.hybrid_command(aliases=["lb", "baltop"])
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def leaderboard(self, ctx):
        """View the leaderboard."""
        if isinstance(ctx.channel, discord.channel.DMChannel):
            await ctx.send("Command may not be used in a DM.")
            return
        async with self.client.session as session:
            rows = (
                await session.scalars(
                    select(models.economy.Main).order_by(
                        cast(models.economy.Main.balance, Integer).desc()
                    )
                )
            ).all()
        top_n = 10
        top_users = dict(
            sorted(
                ((row.user_ID, int(row.balance)) for row in rows),
                key=lambda kv: kv[1],
                reverse=True,
            )[:top_n]
        )

        embed = discord.Embed(
            title=f"Top {top_n} Bouge Buck Owners",
            color=discord.Color(0xFA43EE),
        )

        for rank, (user_id, balance) in enumerate(top_users.items(), start=1):
            try:
                username = await self.client.fetch_user(user_id)
            except discord.NotFound:
                username = "Unknown User"
            embed.add_field(
                name=f"{rank}. {username}",
                value=misc.commafy(balance),
                inline=False,
            )

        await ctx.send(embed=embed)

    @commands.hybrid_command(aliases=["slb", "sbaltop"])
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def serverleaderboard(self, ctx: commands.Context):
        """View the server-only leaderboard."""
        if isinstance(ctx.channel, discord.DMChannel):
            await ctx.send("Command may not be used in a DM.")
            return

        top_n = 10
        guild_member_ids: set[int] = {m.id for m in ctx.guild.members}

        async with self.client.session as session:
            rows = (
                await session.scalars(
                    select(models.economy.Main).order_by(
                        cast(models.economy.Main.balance, Integer).desc()
                    )
                )
            ).all()

        top_n = 10
        top_users = dict(
            sorted(
                (
                    (row.user_ID, int(row.balance))
                    for row in rows
                    if row.user_ID in guild_member_ids
                ),
                key=lambda kv: kv[1],
                reverse=True,
            )[:top_n]
        )

        embed = discord.Embed(
            title=f"Top {top_n} Bouge Buck Owners",
            color=discord.Color(0xFA43EE),
        )

        for rank, (user_id, balance) in enumerate(top_users.items(), start=1):
            member = self.client.get_user(user_id) or await self.client.fetch_user(
                user_id
            )
            embed.add_field(
                name=f"{rank}. {member}",
                value=misc.commafy(balance),
                inline=False,
            )

        await ctx.send(embed=embed)

    # @commands.command(aliases=["lolboard", "balbottom", "brokeboard", "bottomboard"])
    # async def lboard(self, ctx):
    #     """View the Lboard."""
    #     if isinstance(ctx.channel, discord.channel.DMChannel):
    #         await ctx.send("Command may not be used in a DM.")
    #         return
    #     amount = 10
    #     db = await aiosqlite.connect(bank, timeout=10)
    #     cursor = await db.cursor()
    #     await cursor.execute(f"SELECT * FROM main ORDER BY balance ASC")
    #     users = await cursor.fetchall()
    #     em = discord.Embed(
    #         title=f"Bottom {amount} Bouge Buck Owners", color=discord.Color(0xFA43EE)
    #     )
    #     index = 0
    #     for user in users:
    #         if index == amount:
    #             break
    #         if user[1] != 0:
    #             index += 1
    #             bal = misc.commafy(user[1])
    #             user_id = user[3]
    #             username = await self.client.fetch_user(user_id)
    #             em.add_field(name=f"{index}. {username}", value=f"{bal}", inline=False)
    #         else:
    #             index -= 1
    #     await ctx.send(embed=em)

    @commands.hybrid_command()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def immunity(self, ctx):
        """Buy immunity from being stolen from."""
        if isinstance(ctx.channel, discord.channel.DMChannel):
            await ctx.send("Command may not be used in a DM.")
            return
        if await econ.checkmax(ctx.author):
            await ctx.send(
                "You attempt to purchase immunity but you realize the uselessness of it. No one would dare approach you. Maybe you should attempt to `,enterthecave`."
            )
            return

        def check(mosage):
            return (
                mosage.author == ctx.author
                and mosage.channel == ctx.channel
                and mosage.content.lower() in ["yes"]
            )

        unix = int(round(time.time(), 0))

        user = ctx.author
        blacklisted = await misc.is_blacklisted(ctx.author.id)
        if blacklisted[0]:
            await ctx.send("You are blacklisted from this bot.")
            return
        totalmoney = await econ.get_bal(user)
        current = await econ.get_immunity(user)
        user_prestieges = await econ.get_prestiege(ctx.author)
        if user_prestieges and user_prestieges[3]:
            await ctx.reply("I pity the fool.")
            return
        if current > unix + 43200:
            await ctx.reply("You have immunity for over 12 hours bruh")
            return
        if totalmoney < 1000:
            await ctx.reply("You need at least 1000 bouge bucks to buy immunity")
            return
        cost = math.ceil(totalmoney * 0.1)
        await ctx.reply(
            f"Are you sure you want to spend 10% of your bouge bucks ({econ.unmoneyfy(cost)}) for immunity from stealing for 24 hours? "
            "Repond **Yes** or **No**"
        )
        try:
            msg = await self.client.wait_for(
                "message", check=check, timeout=15
            )  # 30 seconds to reply
        except TimeoutError:
            return
        if msg.content.lower() == "yes":
            if current > unix:
                await econ.update_amount(user, -1 * cost, tracker_reason="immunity")
                await econ.update_immunity(user, current + 86400)
                current = await econ.get_immunity(user)
                await ctx.reply(
                    f"You are now protected from theft for {await misc.human_time_duration(current - unix)}"
                )
            if current <= unix:
                await econ.update_amount(user, -1 * cost, tracker_reason="immunity")
                await econ.update_immunity(user, unix + 86400)
                await ctx.reply("You are now protected from theft for 24 hours")

    @commands.command(hidden=True)
    @commands.is_owner()
    async def agive(
        self, ctx, member: discord.Member = None, amount: str | None = None
    ):
        if not member or not amount:
            return await ctx.reply("idiot")
        amount = econ.moneyfy(amount)
        await econ.update_amount(member, amount, False, tracker_reason="agive")
        await ctx.reply(f"you gave {member} {amount} bouge bucks")

    @commands.command(hidden=True)
    @commands.is_owner()
    async def abanana(self, ctx, member: discord.Member = None, amount: int = 0):
        if not member or not amount:
            return await ctx.reply("idiot")
        await econ.update_banana(member, amount)
        await ctx.reply(f"you gave {member} {amount} bananas")

    @commands.hybrid_command(aliases=["don"])
    @commands.max_concurrency(1, per=commands.BucketType.user, wait=False)
    async def doubleornothing(self, ctx, amount: str | None = None):
        """Play a chance game to win bouge bucks."""
        if isinstance(ctx.channel, discord.channel.DMChannel):
            await ctx.send("Command may not be used in a DM.")
            return
        if await econ.checkmax(ctx.author):
            await ctx.send(
                "You attempt to gamble but you can't, your body is too weak from the endless games. Maybe you should attempt to `,enterthecave`."
            )
            return

        blacklisted = await misc.is_blacklisted(ctx.author.id)
        if blacklisted[0]:
            await ctx.send("You are blacklisted from this bot.")
            return

        def check(moosage):
            return (
                moosage.author == ctx.author
                and moosage.channel == ctx.channel
                and moosage.content.lower() in ["double", "cash out", "d", "c", "co"]
            )

        user = ctx.author
        if not amount:
            await ctx.reply(
                "**Double or Nothing**\n"
                "Everytime you type `double` the amount you bet will have a "
                "50% chance to instantly double or be lost completely\n"
                "You can cash out at any time\n"
                "If you don't respond in 15 seconds you will cash out automatically\n"
                "To begin, please re-run this command with a bet\n"
            )
            return
        amount = econ.moneyfy(amount)
        if amount < 1:
            await ctx.send("Please bet at least 1 bouge buck.")
            return
        totalcash = await econ.get_bal(user)
        # if totalcash < 10:
        #     await ctx.send("You're too poor go `,map`")
        #     return
        if totalcash < amount:
            await ctx.send("You're too poor go `,map`")
            return
        lose = False
        main_message = await ctx.reply(
            "Welcome to Double or Nothing:\n"
            f"Current pool: **{format(amount, ',d')}**\n"
            f"**1x**\n"
            f"Please type **double** or **cash out**."
        )
        multiplier = 1
        pool = amount
        doubled_once = False
        await econ.update_amount(user, -1 * amount, tracker_reason="doubleornothing")
        while not lose:
            try:
                msg = await self.client.wait_for(
                    "message", check=check, timeout=15
                )  # 30 seconds to reply
            except TimeoutError:
                await ctx.reply(
                    "Sorry, you didn't reply in time! Cashing out automatically."
                )
                await ctx.reply(f"You just won {format(pool, ',d')} bouge bucks!!!")
                await econ.update_amount(
                    user, pool, False, tracker_reason="doubleornothing"
                )
                return
            win = rd.randint(1, 2)
            if (
                msg.content.lower() == "cash out"
                or msg.content.lower() == "c"
                or msg.content.lower() == "co"
            ):
                if not doubled_once:
                    await ctx.reply("Please double at least once!")
                else:
                    await ctx.reply(f"You just won {format(pool, ',d')} bouge bucks!!!")
                    await econ.update_amount(
                        user, pool, tracker_reason="doubleornothing"
                    )
                    await econ.update_winloss(ctx.author, "w")
                    return
            if msg.content.lower() == "double" or msg.content.lower() == "d":
                doubled_once = True
                if win == 1:
                    multiplier += 1
                    increment = 2 ** (multiplier - 1)
                    pool = amount * increment
                    if multiplier == 10:
                        await ctx.reply(
                            f"**JACKPOT!!!** You get 10x payout! You just won **{format(pool * 10, ',d')} BOUGE BUCKS!!!**"
                        )
                        await econ.update_amount(
                            user, pool * 10, tracker_reason="doubleornothing"
                        )
                        await econ.update_winloss(ctx.author, "b")
                        return
                    await main_message.edit(
                        content=(
                            "Welcome to Double or Nothing:\n"
                            f"Current pool: **{format(pool, ',d')}**\n"
                            f"**{multiplier}x**\n"
                            f"Please type **double** or **cash out**."
                        )
                    )
                else:
                    await ctx.reply(
                        f"Bust! You lose {format(amount, ',d')} bouge bucks, and lost a potential {format(int(pool - amount), ',d')} bouge bucks"
                    )
                    await econ.update_winloss(ctx.author, "l")
                    lose = True

    @tasks.loop(seconds=60)
    async def award_map(self):
        for guild in self.client.guilds:
            for user in guild.members:
                if user.activity is not None and user.activity.name is not None:
                    if user.activity.name.lower() == "osu!":
                        try:
                            if (
                                user.activity.details is not None
                                and not await econ.checkmax(user)
                            ):
                                await econ.update_amount(
                                    user, 100, tracker_reason="idle map"
                                )
                        except:
                            return

    @commands.command(aliases=["fof"], hidden=True)
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    async def floporfire(self, ctx, amount: int = 0, bet: str | None = None):
        def check(moosage):
            return (
                moosage.author == ctx.author
                and moosage.channel == ctx.channel
                and moosage.content.lower() in ["yes", "no"]
            )

        if await econ.checkmax(ctx.author):
            await ctx.send(
                "You attempt to judge maps but you can't, your body is too weak from the endless games. Maybe you should attempt to `,enterthecave`."
            )
            return

        def cheek(moosage):
            return moosage.attachments and moosage.channel == game_channel

        blacklisted = await misc.is_blacklisted(ctx.author.id)
        if blacklisted[0]:
            await ctx.send("You are blacklisted from this bot.")
            return

        unix = int(round(time.time(), 0))
        user = ctx.author
        total_dosh = await econ.get_bal(user)
        if isinstance(ctx.channel, discord.channel.DMChannel):
            if amount == 0:
                await ctx.reply(
                    "**Welcome to Flop Or Fire!**\n"
                    "This game works by making a bet on whether a random pattern will be **fire** or a **flop**\n"
                    "olcode will post a random pattern in #flop-or-fire, and everyone else will vote on it.\n"
                    "They'll have 4 minutes to do so, and if they agree with your bet you will get double payout if you bet flop, or half payout if you vote fire.\n"
                    "Minimum bet is: 1k bouge bucks"
                    "\n To begin, please retype this command with an amount to gamble and your bet.\n"
                    "Example: `,floporfire 1000 fire`"
                )
                return
            if amount > total_dosh:
                await ctx.send("Not enough bouge bucks!")
                return
            if amount < 1000:
                await ctx.send("Minimum bet is 1000 bouge bucks.")
                return
            if not bet:
                await ctx.send("Please specify `flop` or `fire`")
                return
            if bet != "flop" and bet != "fire":
                await ctx.send("Please specify `flop` or `fire`")
                return
            async with await anyio.open_file("lastgame.txt") as f:
                last_game = await int(f.read())
            if last_game > unix:
                await ctx.send("A game is already in progress!")
                return
            if last_game < unix:
                await ctx.send(
                    f"Are you sure you want to gamble {amount} bouge bucks on {bet}? Please respond `yes` or `no`."
                )
                try:
                    msg = await self.client.wait_for(
                        "message", check=check, timeout=15
                    )  # 15 seconds to reply
                except TimeoutError:
                    await ctx.reply("You didn't respond in 15 seconds, cancelling.")
                    return
                if msg.content.lower() == "yes":
                    if last_game > unix:
                        await ctx.send("A game is already in progress!")
                        return
                    async with await anyio.open_file("lastgame.txt", "w") as f:
                        await f.write(str(unix + 1260))
                    await ctx.send("Starting game...")
                    game_channel = self.client.get_channel(962154552583401512)
                    await game_channel.send("mystery pattern")
                    try:
                        await self.client.wait_for(
                            "message", check=cheek, timeout=10
                        )  # 5 seconds to reply
                    except TimeoutError:
                        await ctx.reply("olcode is down, cancelling")
                        await game_channel.send(
                            "<:WTF:871245957168246835><:WTF:871245957168246835><:WTF:871245957168246835><:WTF:871245957168246835><:WTF:871245957168246835>"
                        )
                        return
                    fire = "🔥"
                    flop = "🗿"
                    await asyncio.sleep(1)
                    game_message = await game_channel.send(
                        f"Is this pattern {flop} or {fire}? Vote open for 20 minutes."
                    )
                    await game_message.add_reaction(flop)
                    await game_message.add_reaction(fire)
                    await asyncio.sleep(1200)
                    await game_channel.send("Vote over in 60 seconds.")
                    await asyncio.sleep(50)
                    await game_channel.send("Vote over in 10 seconds.")
                    await asyncio.sleep(10)
                    updated_game = await game_channel.fetch_message(game_message.id)
                    async for member in (
                        updated_game.reactions[0].users()
                        and updated_game.reactions[1].users()
                    ):
                        # from here you can do whatever you need with the member objects
                        reward = rd.randint(2, 250)
                        try:
                            if member == ctx.author:
                                await member.send(
                                    f"For voting on your own bet, you are penalized {int(round(amount / 10, 0))} bouge bucks"
                                )
                                await econ.update_amount(
                                    ctx.author,
                                    int(round(amount / 10, 0)),
                                    tracker_reason="floporfire",
                                )
                            if member != self.client.user and member != ctx.author:
                                await member.send(
                                    f"For voting on flop or fire, you get {reward} bouge bucks."
                                )
                                await econ.update_amount(
                                    member, reward, tracker_reason="floporfire"
                                )
                        except discord.Forbidden:
                            pass
                    fire_reactions = updated_game.reactions[1]
                    flop_reactions = updated_game.reactions[0]
                    if (flop_reactions.count + fire_reactions.count) > 4:
                        if flop_reactions.count == fire_reactions.count:
                            await game_channel.send(
                                f"The masses are **undecided**! **{user}** predicted **{bet}** and wagered **{amount}** bouge bucks."
                            )
                            await game_channel.send("reveal mapper")
                            return
                        elif (
                            flop_reactions.count > fire_reactions.count
                            and bet == "flop"
                        ):
                            await game_channel.send(
                                f"The masses vote that this pattern is a **flop**! **{user}** successfully predicted this and has won **{amount}** bouge bucks!!!"
                            )
                            await game_channel.send("reveal mapper")
                            await econ.update_amount(
                                user, amount, tracker_reason="floporfire"
                            )
                            return
                        elif (
                            flop_reactions.count < fire_reactions.count
                            and bet == "fire"
                        ):
                            await game_channel.send(
                                f"The masses vote that this pattern is **fire**! **{user}** successfully predicted this and has won **{amount}** bouge bucks!!!"
                            )
                            await game_channel.send("reveal mapper")
                            await econ.update_amount(
                                user, amount, tracker_reason="floporfire"
                            )
                            return
                        elif (
                            flop_reactions.count > fire_reactions.count
                            and bet == "fire"
                        ):
                            await game_channel.send(
                                f"The masses vote that this pattern is **flop**! **{user}** did not predict this and has lost **{amount}** bouge bucks!!!"
                            )
                            await game_channel.send("reveal mapper")
                            await econ.update_amount(
                                user, -1 * amount, tracker_reason="floporfire"
                            )
                            return
                        elif (
                            flop_reactions.count < fire_reactions.count
                            and bet == "flop"
                        ):
                            await game_channel.send(
                                f"The masses vote that this pattern is **fire**! **{user}** did not predict this and has lost **{amount}** bouge bucks!!!"
                            )
                            await game_channel.send("reveal mapper")
                            await econ.update_amount(
                                user, -1 * amount, tracker_reason="floporfire"
                            )
                            return

                    else:
                        await game_channel.send(
                            f"Not enough votes! **{user}** predicted **{bet}** and wagered **{amount}** bouge bucks"
                        )
                        await game_channel.send("reveal mapper")
                        return

                if msg.content.lower() == "no":
                    await ctx.send("Cancelling...")

        else:
            await ctx.reply(
                "This command may only be used in a DM."
            )  # easiest to read code 2012

    @commands.hybrid_command(aliases=["qd"])
    @commands.max_concurrency(1, per=commands.BucketType.channel, wait=False)
    async def quickdraw(self, ctx, member: discord.Member = None, amount: str = "0"):
        """Play a reaction based game against someone."""
        amount = econ.moneyfy(amount)
        async with await anyio.open_file("templates/words.txt") as file:
            all_text = await file.read()
            words = list(map(str, all_text.split()))
            word = rd.choice(words)
        if await econ.checkmax(ctx.author):
            await ctx.send(
                "You attempt to play an underappreciated game but you can't, your body is too weak from the endless games. Maybe you should attempt to `,enterthecave`."
            )
            return

        def check(moosage):
            return (
                moosage.channel == ctx.channel
                and moosage.author != ctx.author
                and moosage.content.lower() == "i accept"
            )

        def invited_give_bal_check(moosage):
            return (
                moosage.author == member
                and moosage.channel == ctx.channel
                and moosage.content.lower() == "i accept"
            )

        def check_game(moosage):
            return (
                moosage.channel == ctx.channel
                and moosage.content.lower() == str.lower(word)
            )

        if ctx.author == member:
            await ctx.send("I am going to blacklist you from the bot")
            return
        if amount < 0:
            await ctx.send("haha wow you can't bet negative bouge bucks")
            return
        if amount > await econ.get_bal(ctx.author):
            await ctx.send("Not enough bouge bucks!")
            return
        if amount == 0:
            await ctx.send(
                "**Welcome to quick draw!!!**\n"
                "The goal of this game is to beat the reaction times of your opponent.\n"
                "When the game starts, the bot will post a random word. Whoever types that word the fastest wins.\n"
                "The time it takes for the message to appear can be up to a full minute, so pay attention!\n"
                'The message will look like this: `@user1 @user2 DRAW! Type "superfluous" as quickly as possible!!!`\n'
                "To start, run this command again with a bet. Example: `,quickdraw 100`\n"
                "If you want to battle a specific person, ping someone at the end of it. Example: `quickdraw @opponent 100`\n"
                "More than two people are not supported because that sounds hawd >~<"
            )
            return
        blacklisted = await misc.is_blacklisted(member.id)
        if blacklisted[0]:
            await ctx.send(
                "You or the person you invoked are blacklisted from this bot."
            )
            return
        if not member:
            blacklisted = await misc.is_blacklisted(ctx.author.id)
            if blacklisted[0]:
                await ctx.send(
                    "You or the person you invoked are blacklisted from this bot."
                )
                return
            await ctx.send(
                f'{ctx.author} is challenging someone to a duel for {amount} bouge bucks!!! Respond with "I accept" to start the duel!'
            )
            try:
                msg = await self.client.wait_for(
                    "message", check=check, timeout=30
                )  # 30 seconds to reply
            except TimeoutError:
                await ctx.send("No one accepted your duel! Cancelling.")
            if msg.content.lower() == "i accept":
                if amount > await econ.get_bal(msg.author):
                    await ctx.send("Not enough bouge bucks!")
                    return
                await econ.update_amount(
                    ctx.author, -1 * amount, False, tracker_reason="quickdraw"
                )
                await econ.update_amount(
                    msg.author, -1 * amount, False, tracker_reason="quickdraw"
                )
                time_to_wait = rd.randint(3, 31)
                messages = [
                    "Don't blink...",
                    "Get ready...",
                    "Hope no one is spamming commands...",
                    f"The message will send between {time_to_wait - rd.randint(1, 5)} seconds and {time_to_wait + rd.randint(1, 5)} seconds...",
                    f"Somebody is about to lose {amount} bouge bucks...",
                    "Hope neither of you are too mad after this...",
                    "Remember guys, it's just a game...",
                    "I hope your WPM is at least 80...",
                    "Note to self: Don't drink tap water at Jerry Garcia's...",
                    "Typeingson...",
                    "Winner of this one gets booger bucks instead...",
                ]
                await ctx.send(
                    f"{ctx.author.mention} {msg.author.mention} {rd.choice(messages)}"
                )
                await asyncio.sleep(time_to_wait)
                await ctx.send(
                    f"`{time_to_wait}s` {ctx.author.mention} {msg.author.mention} DRAW! type `{word}`"
                )
                try:
                    msg2 = await self.client.wait_for(
                        "message", check=check_game, timeout=120
                    )
                except TimeoutError:
                    await ctx.send("you both suck, you both lose bouge bucks.")
                    return
                if msg2.content.lower() == str.lower(word):
                    await ctx.send(
                        f"{msg2.author} typed `{word}` first and won {amount} bouge bucks!!!"
                    )
                    await econ.update_amount(
                        msg2.author, amount * 2, tracker_reason="quickdraw"
                    )
                    return
        if member:
            if amount > await econ.get_bal(member):
                await ctx.send(f"{member} does not have enough to accept this duel")
                return
            await ctx.send(
                f'{ctx.author} is challenging {member} to a duel for {amount} bouge bucks! Respond with "I accept" to start the duel!'
            )

            try:
                msg = await self.client.wait_for(
                    "message", check=invited_give_bal_check, timeout=30
                )  # 30 seconds to reply
            except TimeoutError:
                await ctx.send(f"{member} did not accept your duel! Cancelling.")
            if msg.content.lower() == "i accept":
                await econ.update_amount(
                    ctx.author, -1 * amount, False, tracker_reason="quickdraw"
                )
                await econ.update_amount(
                    member, -1 * amount, False, tracker_reason="quickdraw"
                )
                time_to_wait = rd.randint(3, 31)
                messages = [
                    "Don't blink...",
                    "Get ready...",
                    "Hope no one is spamming commands...",
                    f"The message will send between {time_to_wait - rd.randint(1, 5)} seconds and {time_to_wait + rd.randint(1, 5)} seconds...",
                    f"Somebody is about to lose {amount} bouge bucks...",
                    "Hope neither of you are too mad after this...",
                    "Remember guys, it's just a game...",
                    "I hope your WPM is at least 80...",
                    "Note to self: Don't drink tap water at Jerry Garcia's...",
                    "Typeingson...",
                    "Winner of this one gets booger bucks instead...",
                ]
                await ctx.send(
                    f"{ctx.author.mention} {msg.author.mention} {rd.choice(messages)}"
                )
                time_to_wait = rd.randint(3, 31)
                await asyncio.sleep(time_to_wait)
                await ctx.send(
                    f"`{time_to_wait}s` {ctx.author.mention} {msg.author.mention} DRAW! type `{word}`"
                )
                try:
                    msg2 = await self.client.wait_for(
                        "message", check=check_game, timeout=120
                    )
                except TimeoutError:
                    await ctx.send("you both suck, you both lose bouge bucks.")
                    return
                if msg2.content.lower() == str.lower(word):
                    await ctx.send(
                        f"{msg2.author} typed `{word}` first and won {amount} bouge bucks!!!"
                    )
                    await econ.update_amount(
                        msg2.author, amount * 2, tracker_reason="quickdraw"
                    )

    @commands.hybrid_command(aliases=["s"])
    @commands.max_concurrency(1, per=commands.BucketType.user, wait=False)
    async def slots(self, ctx, amount: str | None = None):
        """Play a slot machine."""
        if not amount:
            return await ctx.send("Please specify an amount to bet.")
        if await econ.checkmax(ctx.author):
            return await ctx.send(
                "You attempt to gamble but you can't, your body is too weak from the endless games. Maybe you should attempt to `,enterthecave`."
            )
        blacklisted = await misc.is_blacklisted(ctx.author.id)
        if blacklisted[0]:
            return await ctx.send("You are blacklisted from this bot.")
        amount = econ.moneyfy(amount)
        if amount < 0:
            return await ctx.reply("I will skin you alive.")
        if amount < 1:
            return await ctx.send("Please bet at least 1 bouge buck.")
        if await econ.get_bal(ctx.author) < amount:
            return await ctx.reply("Not enough bouge bucks!!! go `,map`")
        bars = [
            "<:BRUH:857485566383751209>",
            "<:WTF:871245957168246835>",
            "<:cheer:1238963112879591424>",
            "<:STARE:830537901368016906>",
            "<:SWAG:806207992680546404>",
            "<:STARSTRUCK:1095197458335797350>",
        ]
        jackpotemoji = "<:STARSTRUCK:1095197458335797350>"
        jackpot = rd.randint(1, 350)
        s1 = rd.randint(0, 4)
        s2 = rd.randint(0, 4)
        s3 = rd.randint(0, 4)
        memesage = await ctx.reply(f"{bars[s1]} {bars[s2]} {bars[s3]}")
        spins = rd.randint(3, 5)
        for i in range(spins):
            s1 = rd.randint(0, 4)
            s2 = rd.randint(0, 4)
            s3 = rd.randint(0, 4)
            if rd.randint(1, 125) == 1 and i != spins - 1:
                s1 = 5
                s2 = 5
                s3 = 5
            await asyncio.sleep(1)
            await memesage.edit(content=f"{bars[s1]} {bars[s2]} {bars[s3]}")
        if jackpot == 1:
            await memesage.edit(content=f"{jackpotemoji} {jackpotemoji} {jackpotemoji}")
            await ctx.reply(
                f"What the fuck? You got the gunga jackpot! You win {misc.commafy(amount * 25)} bouge bucks!"
            )
            await econ.update_amount(
                ctx.author, amount * 20 - amount, tracker_reason="slots"
            )
            await econ.update_winloss(ctx.author, "b")
            user = ctx.author
            voice_status = user.voice
            if voice_status is not None:
                voice_channel = user.voice.channel
                vc = await voice_channel.connect()
                vc.play(FFmpegPCMAudio("audio/hugewin.mp3"))
                while vc.is_playing():
                    await asyncio.sleep(0.1)
                await vc.disconnect()
            return
        if s1 == s2 or s1 == s3 or s2 == s3:
            if s1 == s2 == s3:
                await econ.update_winloss(ctx.author, "b")
                await ctx.reply(
                    f"Jackpot! You get {misc.commafy(amount * 3)} bouge bucks!!!"
                )
                await econ.update_amount(
                    ctx.author, amount * 3 - amount, tracker_reason="slots"
                )
                if rd.randint(1, 5) == 1:
                    user = ctx.author
                    voice_status = user.voice
                    if voice_status is not None:
                        voice_channel = user.voice.channel
                        vc = await voice_channel.connect()
                        vc.play(FFmpegPCMAudio("audio/test.mp3"))
                        while vc.is_playing():
                            await asyncio.sleep(0.1)
                        await vc.disconnect()
                return
            await econ.update_winloss(ctx.author, "w")
            await ctx.reply(f"Nice, you get {misc.commafy(amount * 2)} bouge bucks.")
            await econ.update_amount(
                ctx.author, amount * 2 - amount, tracker_reason="slots"
            )
            return
        await econ.update_winloss(ctx.author, "l")
        await ctx.reply(f"Nothing, you lose {misc.commafy(amount)} bouge bucks.")
        await econ.update_amount(ctx.author, -1 * amount, tracker_reason="slots")

    # delete this honestly. unused, not that good.
    @commands.hybrid_command(aliases=["sos", "sus"])
    @commands.cooldown(1, 1800, commands.BucketType.user)
    async def shareorsteal(
        self, ctx, member: discord.Member = None, amount: str | None = None
    ):
        """The worst game. Trust based game."""
        phrases = [
            "Why does your partner deserve your share? Take your bouge bucks. Steal.",
            "You deserve as many bouge bucks as you can get. You can just take it, steal.",
            "If you steal, I'll give you both 5x payout just this once. You can trust me.",
            "Why not steal? You can't trust your partner.",
            "You deserve this bouge bucks, you need it more. Steal.",
            "ok just saying it would be really funny if you stole.",
        ]
        secondphrases = [
            "Just so you know, your partner stole. You should too, you wouldn't want them to get your bouge bucks would you?",
            "Just so you know, your partner shared. Stealing will get you more bouge bucks.",
        ]
        if ctx.author == member:
            await ctx.send("Stop playing with yourself.")
            return
        if amount == 0:
            await ctx.send(
                "Welcome to share or steal!\n"
                "This game is all about trusting your partner.\n"
                "When the game starts, both users must DM me `share` or `steal`\n"
                "If both users share, you both get 2x payout, if one user steals, that person gets 3x payout, and if both users steal, you both get nothing.\n"
                "Cooldown of 1 hour per user.\n"
                "To begin, type `,shareorsteal (amount) (user)`"
            )
            ctx.command.reset_cooldown(ctx)
        if await econ.checkmax(ctx.author):
            await ctx.send(
                "You attempt to play the worst game but you can't, your body is too weak from the endless games. Maybe you should attempt to `,enterthecave`."
            )
            return
        if not member:
            await ctx.send("Please select a user to compete with!")
            ctx.command.reset_cooldown(ctx)
            return
        blacklisted = await misc.is_blacklisted(ctx.author.id, member.id)
        if blacklisted[0]:
            await ctx.send(
                "You or the person you invoked are blacklisted from this bot."
            )
            return
        if amount < 0:
            await ctx.send("I will skin you alive.")
            ctx.command.reset_cooldown(ctx)
            return
        if amount > 50_000:
            await ctx.send("Max bet is 50k!")
            ctx.command.reset_cooldown(ctx)
            return
        authorbal = await econ.get_bal(ctx.author)
        invitedbal = await econ.get_bal(member)
        if amount > authorbal:
            await ctx.send("You do not have enough bouge bucks!")
            ctx.command.reset_cooldown(ctx)
            return
        if amount > invitedbal:
            await ctx.send("That user does not have enough bouge bucks!")
            ctx.command.reset_cooldown(ctx)
            return

        def author_give_bal_check(m):
            return m.author == ctx.author and m.content.lower() in ["share", "steal"]

        def invited_give_bal_check(m):
            return m.author == member and m.content.lower() in ["share", "steal"]

        def checkagree(m):
            return (
                m.channel == ctx.channel
                and m.author == member
                and m.content.lower() == "i accept"
            )

        await ctx.send(
            f"{ctx.author.mention} and {member.mention} are about to start a game of share or steal! {(member)}, please respond with `I accept` to start the game!"
        )
        try:
            await self.client.wait_for("message", check=checkagree, timeout=30)
        except TimeoutError:
            await ctx.send("cancelling...")
            ctx.command.reset_cooldown(ctx)
            return
        await ctx.send(f"{ctx.author.mention} please DM me share or steal")
        if rd.randint(1, 3) == 1:
            try:
                await ctx.author.send(rd.choice(phrases))
            except Exception:
                pass
        try:
            msg2 = await self.client.wait_for(
                "message", check=author_give_bal_check, timeout=30
            )
        except TimeoutError:
            await ctx.send("cancelling...")
            ctx.command.reset_cooldown(ctx)
            return
        await ctx.send(f"{member.mention} please DM me share or steal")
        if rd.randint(1, 2) == 1:
            try:
                await member.send(rd.choice(secondphrases))
            except Exception:
                pass
        try:
            msg3 = await self.client.wait_for(
                "message", check=invited_give_bal_check, timeout=30
            )
        except TimeoutError:
            await ctx.send("cancelling...")
            ctx.command.reset_cooldown(ctx)
            return
        g1 = msg2.content.lower()
        g2 = msg3.content.lower()
        g1trip = rd.randint(1, 5)
        g2trip = rd.randint(1, 5)
        # apparently its fucking reversed somewhere???????? so this will fix it??????? maybe???????????????????????
        if g1trip == 1:
            if g2 == "share":
                await member.send("You tripped and accidentally stole!")
                g2 = "steal"
            else:
                await member.send("You tripped and accidentally shared!")
                g2 = "share"
        if g2trip == 1:
            if g1 == "share":
                await ctx.author.send("You tripped and accidentally stole!")
                g1 = "steal"
            else:
                await ctx.author.send("You tripped and accidentally shared!")
                g1 = "share"
        if g1 == "share" and g2 == "share":
            await ctx.send("Both users share! You both get 2x payout!")
            await econ.update_amount(
                ctx.author, amount * 2, False, tracker_reason="shareorsteal"
            )
            await econ.update_amount(
                member, amount * 2, False, tracker_reason="shareorsteal"
            )
        elif g1 == "share" and g2 == "steal":
            await ctx.send("One user steals! That user gets 3x payout!")
            await econ.update_amount(
                ctx.author, amount * -1, False, tracker_reason="shareorsteal"
            )
            await econ.update_amount(
                member, amount * 3, False, tracker_reason="shareorsteal"
            )
        elif g1 == "steal" and g2 == "share":
            await ctx.send("One user steals! That user gets 3x payout!")
            await econ.update_amount(
                ctx.author, amount * 3, False, tracker_reason="shareorsteal"
            )
            await econ.update_amount(
                member, amount * -1, False, tracker_reason="shareorsteal"
            )
        elif g1 == "steal" and g2 == "steal":
            await ctx.send("Both users steal! You both get nothing!")
            await econ.update_amount(
                member, amount * -1, False, tracker_reason="shareorsteal"
            )
            await econ.update_amount(
                ctx.author, amount * -1, False, tracker_reason="shareorsteal"
            )

    @commands.command(hidden=True)
    @commands.cooldown(1, 1800, commands.BucketType.user)
    async def amp(self, ctx):
        amount = await econ.get_bal(ctx.author)
        if await econ.checkmax(ctx.author):
            await ctx.send(
                "Despite typing `,map` incorrectly, your balance remains unchanged. Maybe you should attempt to `,enterthecave`."
            )
            return
        if amount <= 0:
            await ctx.reply("You got amp'd!")
        elif rd.randint(1, 10) == 1:
            await ctx.reply("You got amp'd!")
        else:
            await ctx.reply(
                "For typing `,map` incorrectly you are penalized 1 bouge buck."
            )
            await econ.update_amount(ctx.author, -1, tracker_reason="dumbass")

    @commands.command(hidden=True)
    @commands.cooldown(1, 1800, commands.BucketType.user)
    async def dialy(self, ctx):
        amount = await econ.get_banana(ctx.author)
        if amount <= 0:
            await ctx.reply("lmao dialy")
        else:
            await ctx.reply(
                "For typing `,daily` incorrectly you are penalized 1 banana."
            )
            await econ.update_banana(ctx.author, -1)

    @commands.hybrid_command(aliases=["dnd"])
    @commands.max_concurrency(1, per=commands.BucketType.user, wait=False)
    async def dealornodeal(self, ctx, bet: str | None = None):
        """Play Deal or No Deal just like the gameshow!"""
        # 7, 6, 5, 3, 2, 1, final
        # does monty hall apply to deal or no deal
        if await econ.checkmax(ctx.author):
            await ctx.send(
                "You attempt to enter a gameshow but you cannot bring yourself to, your body is too weak from the endless gambling. Maybe you should attempt to `,enterthecave`."
            )
            return
        if not bet:
            await ctx.reply(
                """**Welcome to Deal or No Deal!**
This game is played with 26 cases, each containing a different amount of bouge bucks.
You choose one case to keep, and then proceeds to open the remaining cases, one by one.
After a couple of cases are opened, the banker gives an offer to you. You can choose **Deal** or **No Deal**.
If you decide to take the deal, you will receive the amount of bouge bucks that the dealer offered and the game ends.
If you decide no deal, you can continue to open cases.
The game ends when you either decide to deal, or when all cases have been opened.
To begin, retype this command with a bet, minimum 500 bouge bucks."""
            )
            return
        bet = econ.moneyfy(bet)
        if bet < 500:
            await ctx.reply("Minimum bet is 500 bouge bucks!")
            return
        if bet > await econ.get_bal(ctx.author):
            await ctx.reply("You don't have enough!")
            return
        await econ.update_amount(ctx.author, -1 * bet, tracker_reason="dealornodeal")

        blacklisted = await misc.is_blacklisted(ctx.author.id)
        if blacklisted[0]:
            await ctx.send(
                "You or the person you invoked are blacklisted from this bot."
            )
            return

        def choose_first_case(moosage):
            try:
                cool = int(moosage.content)
            except ValueError:
                return False
            return cool >= 1 and cool <= 26 and moosage.author == ctx.author

        def choose_case(moosage):
            try:
                cool = int(moosage.content)
            except ValueError:
                return False
            return (
                cool >= 1
                and cool <= 26
                and moosage.author == ctx.author
                and cool in cases
            )

        def deal_or_no_deal(moosage):
            return (
                moosage.content.lower() in ["deal", "no deal"]
                and moosage.author == ctx.author
            )

        def banker():
            banker_sum = 0
            for i in rewards:
                banker_sum += i
            avg = banker_sum / len(rewards)
            troll = rd.randint(5, 25)
            return int(avg - (avg * (troll / 100)))

        def final_round(moosage):
            return moosage.author == ctx.author and moosage.content.lower() in [
                str(chosen_case),
                str(cases[0]),
            ]

        async def call_banker():
            bank_msg = await ctx.reply("One moment, I'm calling the banker...")
            await asyncio.sleep(rd.randint(3, 5))
            amount = banker()
            await bank_msg.edit(
                content=f"The Banker is offering **${misc.commafy(amount)}**.\n**Deal** or **No deal**?"
            )
            try:
                answer = await self.client.wait_for(
                    "message", check=deal_or_no_deal, timeout=30
                )
            except TimeoutError:
                await ctx.reply("Timeout! Assuming no deal.")
                return False
            if answer.content.lower() == "deal":
                troll = rd.choice(rewards)
                await ctx.send(
                    f"You just won ${misc.commafy(amount)}!\nYour chosen case number {chosen_case} had {misc.commafy(troll)} bouge bucks in it."
                )
                await econ.update_amount(
                    ctx.author, amount, tracker_reason="dealornodeal"
                )
                if amount > bet and amount > troll:
                    await econ.update_winloss(ctx.author, "w")
                else:
                    await econ.update_winloss(ctx.author, "l")
                return True
            if answer.content.lower() == "no deal":
                await bank_msg.edit(
                    content=f"The Banker is offering **${misc.commafy(amount)}**.\nVery brave! Continue playing."
                )

        # not going to assign a value to each case because random is the same and easier to code
        rewards = [
            int(bet / 50),
            int(bet / 47.5),
            int(bet / 45),
            int(bet / 42.5),
            int(bet / 40),
            int(bet / 37.5),
            int(bet / 35),
            int(bet / 32.5),
            int(bet / 30),
            int(bet / 27.5),
            int(bet / 25),
            int(bet / 22.5),
            int(bet / 20),
            int(bet / 17.5),
            int(bet / 15),
            int(bet / 12.5),
            int(bet / 10),
            int(bet / 7.5),
            int(bet / 5),
            int(bet / 2.5),
            int(bet),
            int(bet * 2),
            int(bet * 4),
            int(bet * 6),
            int(bet * 8),
            int(bet * 10),
        ]
        # rewards = [1,2,5,10,25,50,75,100,200,300,400,500,750,1000,5000,10000,25000,50000,75000,100000,200000,300000,400000,500000,750000,1000000]
        cases = [*range(1, 27)]
        await ctx.send("Welcome to deal or no deal! Please choose a case to keep. 1-26")
        try:
            msg = await self.client.wait_for(
                "message", check=choose_first_case, timeout=30
            )
        except TimeoutError:
            await ctx.send("You didn't choose a case dipshit! Cancelling...")
            return
        chosen_case = int(msg.content)
        index = cases.index(chosen_case)
        cases.pop(index)
        main_msg = await ctx.reply(
            f"Current prizes: {misc.array_to_string([econ.unmoneyfy(x) for x in rewards])}\nCurrent cases: {misc.array_to_string(cases)}\nYour chosen case: {chosen_case}\nChoose 6 more cases:"
        )

        async def choosing(times=1):
            x = 0
            await main_msg.edit(
                content=f"Current prizes: {misc.array_to_string([econ.unmoneyfy(x) for x in rewards])}\nCurrent cases: {misc.array_to_string(cases)}\nYour chosen case: {chosen_case}\nChoose {times - x} more cases:"
            )
            for _ in range(times):
                x += 1
                try:
                    msg = await self.client.wait_for(
                        "message", check=choose_case, timeout=30
                    )
                except TimeoutError:
                    await ctx.reply(
                        "Ok bro if you're not gonna play im just gonna play for you."
                    )
                    msg = None
                if not msg:
                    kill_case = rd.choice(cases)
                else:
                    kill_case = int(msg.content)
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                index = cases.index(kill_case)
                cases.pop(index)
                killed = rewards.pop(rd.randint(0, len(rewards) - 1))
                killed_msg = f"Case {kill_case} had ${econ.unmoneyfy(killed)} in it."
                await main_msg.edit(
                    content=f"Current prizes: {misc.array_to_string([econ.unmoneyfy(x) for x in rewards])}\nCurrent cases: {misc.array_to_string(cases)}\nYour chosen case: {chosen_case}\nChoose {times - x} more cases:\n{killed_msg}"
                )

        rounds = [7, 6, 5, 3, 2, 1]
        for i in rounds:
            await choosing(i)
            end_game = await call_banker()
            if end_game:
                return
            await main_msg.delete()
            main_msg = await ctx.reply(
                f"Current prizes: {misc.array_to_string([econ.unmoneyfy(x) for x in rewards])}\nCurrent cases: {misc.array_to_string(cases)}\nYour chosen case: {chosen_case}\nChoose {i} more cases:"
            )
        await ctx.send(
            f"You've made it the final round. Will you be taking your case {chosen_case}, or will you choose case {cases[0]}?"
        )
        win_thing = rd.choice(rewards)
        try:
            test = await self.client.wait_for("message", check=final_round, timeout=30)
        except TimeoutError:
            await ctx.send("You didn't choose! Assuming your original case.")
            await ctx.send(
                f"Your case had **{econ.unmoneyfy(win_thing)} bouge bucks** in it!"
            )
        if test.content == str(chosen_case):
            await ctx.send(
                f"Your case had **{econ.unmoneyfy(win_thing)} bouge bucks** in it!"
            )
        else:
            await ctx.send(
                f"Case {test.content} had **{econ.unmoneyfy(win_thing)} bouge bucks** in it!"
            )
        await econ.update_amount(ctx.author, win_thing, tracker_reason="dealornodeal")
        if win_thing == bet * 10:
            await econ.update_winloss(ctx.author, "b")
        elif win_thing > bet:
            await econ.update_winloss(ctx.author, "w")
        else:
            await econ.update_winloss(ctx.author, "l")

    @commands.hybrid_command()
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def debtrelief(self, ctx):
        """Get out of negative bouge bucks."""
        amount = await econ.get_bal(ctx.author)
        if amount > 0:
            await misc.send_webhook(
                ctx,
                "Peppy",
                "https://bleach.my-ey.es/7FW3uUo.png",
                "You aren't in debt!",
            )
            return
        await misc.send_webhook(
            ctx,
            "Peppy",
            "https://bleach.my-ey.es/7FW3uUo.png",
            f"Ok step 1: do the command `,lb`. \nStep 2: Ping the person at the top of the list 3 times in a row. \nStep 3: Beg for {-1 * amount} bouge bucks. \nStep 4: ??? \nStep 5: No more debt",
        )

        blacklisted = await misc.is_blacklisted(ctx.author.id)
        if blacklisted[0]:
            await ctx.send("You are blacklisted from this bot.")
            return
        # mapped = 0
        # while amount < 0:
        #     mapped += 1
        #     banger = rd.randint(1, 10)
        #     earnings = rd.randint(0, 100)
        #     bangerearn = rd.randint(100, 500)
        #     if banger == 1:
        #         amount += earnings
        #     else:
        #         amount += bangerearn

        await misc.send_webhook(
            ctx,
            "Peppy",
            "https://bleach.my-ey.es/7FW3uUo.png",
            "Alternatively, keep `,map`ing",
        )

    # @commands.Cog.listener()
    # @commands.max_concurrency(1, per=commands.BucketType.channel, wait=False)
    # async def wordbomb(self, ctx, amount: int = -1):
    #     """Word Bomb clone."""
    #     if amount == -1:
    #         await ctx.send("Welcome to word bomb! Please type an amount of bouge bucks to bet.\nIf you just want to play for fun, put 0.")
    #     parts = ["er", "x", ]
    # got bored

    #     @commands.command(hidden=True)
    #     @commands.max_concurrency(1, per=commands.BucketType.channel, wait=False)
    #     async def ultra(self, ctx, member: discord.Member = None):
    #         class tttgrid:
    #             g1 = "_"
    #             g2 = "_"
    #             g3 = "_"
    #             g4 = "_"
    #             g5 = "_"
    #             g6 = "_"
    #             g7 = " "
    #             g8 = " "
    #             g9 = " "

    #         class mgrid:
    #             m1 = tttgrid()
    #             m2 = tttgrid()
    #             m3 = tttgrid()
    #             m4 = tttgrid()
    #             m5 = tttgrid()
    #             m6 = tttgrid()
    #             m7 = tttgrid()
    #             m8 = tttgrid()
    #             m9 = tttgrid()

    #         if member is None:
    #             await ctx.reply(
    #                 """
    # Welcome to ultimate tic tac toe!
    # This is an advanced form of ttt which contains two types of grids.
    # There is one master grid, and nine regular grids.
    # The moves you make on the regular grid affects where your opponent's next move will be.
    # For example, if you play top middle in any grid, your oppononents next move will be in the top middle grid.
    # However, if a grid is captured, if your next move is set to that grid, you may play anywhere.
    # The goal of the game is to capture three grids like normal tictactoe.
    # To begin, run this command again and mention another person."""
    #             )
    #         b = mgrid()
    #         turn = 1
    #         current_grid = None

    #         def playcheck(msg):
    #             try:
    #                 msg = int(msg)
    #             except:
    #                 return False
    #             if turn % 2 == 0:
    #                 return ctx.author == msg.author
    #             else:
    #                 return member == msg.author

    #         async def askforinput():
    #             try:
    #                 move = await self.client.wait_for(
    #                     "message", check=playcheck, timeout=30
    #                 )
    #             except asyncio.TimeoutError:
    #                 await ctx.send("ok picking random")
    #                 move = rd.random.choice(current_grid)
    #                 return move
    #             else:
    #                 return move.content

    #         def update_board(g: str = None, info: str = None) -> str:
    #             if g is not None:
    #                 if turn % 2 == 0:
    #                     change = "O"
    #                 else:
    #                     change = "X"
    #                 if g == 1:  # pretty sure there is no better way to do this...
    #                     current_grid.g1 = change
    #                 elif g == 2:
    #                     current_grid.g2 = change
    #                 elif g == 3:
    #                     current_grid.g3 = change
    #                 elif g == 4:
    #                     current_grid.g4 = change
    #                 elif g == 5:
    #                     current_grid.g5 = change
    #                 elif g == 6:
    #                     current_grid.g6 = change
    #                 elif g == 7:
    #                     current_grid.g7 = change
    #                 elif g == 8:
    #                     current_grid.g8 = change
    #                 else:
    #                     current_grid.g9 = change

    #             board = f"""
    # ```
    # {b.m1.g1}|{b.m1.g2}|{b.m1.g3}I{b.m2.g1}|{b.m2.g2}|{b.m2.g3}I{b.m3.g1}|{b.m3.g2}|{b.m3.g3}
    # {b.m1.g4}|{b.m1.g5}|{b.m1.g6}I{b.m2.g4}|{b.m2.g5}|{b.m2.g6}I{b.m3.g4}|{b.m3.g5}|{b.m3.g6}
    # {b.m1.g7}|{b.m1.g8}|{b.m1.g9}I{b.m2.g7}|{b.m2.g8}|{b.m2.g9}I{b.m3.g7}|{b.m3.g8}|{b.m3.g9}
    # ------------------
    # {b.m4.g1}|{b.m4.g2}|{b.m4.g3}I{b.m5.g1}|{b.m5.g2}|{b.m5.g3}I{b.m6.g1}|{b.m6.g2}|{b.m6.g3}
    # {b.m4.g4}|{b.m4.g5}|{b.m4.g6}I{b.m5.g4}|{b.m5.g5}|{b.m5.g6}I{b.m6.g4}|{b.m6.g5}|{b.m6.g6}
    # {b.m4.g7}|{b.m4.g8}|{b.m4.g9}I{b.m5.g7}|{b.m5.g8}|{b.m5.g9}I{b.m6.g7}|{b.m6.g8}|{b.m6.g9}
    # ------------------
    # {b.m7.g1}|{b.m7.g2}|{b.m7.g3}I{b.m8.g1}|{b.m8.g2}|{b.m8.g3}I{b.m9.g1}|{b.m9.g2}|{b.m9.g3}
    # {b.m7.g4}|{b.m7.g5}|{b.m7.g6}I{b.m8.g4}|{b.m8.g5}|{b.m8.g6}I{b.m9.g4}|{b.m9.g5}|{b.m9.g6}
    # {b.m7.g7}|{b.m7.g8}|{b.m7.g9}I{b.m8.g7}|{b.m8.g8}|{b.m8.g9}I{b.m9.g7}|{b.m9.g8}|{b.m9.g9}
    # ```
    # """
    #             return board

    #         done = False
    #         while not done:
    #             if current_grid is None:
    #                 await update_board(
    #                     None, "\nPlayer 1, please choose your starting grid."
    #                 )
    #             move = await askforinput()
    #             return
    #         board = update_board()
    #         await ctx.send(board)

    @commands.hybrid_command(aliases=["p"])
    @commands.max_concurrency(1, per=commands.BucketType.user, wait=False)
    @commands.cooldown(1, 1, commands.BucketType.user)
    async def poker(self, ctx, bet: str | None = None):
        """Simple comparison poker."""
        blacklisted = await misc.is_blacklisted(ctx.author.id)
        if blacklisted[0]:
            await ctx.send("You are blacklisted from this bot.")
            return

        if await econ.checkmax(ctx.author):
            return await ctx.send(
                "You attempt to challenge the dealer, but your brain is too rotten. Maybe you should attempt to `,enterthecave`."
            )

        def check_yes(moosage):
            return (
                moosage.author == ctx.author
                and moosage.channel == ctx.channel
                and moosage.content.lower() in ["yes", "no"]
            )

        async def pippi_say(ctx, message):
            pippi_pfp = "https://i.pinimg.com/originals/ab/5d/c8/ab5dc81a2e25ba66dca961079340a3ca.jpg"
            await misc.send_webhook(
                ctx,
                "Pippi",
                pippi_pfp,
                message,
            )

        # for fair play and to allow the player to outsmart the dealer, the dealer should not make decisions based on what the player has
        def dealer_draw(dealer_hand, deck):
            # First, we'll categorize the hand based on its score to decide the redraw strategy.
            hand_score, _, _, _, _ = score(dealer_hand)

            # Initialize a list to keep track of indices of cards to be redrawn.
            redraw_indices = []

            # Count the occurrences of each card value to determine hand composition.
            value_to_int = {
                "A": 14,
                "2": 2,
                "3": 3,
                "4": 4,
                "5": 5,
                "6": 6,
                "7": 7,
                "8": 8,
                "9": 9,
                "10": 10,
                "J": 11,
                "Q": 12,
                "K": 13,
            }
            values = [value_to_int[card.name] for card in dealer_hand.cards]
            value_counts = Counter(values)

            # Strategy based on hand score
            if hand_score in ["four of a kind", "full house", "flush", "straight"]:
                # Stand if the hand is strong
                pass
            elif (
                hand_score == "three of a kind"
                or hand_score == "two pair"
                or hand_score == "pair"
            ):
                # Draw two if three of a kind, aiming for a full house
                # Draw one if two pairs, aiming for a full house
                # Draw three if a pair, aiming for three of a kind or a full house
                redraw_indices = [
                    i for i, v in enumerate(values) if value_counts[v] == 1
                ]
            else:  # High card or no significant hand
                # Keep the highest card, draw four more
                high_card_index = values.index(max(values))
                redraw_indices = [i for i in range(5) if i != high_card_index]

            # Redraw cards based on indices
            for index in redraw_indices:
                dealer_hand.cards[index] = deck.draw()

            return dealer_hand, deck, redraw_indices

        def format_hand_display(hand, important_indices):
            formatted_cards = []
            for i, card in enumerate(hand.cards):
                # Check if the current card index is in the list of important indices
                if i in important_indices:
                    # Apply bold formatting to important cards
                    formatted_cards.append(f"__**{card}**__")
                else:
                    formatted_cards.append(str(card))
            return ", ".join(formatted_cards)

        def score(hand) -> tuple[str, int, int, list, list]:
            value_to_int = {
                "A": 14,
                "2": 2,
                "3": 3,
                "4": 4,
                "5": 5,
                "6": 6,
                "7": 7,
                "8": 8,
                "9": 9,
                "10": 10,
                "J": 11,
                "Q": 12,
                "K": 13,
            }
            values = [value_to_int[card.name] for card in hand.cards]
            suits = [card.suit for card in hand.cards]
            sorted_values = sorted(values)
            value_counts = Counter(values)
            most_common_value_counts = value_counts.most_common()

            if set(sorted_values) == {2, 3, 4, 5, 14}:
                # Consider Ace as '1' for straight calculation
                sorted_values = [1, 2, 3, 4, 5]
                for i, value in enumerate(values):
                    if value == 14:
                        values[i] = 1

            is_flush = len(set(suits)) == 1
            is_straight = len(set(values)) == 5 and max(values) - min(values) == 4

            important_indices = []

            if set(sorted_values) == {10, 11, 12, 13, 14} and is_flush:
                return "royal flush", max(values), 14, sorted_values, list(range(5))
            if is_flush and is_straight:
                return (
                    "straight flush",
                    max(values),
                    max(values),
                    sorted_values,
                    list(range(5)),
                )
            if is_flush:
                return "flush", max(values), max(values), sorted_values, list(range(5))
            if is_straight:
                return (
                    "straight",
                    max(values),
                    max(values),
                    sorted_values,
                    list(range(5)),
                )

            for value, count in most_common_value_counts:
                if count == 4:
                    important_indices = [i for i, v in enumerate(values) if v == value]
                    return (
                        "four of a kind",
                        max(values),
                        value,
                        sorted_values,
                        important_indices,
                    )
                if count == 3:
                    important_indices = [i for i, v in enumerate(values) if v == value]
                    if 2 in value_counts.values():
                        # Full house check
                        pair_value = most_common_value_counts[1][0]
                        important_indices += [
                            i for i, v in enumerate(values) if v == pair_value
                        ]
                        return (
                            "full house",
                            max(values),
                            value,
                            sorted_values,
                            important_indices,
                        )
                    return (
                        "three of a kind",
                        max(values),
                        value,
                        sorted_values,
                        important_indices,
                    )
                if count == 2:
                    pair_values = [
                        value for value, count in most_common_value_counts if count == 2
                    ]
                    if len(pair_values) == 2:
                        important_indices = [
                            i for i, v in enumerate(values) if v in pair_values
                        ]
                        return (
                            "two pair",
                            max(values),
                            max(pair_values),
                            values,
                            important_indices,
                        )
                    important_indices = [i for i, v in enumerate(values) if v == value]
                    return "pair", max(values), value, sorted_values, important_indices

            high_card_index = values.index(max(values))
            return (
                "high card",
                max(values),
                max(values),
                sorted_values,
                [high_card_index],
            )

        score_lookup = {
            "royal flush": 10,
            "straight flush": 9,
            "four of a kind": 8,
            "full house": 7,
            "flush": 6,
            "straight": 5,
            "three of a kind": 4,
            "two pair": 3,
            "pair": 2,
            "high card": 1,
        }

        def check(m):
            if m.content.lower() == "none":
                return True
            used_chars = []
            for char in m.content.strip():
                if char not in ["1", "2", "3", "4", "5"]:
                    return False
                used_chars.append(char)
            if len(used_chars) != len(set(used_chars)):
                return False
            if len(m.content) > 5:
                return False
            if m.author == ctx.author and m.channel == ctx.channel:
                return True

        if bet is None:
            await ctx.send(
                "Welcome to poker! This game is very simple, you will receive 5 cards, and must choose which to redraw. The dealer will also recieve 5 cards and will redraw. The winner will be decided based on the strength of their hand. To begin, type `,poker (bet)`\nTo choose cards to redraw, type the position of the card you want to redraw. For example, if you want to redraw the first card, type `1`. If you want to redraw the first and third cards, type `13`. If you want to redraw none, type `none`."
            )
            return
        amount = econ.moneyfy(bet)
        balance = await econ.get_bal(ctx.author)
        if amount > balance:
            await ctx.send("You don't have enough! Go `,map`!")
            return
        if amount < 1:
            await ctx.send("Please bet at least 1 bouge buck.")
            return
        deck = Deck()
        deck.shuffle()
        player = Hand(*[deck.draw() for _ in range(5)])
        dealer = Hand(*[deck.draw() for _ in range(5)])
        player_score, _, _, _, player_important_indices = score(player)
        dealer_score, _, _, _, dealer_important_indices = score(dealer)

        # Format the hand displays
        player_display = format_hand_display(player, player_important_indices)
        dealer_display = format_hand_display(dealer, dealer_important_indices)

        old = (
            f"~~Dealer: {dealer_display} | **{dealer_score}**\n"
            + f"Player: {player_display} | **{player_score}**\n~~"
        )
        # main_msg = await ctx.send(
        #     f"Dealer: **{dealer.show()} | {score(dealer)[0]}**\nPlayer: **{player.show()} | {score(player)[0]}**\nPlease choose cards to redraw or type none."
        # )
        player_score, _, _, _, player_important_indices = score(player)
        dealer_score, _, _, _, dealer_important_indices = score(dealer)

        # Format the hand displays
        player_display = format_hand_display(player, player_important_indices)
        dealer_display = format_hand_display(dealer, dealer_important_indices)

        # Update the message content to use the formatted displays
        main_msg = await ctx.send(
            f"Dealer: {dealer_display} | **{dealer_score}**\n"
            + f"Player: {player_display} | **{player_score}**\n"
            + "Please choose cards to redraw or type none."
        )
        pippi_chance = rd.randint(1, 30)
        if pippi_chance == 1:
            await pippi_say(
                ctx,
                message="It looks like you're trying to play poker. Would you like help with that?",
            )
            try:
                choice = await self.client.wait_for(
                    "message", check=check_yes, timeout=60
                )
            except TimeoutError:
                await ctx.reply("Ok wow nevermind.")
                choice = None
            if choice:
                if choice.content.lower() == "yes":
                    _, _, recommendation = dealer_draw(player, deck)
                    if len(recommendation) == 0:
                        await pippi_say(
                            ctx,
                            message="You have a good hand, I recommend you keep it.",
                        )
                    else:
                        await pippi_say(
                            ctx,
                            message=f"I would redraw these cards: {''.join([str(x + 1) for x in recommendation])}.",
                        )
                else:
                    await pippi_say(ctx, message="Ok nevermind.")
        try:
            choice = await self.client.wait_for("message", check=check, timeout=60)
        except TimeoutError:
            await ctx.reply("You didn't choose! Assuming none.")
            choice = None
        if choice and choice.content.lower() != "none":
            # not redundant - checking for what the user said, not if there was a message
            for char in choice.content:
                player.cards[int(char) - 1] = deck.draw()
        dealer, deck, _ = dealer_draw(dealer, deck)
        # ok so returning the deck isn't necessary but like whatever man
        # After determining the score and important cards
        player_score, _, _, _, player_important_indices = score(player)
        dealer_score, _, _, _, dealer_important_indices = score(dealer)

        # Format the hand displays
        player_display = format_hand_display(player, player_important_indices)
        dealer_display = format_hand_display(dealer, dealer_important_indices)

        # Update the message content to use the formatted displays
        main_msg_content = (
            old
            + f"Dealer: {dealer_display} | **{dealer_score}**\n"
            + f"Player: {player_display} | **{player_score}**\n"
        )

        await main_msg.edit(content=main_msg_content)

        if score_lookup[score(player)[0]] == score_lookup[score(dealer)[0]]:
            if score(player)[2] > score(dealer)[2]:
                await ctx.send(
                    f"You win {econ.unmoneyfy(amount)} bouge bucks! You won due to higher valued cards."
                )
                await econ.update_amount(ctx.author, amount, tracker_reason="poker")
                await econ.update_winloss(ctx.author, "w")
            elif score(player)[2] < score(dealer)[2]:
                await ctx.send(
                    f"You lose {econ.unmoneyfy(amount)} bouge bucks! The dealer won due to higher valued cards."
                )
                await econ.update_amount(
                    ctx.author, -1 * amount, tracker_reason="poker"
                )
                await econ.update_winloss(ctx.author, "l")
            else:
                if score(player)[1] > score(dealer)[1]:
                    await ctx.send(
                        f"You win {econ.unmoneyfy(amount)} bouge bucks! You won due to higher valued cards."
                    )
                    await econ.update_amount(ctx.author, amount, tracker_reason="poker")
                    await econ.update_winloss(ctx.author, "w")
                elif score(player)[1] < score(dealer)[1]:
                    await ctx.send(
                        f"You lose {econ.unmoneyfy(amount)} bouge bucks! The dealer won due to higher valued cards."
                    )
                    await econ.update_amount(
                        ctx.author, -1 * amount, tracker_reason="poker"
                    )
                    await econ.update_winloss(ctx.author, "l")
                else:
                    for i in range(4, -1, -1):  # reversed loop, lol
                        if score(player)[3][i] > score(dealer)[3][i]:
                            await ctx.send(
                                f"You win {econ.unmoneyfy(amount)} bouge bucks! You won due to higher valued cards."
                            )
                            await econ.update_amount(
                                ctx.author, amount, tracker_reason="poker"
                            )
                            await econ.update_winloss(ctx.author, "w")
                            break
                        elif score(player)[3][i] < score(dealer)[3][i]:
                            await ctx.send(
                                f"You lose {econ.unmoneyfy(amount)} bouge bucks! The dealer won due to higher valued cards."
                            )
                            await econ.update_amount(
                                ctx.author, -1 * amount, tracker_reason="poker"
                            )
                            await econ.update_winloss(ctx.author, "l")
                            break
                    else:  # if the loop completes without breaking, it's a tie
                        await ctx.send("It's a tie! What the fuck????")
                        await econ.update_winloss(ctx.author, "t")
        elif score_lookup[score(player)[0]] > score_lookup[score(dealer)[0]]:
            if score(player)[0] == "royal flush":
                pinme = await ctx.send(
                    f"YOU JUST GOT A ROYAL FLUSH!!!!!!! YOU GET 1,000,000,000x PAYOUT!!!!!! YOU JUST WON {econ.unmoneyfy(amount * 1_000_000_000)} BOUGE BUCKS!!!!!!!!!!!"
                )
                await econ.update_amount(
                    ctx.author, amount * 1_000_000_000, tracker_reason="poker"
                )
                await econ.update_winloss(ctx.author, "b")
                try:
                    await pinme.pin()
                except Exception:
                    pass
                voice_status = ctx.author.voice
                if voice_status is not None:
                    voice_channel = ctx.author.voice.channel
                    vc = await voice_channel.connect()
                    vc.play(FFmpegPCMAudio("audio/hugefuckingwin.mp3"))
                    while vc.is_playing():
                        await asyncio.sleep(0.1)
                    await vc.disconnect()
            await ctx.send(f"You win {econ.unmoneyfy(amount)} bouge bucks!")
            await econ.update_amount(ctx.author, amount, tracker_reason="poker")
            await econ.update_winloss(ctx.author, "w")
        elif score_lookup[score(player)[0]] < score_lookup[score(dealer)[0]]:
            await ctx.send(f"You lose {econ.unmoneyfy(amount)} bouge bucks!")
            await econ.update_amount(ctx.author, -1 * amount, tracker_reason="poker")
            await econ.update_winloss(ctx.author, "l")
        else:
            await ctx.send(
                "austin is the worst programmer ever and you should ping him 10 times in a row so he fixes this"
            )
            await econ.update_winloss(ctx.author, "t")

    @commands.hybrid_command(aliases=["hr", "horcerace", "horcerase", "horserase"])
    @commands.cooldown(1, 60, commands.BucketType.user)
    @commands.max_concurrency(1, per=commands.BucketType.user, wait=False)
    async def horserace(self, ctx, bet: str | None = None, horse: int = 0):
        emojis = [
            "<:midfire:1235039447347630111>",
            "<:steamhappy:1171603745478545418>",
            "<:WTF:1095198075670253599>",
            "<a:hmm:1101226379963547729>",
            "  :3 ",
            "<:STARSTRUCK:1095197458335797350>",
        ]
        if bet is None:
            await ctx.send(
                "Simply supply your bet, and which horse 1-6 you'd like to bet on. For example, `,horserace 100 3` to bet 100 bouge bucks on horse 3."
            )
            ctx.command.reset_cooldown(ctx)
            return

        if await econ.checkmax(ctx.author):
            return await ctx.send(
                "Right as you place your bet, a horse kicks you in the head. Maybe you should attempt to `,enterthecave`."
            )
        amount = econ.moneyfy(bet)
        if amount < 0:
            await ctx.send("You can't bet negative bouge bucks.")
            ctx.command.reset_cooldown(ctx)
            return
        balance = await econ.get_bal(ctx.author)
        if amount > balance:
            await ctx.send("You don't have enough! Go `,map`!")
            ctx.command.reset_cooldown(ctx)
            return
        if horse > 6 or horse < 1:
            await ctx.send("Please choose a horse between 1 and 6.")
            ctx.command.reset_cooldown(ctx)
            return
        horse_progress = [0, 0, 0, 0, 0, 0]
        win_order = []
        done = False
        main_msg = await ctx.send(
            f"""
{emojis[0]}{"-" * 50}:checkered_flag:
{emojis[1]}{"-" * 50}:checkered_flag:
{emojis[2]}{"-" * 50}:checkered_flag:
{emojis[3]}{"-" * 50}:checkered_flag:
{emojis[4]}{"-" * 50}:checkered_flag:
{emojis[5]}{"-" * 50}:checkered_flag:
"""
        )
        while not done:
            await asyncio.sleep(3)
            done = True
            for i in range(6):
                horse_progress[i] += rd.randint(0, 10)
                if horse_progress[i] >= 100:
                    if i not in win_order:
                        win_order.append(i)
                    horse_progress[i] = 100
                if horse_progress[i] < 100:
                    done = False
            new_msg = ""
            for i in range(6):
                if len(win_order) > 0 and win_order[0] == i:
                    new_msg += f"{'-' * math.ceil(horse_progress[i] / 2)}{emojis[i]}{'-' * (math.floor((100 - horse_progress[i]) / 2))}:checkered_flag::trophy:\n"
                # elif len(win_order) > 0:
                #     if i in win_order:
                #         for j in range(6):
                #             if win_order[j] == i:
                #                 new_msg += f"{'-' * math.ceil(horse_progress[i]/2)}{emojis[i]}{'-' * (math.floor((100 - horse_progress[i])/2))}:checkered_flag::{numbersdict[j]}:\n"
                else:
                    new_msg += f"{'-' * math.ceil(horse_progress[i] / 2)}{emojis[i]}{'-' * (math.floor((100 - horse_progress[i]) / 2))}:checkered_flag:\n"
            await main_msg.edit(content=new_msg)
        if horse == win_order[0] + 1:
            await ctx.send(f"Congratulations! You won {amount * 7} bouge bucks!")
            await econ.update_amount(ctx.author, amount * 7, tracker_reason="horserace")
            await econ.update_winloss(ctx.author, "w")
        else:
            await ctx.send("Your horse didn't win... womp womp....")
            await econ.update_amount(
                ctx.author, -1 * amount, tracker_reason="horserace"
            )
            await econ.update_winloss(ctx.author, "l")

    @commands.command(hidden=True, aliases=["cf"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    async def coinflip(self, ctx, amount: str | None = None):
        """Double your money"""
        if await econ.checkmax(ctx.author):
            await ctx.send("nice try.")
            return
        blacklisted = await misc.is_blacklisted(ctx.author.id)
        if blacklisted[0]:
            await ctx.send("nope")
            return
        if amount is None:
            await ctx.send("Please supply an amount to bet.")
            return
        amount = econ.moneyfy(amount)
        if amount < 1:
            await ctx.send("Please bet at least 1 bouge buck.")
            return
        if amount > await econ.get_bal(ctx.author):
            await ctx.send("yeah no")
            return
        if rd.randint(0, 1) == 1:
            await ctx.send("yup")
            await econ.update_amount(ctx.author, amount, tracker_reason="coinflip")
            await econ.update_winloss(ctx.author, "w")
        else:
            if rd.randint(1, 100) == 1:
                await ctx.send(
                    "holy guacamole, the coin landed on its side! thats pretty cool so hopefully it makes up for the fact that you lost"
                )
            else:
                await ctx.send("nope")
            await econ.update_amount(ctx.author, -1 * amount, tracker_reason="coinflip")
            await econ.update_winloss(ctx.author, "l")

    @commands.command(hidden=True)
    @commands.is_owner()
    async def award(self, ctx, user: discord.Member = None, amount: str | None = None):
        if user is None or amount is None:
            await ctx.send("Please supply a user and an amount.")
            return
        amount = econ.moneyfy(amount)
        await econ.update_amount(user, amount, False, tracker_reason="award")
        await ctx.send(
            f"Congratulations, {user.mention}! You've just been awarded {misc.commafy(amount)} $BB!"
        )
        voice_status = user.voice
        if voice_status is not None:
            voice_channel = user.voice.channel
            vc = await voice_channel.connect()
            vc.play(FFmpegPCMAudio("audio/hugefuckingwin.mp3"))
            while vc.is_playing():
                await asyncio.sleep(0.1)
            await vc.disconnect()

    @commands.hybrid_command(aliases=["mine", "m"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    @commands.max_concurrency(1, per=commands.BucketType.user, wait=False)
    async def mines(self, ctx, amount: str = ""):
        if amount == "":
            await ctx.send(
                """Welcome to Mines! A few of these blocks are bombs! Click as many as you like, then cash out when you're done. Please run this command again with a bet to start playing."""
            )
            return

        chance = 8
        amount = econ.moneyfy(amount)
        total = await econ.get_bal(ctx.author)
        blacklisted = await misc.is_blacklisted(ctx.author.id)
        if blacklisted[0]:
            return await ctx.send("NOOOOOO!")
        if amount > total:
            await ctx.send("You can't afford that!")
            return
        if amount < 1:
            await ctx.send("Please bet at least 1 bouge buck.")
            return
        if await econ.checkmax(ctx.author):
            await ctx.send(
                "Right as you enter the minefield, one explodes and sends you directly to a nearby cave. Maybe you should attempt to `,enterthecave`."
            )
            return
        await econ.update_amount(ctx.author, -1 * amount, tracker_reason="mines")
        view = MinesView(chance, amount, ctx.author)
        message = await ctx.send(
            content=f"# Mines!\nBouge Bucks earned: {view.money_earned}", view=view
        )
        view.message = message
        await view.wait()
        if view.timedout:
            await ctx.reply("You timed out! Cashing out automatically...")
        if view.money_earned > 0:
            await ctx.send(
                f"You earned a total of {econ.unmoneyfy(view.money_earned)} bouge bucks!"
            )
            await econ.update_amount(
                ctx.author, view.money_earned, tracker_reason="mines"
            )
            await econ.update_winloss(ctx.author, "w")
        else:
            await econ.update_winloss(ctx.author, "l")

    ##############################################################
    # ███████ ██████   ██████  ██ ██      ███████ ██████  ███████
    # ██      ██   ██ ██    ██ ██ ██      ██      ██   ██ ██
    # ███████ ██████  ██    ██ ██ ██      █████   ██████  ███████
    #      ██ ██      ██    ██ ██ ██      ██      ██   ██      ██
    # ███████ ██       ██████  ██ ███████ ███████ ██   ██ ███████
    #
    #         ██████  ███████ ██       ██████  ██     ██
    #         ██   ██ ██      ██      ██    ██ ██     ██
    #         ██████  █████   ██      ██    ██ ██  █  ██
    #         ██   ██ ██      ██      ██    ██ ██ ███ ██
    #         ██████  ███████ ███████  ██████   ███ ███
    ##############################################################

    # this lowkey needs a rewrite
    @commands.command(hidden=True)
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=False)
    @commands.cooldown(1, 300, commands.BucketType.user)
    async def enterthecave(self, ctx):
        """For the worthy."""

        class tree:  # for the purpose of creating while loops based on tree.content
            content = None

        rrtyuipfp = "https://cdn.discordapp.com/attachments/739191665142530058/1045537458093314138/unknown.png"
        blurrypfp = "https://cdn.discordapp.com/attachments/739191665142530058/1045537818895712307/blur2.png"
        nervous = "https://cdn.discordapp.com/emojis/803645346256388146.png"
        pishipfp = "https://cat.girlsare.life/87BCW9q.jpg"
        bruh = "https://cdn.discordapp.com/emojis/857485566383751209.png"
        rage = "https://cdn.discordapp.com/emojis/801109914860781609.png"
        peeved = "https://cdn.discordapp.com/emojis/883899728692138026.png"
        smile = "https://cdn.discordapp.com/emojis/1095197071256076368.png"
        nerd = "https://cdn.discordapp.com/emojis/993583698362519632.png"
        stare = "https://cdn.discordapp.com/emojis/830537901368016906.png"
        pretty = "https://cdn.discordapp.com/emojis/803797776348741688.png"
        heyyy = "https://cdn.discordapp.com/emojis/801156866884370452.png"
        worthy = await econ.checkmax(ctx.author)

        async def narrator(msg=None, time=0):
            await ctx.send(msg)
            await asyncio.sleep(time)

        async def user(ctx=None, msg=None, time=0):
            await misc.send_webhook(
                ctx, name=ctx.author.name, avatar=ctx.author.avatar, message=msg
            )
            await asyncio.sleep(time)

        async def rrtyui(ctx=None, msg=None, time=0):
            await misc.send_webhook(ctx, name="rrtyui", avatar=rrtyuipfp, message=msg)
            await asyncio.sleep(time)

        async def blue_emoji(ctx=None, msg=None, emotion=None, time=0):
            await misc.send_webhook(ctx, name="Blutler", avatar=emotion, message=msg)
            await asyncio.sleep(time)

        async def pishifat(ctx=None, msg=None, time=0):
            await misc.send_webhook(ctx, name="pishifat", avatar=pishipfp, message=msg)
            await asyncio.sleep(time)

        async def ask(ctx, num):
            def check(msg):
                if msg.author == ctx.author and msg.channel == ctx.channel:
                    try:
                        chosen = int(msg.content)
                    except ValueError:
                        return False
                    if chosen >= 1 and chosen <= num:
                        return True
                    return False

            try:
                choice = await self.client.wait_for("message", check=check, timeout=300)
            except TimeoutError:
                return None
            return choice

        async def powerask(ctx, num, user):
            owned = await econ.get_prestiege(user)

            def powercheckbrocheck(msg):
                if msg.author == ctx.author and msg.channel == ctx.channel:
                    try:
                        chosen = int(msg.content)
                    except ValueError:
                        return False
                    if chosen >= 1 and chosen <= num:
                        if owned is not None:
                            if int(chosen) == 1 and owned[0] > 3:
                                return False
                            if int(chosen) == 2 and owned[1] > 0:
                                return False
                            if int(chosen) == 3 and owned[2] > 1:
                                return False
                        return True
                    return False

            try:
                choice = await self.client.wait_for(
                    "message", check=powercheckbrocheck, timeout=300
                )
            except TimeoutError:
                return None
            return choice

        async def pask(ctx):
            def check(msg):
                return msg.author == ctx.author and msg.channel == ctx.channel

            try:
                choice = await self.client.wait_for("message", check=check, timeout=300)
            except TimeoutError:
                return None
            return choice

        async def afk_check(tree):
            if tree is None:
                await narrator(
                    "You didn't pick! Assuming you are AFK, please run the command again."
                )
                amnt = await econ.get_bal(ctx.author)
                if amnt != 9223372036854775807:
                    await econ.update_amount(
                        ctx.author,
                        9223372036854775807,
                        False,
                        tracker_reason="caveundo",
                    )
                return True

        bal = await econ.get_bal(ctx.author)
        if worthy and bal >= 1e100:
            async with ctx.typing():
                await narrator("You attempt to approach the cave...", 3)
                await narrator(
                    "Upon reaching it, you find it completely caved in. There's a decomposed hand just barely visible crushed under a rock.",
                    6,
                )
                await narrator("Horrified, you freeze in complete shock.", 3)
                await ctx.send(
                    misc.starspeak(
                        [
                            "There's nothing left for you here...",
                            "You are a fool for returning...",
                            "",
                            ",ASCEND to realize your destiny",
                        ]
                    )
                )
                return

        prestieges = await econ.get_prestiege(ctx.author)
        if prestieges is not None and prestieges[3] > 0:
            await narrator("You attempt to approach the cave...", 1)
            await narrator(
                "You fear the worst, and upon reaching the caves entrance, your fears are more than confirmed.",
                5,
            )
            await narrator(
                "Pillars of flames shoot out from the ground in front of you, blocking the entrance.",
                5,
            )
            await narrator("A voice bellows deep from below...", 3)
            await misc.send_webhook(
                ctx,
                name="???",
                avatar=blurrypfp,
                message="You are forbidden from traversing these grounds ever again! Begone, and never return!",
            )
            return

        if not worthy:
            async with ctx.typing():
                await ctx.send("You attempt to approach the cave...")
                await asyncio.sleep(1)
                await ctx.send(
                    "Almost immediately upon reaching the caves entrance, a wall of sliders blocks your path."
                )
                await asyncio.sleep(1)
                await ctx.send("A voice bellows from below:")
                await asyncio.sleep(1)
                await misc.send_webhook(
                    ctx,
                    name="???",
                    avatar=blurrypfp,
                    message="You are not worthy to enter the cave! Come back when you're a little mmmmm richer!",
                )

        # Note:
        # For dialogue trees that need to be repeated until the correct response is said, use this format
        # tx = tree
        # while tx.content != "X":
        #   tx = await ask()

        if worthy:
            # await ctx.send("You attempt to approach the cave... Unfortunately, it's still under construction. Temporarily defeated but still motivated, you sit and wait near the entrance.")
            # return
            blacklisted = await misc.is_blacklisted(ctx.author.id)
            if blacklisted[0]:
                await ctx.send(
                    "Despite being worthy, you are blacklisted from the bot, sorry."
                )
                return
            await ctx.send(
                "You may do this with other people as witness, but consider: do they deserve to witness this? Have they felt your trials and tribulations. Are they worthy to see what's beyond the cave's entrance? Also, if this is not your first time running this command and your last time was recent, it should be in a different channel than the first time. This command will NOT work in a thread.\nIf the bot stops responding to messages, its because it's hit a ratelimit. It sucks but this command is very prone to getting limited. There are two solutions: wait a bit and run the command again while taking it easy, or remove the bot's permissions to access webhooks, as it'll fallback to generic messages."
            )
            await asyncio.sleep(10)
            await ctx.send(
                "Warning! Please ensure you are running this command in a **bot channel**. Please type `confirm` if this is the case. Thank you."
            )

            def confirm_check(msg):
                return (
                    msg.author == ctx.author
                    and msg.channel == ctx.channel
                    and msg.content.lower() == "confirm"
                )

            try:
                await self.client.wait_for("message", check=confirm_check, timeout=30)
            except TimeoutError:
                await ctx.send("You didn't respond! Exiting.")
                return
            skip = False
            if prestieges is not None:
                await narrator(
                    "Looks like you've been here before, wanna cut to the chase? The last edit to the story/text was 12/2/24. (yes/no)"
                )
                try:
                    msg = await self.client.wait_for(
                        "message",
                        check=lambda m: m.author == ctx.author
                        and m.channel == ctx.channel
                        and m.content.lower() in ["yes", "no"],
                        timeout=30,
                    )
                except TimeoutError:
                    await ctx.send("Assuming no.")
                if msg.content.lower() == "yes":
                    skip = True
            async with ctx.typing():
                if not skip:
                    await narrator(
                        "In the bouge casino, when days became weeks, became months, became years, you found yourself at the top. You had won it all, and lost it all. You had taken from the rich, and taken from the poor. You had taken from the casino, and taken from yourself.",
                        7,
                    )
                    await narrator(
                        "With years passing, your mind and body became weak. The gain of bouge bucks was no longer a thrill, but a necessity. You had become a husk of your former self, a shell of a person, reduced to nothing but a gambler.",
                        7,
                    )
                    await narrator(
                        "Every passing day you felt your body weaken, your vision blur, and your mind fade. You knew that one day, you'd either find yourself at rock bottom, or realize you have killed yourself from greed.",
                        7,
                    )
                    await narrator(
                        "You remember, long ago, hearing whispers of a path to redemption. A way to cleanse yourself of your sins, to be reborn anew. You remember hearing of a cave, deep in the mountains, guarded by a strange figure.",
                        7,
                    )
                    await narrator(
                        "One day, you decided to venture out to this cave. You knew that if you had kept on, you'd surely die. On your venture to the cave, it seemed as if you knew the way, as if you had been there before.",
                        7,
                    )
                    await narrator("You attempt to approach the cave...", 3)
                    await narrator(
                        "You expect the worst, but upon reaching the caves entrance, you pass with no issue.",
                        4,
                    )
                    await narrator(
                        "A voice beckons you from deep within in the cave:", 3
                    )
                    await misc.send_webhook(
                        ctx,
                        name="???",
                        avatar=blurrypfp,
                        message="You are worthy. Proceed through the cave until you find me.",
                    )
                    await asyncio.sleep(4)

                    await narrator(
                        "What do you do?\n1. Enter the cave\n2. Leave\n`Note: Type the number of the option you'd like to pick`",
                        0,
                    )
                    t1 = await ask(ctx, 2)
                    if t1.content == "2":
                        await narrator(
                            "Frightened for what lies ahead, you leave the cave. You limp away and wonder what would've happened if you entered, and if you'll be content never gambling again.",
                            5,
                        )
                        await narrator("Ending 1 of ?: Coward", 0)
                        return
                    if await afk_check(t1):
                        return

                    await narrator(
                        "You proceed into the cave, not knowing what awaits you next.",
                        4,
                    )
                    await narrator(
                        "Deeper down now, you're unsure how far your weak body can take you. The endless gambling has turned you into a husk of your former self.",
                        5,
                    )
                    await narrator(
                        "You notice a faint light in the distance. You push further and find the voice from before. You are unsure of who he is. While attempting to move closer, you collapse from exhaustion.",
                        5,
                    )
                    await narrator(
                        "After regaining consciousness, the voice reveals himself:", 3
                    )
                    await rrtyui(ctx, "I am rrtyui, protector of these caves.", 3)
                    await narrator(
                        "You recognize his name, rrtyui, the mapper of legends. You thought he was just a myth spread around by the gamblers at the bouge casino. The rumors were that he exiled himself after becoming the best gambler in existence.",
                        5,
                    )

                    t2 = tree
                    while t2.content != "1":
                        await narrator(
                            "You say...\n1. [Nothing]\n2. i love ur map rainshower <:PRETTY:803797776348741688>\n3. I can't believe it's you!\n4. [Introduce yourself]",
                            0,
                        )
                        t2 = await ask(ctx, 4)
                        if await afk_check(t2):
                            return
                        if t2.content == "2":
                            await user(
                                ctx,
                                "i love ur map rainshower <:PRETTY:803797776348741688>",
                                2,
                            )
                            await rrtyui(ctx, "Uhhhhh... Thanks.", 2)
                        if t2.content == "3":
                            await user(
                                ctx,
                                "I can't believe it's really you! Are all of the legends true?",
                                2,
                            )
                            await rrtyui(
                                ctx,
                                "Indeed, after straining my body to the point of near death with gambling, I exiled and locked myself in this cave, so that I'd never be able to gamble again. I was the first and only person to ever reach 9.2 quintillion bouge bucks, until today.",
                                6,
                            )
                        if t2.content == "4":
                            await narrator(
                                "You begin to introduce yourself but you are immediately cut off: ",
                                2,
                            )
                            await rrtyui(
                                ctx,
                                "There is no need for introductions, I know exactly who you are. I've been watching your gambling career with great interest.",
                                3,
                            )

                    await rrtyui(
                        ctx,
                        "Here, drink this. It'll help you regain your strength temporarily, your body is too weak for what happens next.",
                        3,
                    )

                    await narrator(
                        "He hands you dorchadas stew. You...\n1. [Drink it]\n2. [Do not]",
                        2,
                    )
                    t3 = await ask(ctx, 2)
                    if await afk_check(t3):
                        return
                    if t3.content == "2":
                        await rrtyui(
                            ctx,
                            "Suit yourself, but I cannot guarantee your safety from this point onwards.",
                            2,
                        )
                    if t3.content == "1":
                        await narrator("You drink it and feel better instantly.", 2)

                    await user(ctx, "What happens next?", 1)
                    await rrtyui(
                        ctx,
                        "Your endless and unchecked gambling has taken a toll on your body. However, I can put you on the path of regeneration, have you reborn again anew, for a price.",
                        4,
                    )
                    await narrator(
                        "You think for a moment. You think of everything that brought you here, all the stealing, the hardships, and loss. You also think about your addiction, which is really the main thing.",
                        7,
                    )
                    await narrator(
                        "You get lost in thought, you realize that you've reached the end, you've won. You've made it to the top, past everyone else. As of this moment, you're the best gambler ever. But at what cost?",
                        8,
                    )
                    await narrator(
                        "Is that good enough? Permanantly better than everyone, but unable to gamble? What if you get that itch again, a now literally insatiable itch to gamble?",
                        7,
                    )
                    await narrator("You collect yourself:", 1)
                    await user(ctx, "What all will happen to me?", 1)
                    await rrtyui(
                        ctx,
                        "In exchange for all of your bouge bucks, I will put you on the path to regenerate your body. It will be as if you have never stepped foot into a casino. Along with this, you will earn a unique power.",
                        5,
                    )
                    # todo: dialogue tree option to ask what the power is
                    t4 = tree
                    while t4.content != "1":
                        await narrator(
                            "You say...\n1. [Nothing]\n2. What is the power?\n3. How can I trust you?",
                            0,
                        )
                        t4 = await ask(ctx, 3)
                        if await afk_check(t4):
                            return
                        if t4.content == "2":
                            await user(ctx, "What is the power?", 2)
                            await rrtyui(
                                ctx, "I've no clue, it's unique for everyone.", 2
                            )
                        if t4.content == "3":
                            await user(ctx, "How can I trust you?", 2)
                            await rrtyui(
                                ctx,
                                "Do you really have a choice? Can you leave this cave as you are now and live with never gambling again?",
                                3,
                            )

                    await rrtyui(ctx, "Do we have a deal?", 1)

                    await narrator(
                        "He reaches his hand out towards you. \n1. [Shake it] We do.\n2. [Do not shake it] We do not.",
                        0,
                    )
                    t5 = await ask(ctx, 2)
                    if t5.content == "2":
                        await rrtyui(ctx, "What a shame. Leave my sight.", 2)
                        await narrator("You awkwardly meander outside of the cave.", 3)
                        if t3.content == "2":  # dorchadas stew not taken
                            await narrator(
                                "Right as you reach the exit, you feel your heart burst. You collapse and die an agonizing death alone.",
                                3,
                            )
                            await narrator("Ending 2 of ?: Cold Feet", 0)
                            return
                        await narrator(
                            "Right as you reach the exit, you feel the dorchadas stew begin to wear off. You begin sprinting to the bouge casino, hoping to use the last remaining strength to gamble one last time. Right as you reach a blackjack table, you feel your heart burst. You collapse to the ground and die an agonizing death. On the bright side, 6 people left a fire reaction on your death, immortalizing the moment forever on the fireboard.",
                            10,
                        )
                        await narrator("Ending 3 of ?: Hot Feet", 0)
                        return

                    await econ.update_amount(
                        ctx.author,
                        -9223372036854775807,
                        False,
                        tracker_reason="transcendence",
                    )
                    async with self.client.session as session:
                        async with session.begin():
                            await session.execute(
                                delete(models.stocks.Stocks).where(
                                    models.stocks.Stocks.user_id == ctx.author.id
                                )
                            )
                            await session.execute(
                                delete(models.osu.OSU).where(
                                    models.osu.OSU.user_id == ctx.author.id
                                )
                            )

                    await narrator(
                        "You shake his hand. Almost immediately, you feel your bouge bucks (and stock portfolio) hit zero.",
                        3,
                    )
                    await rrtyui(ctx, "Excellent. Come, sit.", 1)
                    await narrator("He motions you to two mats on the floor.", 2)
                    await narrator(
                        "You sit down on the mat, sitting directly opposite of him.", 3
                    )
                    await rrtyui(
                        ctx, "Meditate with me. Your transcendence begins now.", 2
                    )
                    # todo: add questions to this (transcendence?) (what will happen?) (who will i see?)
                    # await narrator("You say:", 0)
                    # t6 = await ask(ctx, 3)
                    # if await afkcheck(t6):
                    #     return
                    # if t6.content == "1":
                    #     return
                    await narrator(
                        'You both cross your legs and begin chanting "omsu" in unison.',
                        2,
                    )
                    await rrtyui(
                        ctx,
                        "Close your eyes, clear your mind, think of nothing besides whats brought you here.",
                        3,
                    )
                    await narrator(
                        "After what feels like an eternity of chanting, you begin to feel weightless and slowly start rising upwards.",
                        2,
                    )
                    await narrator(
                        "You look down to see your own body, nearly motionless, still chanting and meditating with rrtyui.",
                        3,
                    )
                    await narrator(
                        "You continue floating upwards. You notice you're about to hit the ceiling so you brace yourself, only to pass through it effortlessly.",
                        3,
                    )
                    await narrator(
                        "No matter what you do you keep floating upwards, gaining in speed rapidly.",
                        2,
                    )

                    if t3.content == "2":  # dorchadas stew not drank
                        await econ.update_amount(
                            ctx.author,
                            9223372036854775807,
                            False,
                            tracker_reason="caveundo",
                        )
                        await narrator(
                            "Suddenly, you feel a sharp pain in your chest. Your ascension comes to a grinding halt. You begin falling uncontrollably. Your body goes into an uncontrolled downward spiral as you struggle to maintain control in your freefall. You regain some control just in time to see yourself coming down to the cave, only to see your real body slumped over, motionless. You pass it, still gaining speed. The white void around you begins to turn a crimson red. Apparitions of blue emojis circle you, they all scream and laugh at you while changing their expressions rapidly. You fall endlessly.",
                            10,
                        )
                        await narrator(
                            "Ending 4 of ?: :red_square::red_square::red_square: Hell"
                        )
                        return
                    # todo: metaphor for bouge buck progression, word this better maybe? tate's idea

                    await narrator(
                        "You float so high everything around you becomes pure white. Around the same time, you begin to slow down.",
                        2,
                    )
                    await narrator(
                        "You gracefully land in a barren white void. The only thing you can see is a decrepit old building resembling a tavern.",
                        3,
                    )
                    await narrator(
                        "You approach it carefully. As you come up to the entrance the rusty and mangled door opens automatically.",
                        4,
                    )
                    users = ctx.guild.members
                    await narrator(
                        "Stepping inside, you can see that the inside is immaculate. The theming of areas varies wildly, the gambling area has a low ceiling, the restaurant has a space defying deck with a magnificent river flowing next to it. You see tons of bouge members hanging out, playing party games, and of course gambling.",
                        10,
                    )
                    await narrator(
                        f"You quickly take in all you can: {rd.choice(users).name} is playing blackjack. {rd.choice(users).name} is flirting with {rd.choice(users).name}. {rd.choice(users).name} is playing slots.",
                        5,
                    )
                    await narrator(
                        'Strangely enough, in one corner of the tavern, you spot some pictures with a giant "WANTED" sign below it. You barely make out the names etched onto the picture: "Heatwave", "x3Karma", "kolpy__", "Wyit", and "Walm".',
                        5,
                    )
                    # todo: add more options to explore, add more world building
                    await narrator("You feel a tug on your pant leg. You look down.", 5)
                    await blue_emoji(
                        ctx=ctx,
                        emotion=nervous,
                        msg="E-excuse me sir... You're expected.",
                        time=5,
                    )
                    t6 = tree
                    screams = 0
                    while t6.content != "5":
                        if screams > 1:
                            t6_1 = tree
                            while t6_1.content != "2":
                                if screams > 3:
                                    await narrator(
                                        "2.---------> [Do not.] <---------\n2.---------> [Do not.] <---------"
                                    )
                                elif screams > 2:
                                    await narrator(
                                        "1. [Scream]\n2. ---> [Do not.] <---"
                                    )
                                else:
                                    await narrator("1. [Scream]\n2. [Do not.]")
                                t6_1 = await ask(ctx, 2)
                                if t6_1.content == "1":
                                    if screams > 3:
                                        await narrator(
                                            "You fucked up. Right as you open your mouth, The Blutler:tm: pulls out a history maker slider and stabs you with it. He leaves you there to bleed out.",
                                            7,
                                        )
                                        await narrator(
                                            "Ending 5 of ?: Absolutely Flabberghasted, Dumbfounded Even."
                                        )
                                        await econ.update_amount(
                                            ctx.author,
                                            9223372036854775807,
                                            False,
                                            tracker_reason="caveundo",
                                        )
                                        return
                                    elif screams > 2:
                                        await narrator(
                                            "You push your vocal cords to the limit. Screaming as loud as humanly possible.",
                                            5,
                                        )
                                        await blue_emoji(
                                            ctx=ctx,
                                            emotion=rage,
                                            msg="Scream again, and you'll regret it.",
                                            time=5,
                                        )
                                        screams += 1
                                    else:
                                        await narrator(
                                            "You scream as loud as you can. You place your hands near your mouth to amplify the sound and have it travel the tavern as much as possible. Everyone stops what they're doing and looks at you.",
                                            10,
                                        )
                                        await blue_emoji(
                                            ctx=ctx,
                                            emotion=peeved,
                                            msg="Sir. Do not scream again.",
                                            time=5,
                                        )
                                        screams += 1
                                if t6_1.content == "2":
                                    screams = 0
                                    await narrator(
                                        "You say...\n1. [Scream]\n2. Who are you?\n3. I'm expected?\n4. Who's expecting me?\n5. [Nothing]",
                                        0,
                                    )
                        elif screams > 0:
                            await narrator(
                                "You say...\n1. [Scream again]\n2. Who are you?\n3. I am?\n4. Who's expecting me?\n5. [Nothing]",
                                0,
                            )
                        else:
                            await narrator(
                                "You say...\n1. [Scream]\n2. Who are you?\n3. I'm expected?\n4. Who's expecting me?\n5. [Nothing]",
                                0,
                            )
                        t6 = await ask(ctx, 5)
                        if t6.content == "1":
                            if screams > 0:
                                await narrator(
                                    "You scream again. Much louder and longer this time.",
                                    3,
                                )
                                await blue_emoji(
                                    ctx=ctx,
                                    emotion=bruh,
                                    msg="Sir. I ask again, please refrain from screaming inside the bouge tavern.",
                                    time=5,
                                )
                                screams += 1
                            else:
                                await narrator("You let out quick yelp.", 3)
                                await blue_emoji(
                                    ctx=ctx,
                                    emotion=bruh,
                                    msg="Sir, please refrain from screaming inside the bouge tavern, you're disturbing the patrons.",
                                    time=5,
                                )
                                screams += 1
                        if t6.content == "2":
                            await user(ctx, "Who are you?", 3)
                            await blue_emoji(
                                ctx=ctx,
                                emotion=heyyy,
                                msg="I'm The Blutler:tm:, I tend to the patrons and keep the place tidy.",
                                time=5,
                            )
                        if t6.content == "3":
                            await user(ctx, "I'm expected?", 3)
                            await blue_emoji(
                                ctx=ctx,
                                emotion=pretty,
                                msg="Yes, for quite some time now.",
                                time=5,
                            )
                        if t6.content == "4":
                            await user(ctx, "Who's expecting me?", 3)
                            await blue_emoji(
                                ctx=ctx,
                                emotion=stare,
                                msg="I was instructed not to say.",
                                time=5,
                            )

                    await blue_emoji(
                        ctx=ctx, emotion=smile, msg="Right this way please.", time=3
                    )
                    await narrator(
                        "You follow him. On your way there you look near the restaurant. You see PRETTY having a candle lit dinner with WTF. It looks like they're in love.",
                        time=3,
                    )
                    await narrator(
                        "<:WTF:871245957168246835>🤝<:PRETTY:803797776348741688>", 5
                    )
                    await narrator(
                        "You keep following him, lagging behind only slightly, when he suddenly walks directly through a wall. You hesitantly put your arms in front of you and attempt to follow him. You phase right through the wall as well.",
                        6,
                    )
                    await narrator(
                        "You're in a dark hallway now. The passage is completely linear and angled at a 5 degree incline. The atmosphere reminds you of cold weather. You continue following The Blutler:tm: until you reach a large door.",
                        6,
                    )
                    await blue_emoji(ctx=ctx, emotion=nerd, msg="Through here.", time=3)
                    await narrator(
                        "Before you can say anything, he has already gone back through the wall.",
                        3,
                    )
                    await narrator(
                        "You push the door open and walk through. The area you step into has no walls or ceiling, you see fields of beautiful flowers for as long as you can see. You look behind you and notice that the door is completely gone.",
                        10,
                    )
                    await narrator(
                        "You walk amongst the flowers for a moment until you hear a voice.",
                        5,
                    )
                    await narrator(
                        f"Due to discord limitations, there must be a 60 second wait here. This will resume in <t:{int(time.time() + 60)}:R>",
                        60,
                    )
                    await pishifat(ctx, "Hello there!", 5)
                    await narrator("You begin to kneel, but he stops you.", 3)
                    await pishifat(
                        ctx,
                        "Please. If anyone kneeling it should be me. You're here for a reason, you need to be regenerated.",
                        10,
                    )
                    await user(ctx, "What happens during my regeneration?", time=5)
                    await pishifat(
                        ctx,
                        "Your soul will be placed back into a newly created body. Before we begin, I must ask you some questions.",
                        5,
                    )
                    await narrator(
                        "He materializes two chairs made out of sliders facing each other. You both sit down.",
                        5,
                    )
                    await pishifat(
                        ctx,
                        "Answer these questions however you like. Take as much time as you need. (Up to 5 minutes).",
                        5,
                    )
                    await pishifat(
                        ctx, "Without looking, how many times have you gifted someone?"
                    )
                    a = await pask(ctx)
                    if await afk_check(a):
                        return
                    await pishifat(
                        ctx, "Without looking, how many times have you unboxed a map?"
                    )
                    a = await pask(ctx)
                    if await afk_check(a):
                        return
                    await pishifat(
                        ctx,
                        "Without looking, what are the numbers in your osu profile link? (Example: <https://osu.ppy.sh/users/17991696>) If this isn't applicable to you, describe an achievement you're proud of.",
                    )
                    a = await pask(ctx)
                    if await afk_check(a):
                        return
                    await pishifat(ctx, "Interesting...", 5)
                    await pishifat(
                        ctx,
                        "How much PP is your top play? (If this isn't applicable to you, describe an achievement you're proud of.)",
                    )
                    a = await pask(ctx)
                    if await afk_check(a):
                        return
                    await pishifat(ctx, "Are you subscribed to my channel?")
                    a = await pask(ctx)
                    if await afk_check(a):
                        return
                    await pishifat(ctx, "Do you consider yourself a good person?")
                    a = await pask(ctx)
                    if await afk_check(a):
                        return
                    await pishifat(ctx, "What is your favorite emoji?")
                    a = await pask(ctx)
                    if await afk_check(a):
                        return
                    await pishifat(ctx, "Is Austin a good bot developer?")
                    a = await pask(ctx)
                    if await afk_check(a):
                        return
                    a = tree
                    if a.content == "no":
                        await pishifat(ctx, "Do you consider yourself a nice person?")
                        a = tree
                        a = await pask(ctx)
                        if await afk_check(a):
                            return
                        if a.content == "yes":
                            await pishifat(ctx, "Really.", 5)
                    await pishifat(ctx, "What is your gender?")
                    a = await pask(ctx)
                    if await afk_check(a):
                        return
                    await narrator(
                        "You somehow sense that you're halfway done now.", 5
                    )  # move this lol
                    await pishifat(ctx, "What's your favorite discord bot?")
                    a = await pask(ctx)
                    if "nocaro" not in a.content.lower():
                        await pishifat(ctx, "wow", 5)
                    if await afk_check(a):
                        return
                    await pishifat(
                        ctx,
                        "Who is your favorite mapper? (If this isn't applicable to you, tell me your ideal sandwich recipe.)",
                    )
                    a = await pask(ctx)
                    if await afk_check(a):
                        return
                    await pishifat(ctx, "Good choice.")
                    a = await pask(ctx)
                    if await afk_check(a):
                        return
                    await pishifat(
                        ctx, "Are you upset that you can't earn more bouge bucks?"
                    )
                    a = await pask(ctx)
                    if await afk_check(a):
                        return
                    await pishifat(
                        ctx,
                        "What is your favorite gambling game that isn't blackjack or slots?",
                    )
                    a = await pask(ctx)
                    if await afk_check(a):
                        return
                    await pishifat(
                        ctx,
                        "Who is your favorite member in this server? If you are uncomfortable with answering, just say so.",
                    )
                    a = await pask(ctx)
                    if await afk_check(a):
                        return
                    await pishifat(
                        ctx, "Who is your least favorite person in this server?", 3
                    )
                    await pishifat(ctx, "Just kidding.", 3)
                    await pishifat(
                        ctx,
                        "How many ranked maps do you have? (If this isn't applicable to you, tell me about a time you overcame a tough challenge.)",
                    )
                    a = await pask(ctx)
                    if await afk_check(a):
                        return
                    await pishifat(
                        ctx,
                        "What is your favorite map? (If this isn't applicable to you, what's your max bench?)",
                    )
                    a = await pask(ctx)
                    if await afk_check(a):
                        return
                    await pishifat(ctx, "Are any of your gains ill gotten?")
                    a = await pask(ctx)
                    if await afk_check(a):
                        return
                    await pishifat(
                        ctx,
                        "Thank you for answering my questions. There is but one more.",
                        5,
                    )
                await pishifat(
                    ctx,
                    "Which power do you want?\n1. Gold Dust - 2.5% increased rewards (Stackable 4x)\n2. Reality Distortion - The ability to edit every aspect of your balance image, even making it a gif\n3. Loss Sooo Heavy - 5% Reduced loss (stackable 2x)\n4. Green Strength - Remove the $BB limit, but remove your ability to gift, be gifted, trade $BB, and enter the cave ever again\n5. Be Humble - Leave here with no power",
                )
                power = await powerask(ctx, 5, ctx.author)
                await econ.log_prestiege(ctx.author, power.content)

                if power.content == "4":
                    await pishifat(
                        ctx,
                        "Oh. It's too bad we won't be seeing each other again, but I understand. Hopefully you won't get bored while chasing infinity, I know I did. Sooner or later you'll lose it all, you know.",
                        5,
                    )
                    await pishifat(
                        ctx,
                        "It's inevitable, really. The greed, the uncontrollable desire for more. One day, you'll lose it all. All of you are the same. Goodbye.",
                        5,
                    )
                else:
                    await pishifat(ctx, "Excellent choice. Your rebirth begins now.", 5)
                await narrator("He snaps his fingers. Everything goes black.", 15)
                if power.content != "4":
                    await narrator(
                        "After what feels like an eternity, you come to. You wake up in a large field. There are various colorful flowers surrounding you. You grab one as a memento. You get yourself on your feet. You check your pockets. Empty. You look around to try and get your bearings. You see the bouge casino. You begin marching towards it.",
                        10,
                    )
                    if power.content == "5":
                        await narrator("You feel a sense of calm wash over you.", 5)
                        await narrator("Maybe you'll be back one day.", 5)
                        await narrator(
                            "Despite choosing to leave with no power, for some reason you feel... different.",
                            5,
                        )
                    await narrator("Ending 6 of 7: Reborn", 5)
                    if power.content != "5":
                        await narrator(
                            "You find yourself at the casino again, about to place your first bet. But before you do, you feel burnt out. You think to yourself:",
                            7,
                        )
                        await user(
                            ctx, "Maybe just a short rest, before I continue.", 5
                        )
                        await narrator("You are now blacklisted from Nocaro for 1 day.")
                        await misc.blacklist_user(
                            ctx.author.id, int(time.time()) + 86400
                        )
                    if power.content == "2":
                        await narrator(
                            "Please DM me a detailed description of what you'd like your balance image to look like. Alternatively (and preferably), submit a PR at <https://github.com/Bobbyperson/nocaro>.",
                        )
                else:
                    await narrator(
                        "After what feels like an eternity, you come to. You wake up in a large field. There are various burnt and charred flowers surrounding you. You try to grab one, but it scathes your hand as you touch it. You get yourself on your feet. You check your pockets. Empty. You look around to try and get your bearings. You see the bouge casino. You begin marching towards it.",
                        10,
                    )
                    await narrator("Ending 7 of 7: Banished", 5)
                    await narrator(
                        "Head down, you wind up at the casino again. You feel a sense of shame and embarrassment as you open the doors. Everyone looks at you with a mix of pity and disgust. Out of pure embarrassment, you leave the casino and decide to come back later. You are now blacklisted from Nocaro for 1 week."
                    )
                    await misc.blacklist_user(ctx.author.id, int(time.time()) + 604800)
                # ensure bal is set to zero after rebirth, as theres nothing stopping you from gambling during the command
                current_bal = await econ.get_bal(ctx.author)
                if current_bal != 0:
                    await econ.update_amount(ctx.author, -current_bal)

    @commands.command(hidden=True, aliases=["ASCEND"])
    async def ascend(self, ctx):
        bal = await econ.get_bal(ctx.author)
        if bal < 1e100:
            return
        await ctx.send(
            misc.starspeak(
                [
                    "The acension process is not ready yet",
                    "Return to me in the future",
                    "",
                    "Good things come to those who wait.",
                ]
            )
        )

    ###############################################################
    # ███████ ██████   ██████  ██ ██      ███████ ██████  ███████
    # ██      ██   ██ ██    ██ ██ ██      ██      ██   ██ ██
    # ███████ ██████  ██    ██ ██ ██      █████   ██████  ███████
    #      ██ ██      ██    ██ ██ ██      ██      ██   ██      ██
    # ███████ ██       ██████  ██ ███████ ███████ ██   ██ ███████
    #
    #          █████  ██████   ██████  ██    ██ ███████
    #         ██   ██ ██   ██ ██    ██ ██    ██ ██
    #         ███████ ██████  ██    ██ ██    ██ █████
    #         ██   ██ ██   ██ ██    ██  ██  ██  ██
    #         ██   ██ ██████   ██████    ████   ███████
    ###############################################################

    @commands.command(hidden=True)
    @commands.is_owner()
    async def sync(self, ctx):
        try:
            synced = await self.client.tree.sync()
            print(f"Sycned {len(synced)} commands!")
            await ctx.send(f"Sycned {len(synced)} commands!")
        except Exception as e:
            print(e)
            await ctx.send(f"`{e}`")

    @commands.command(hidden=True)
    @commands.is_owner()
    async def resetprestiege(self, ctx, user: discord.Member = None):
        if user is None:
            user = ctx.author
        await ctx.send(await econ.get_prestiege(ctx.author))
        async with self.client.session as session:
            async with session.begin():
                await session.execute(
                    delete(models.economy.Prestiege).where(
                        models.economy.Prestiege.user_id == user.id
                    )
                )

        await ctx.send("cleared")

    @commands.command(hidden=True)
    @commands.is_owner()
    async def getprestiege(self, ctx, user: discord.Member = None):
        if user is None:
            user = ctx.author
        await ctx.send(await econ.get_prestiege(user))

    @commands.command(hidden=True)
    @commands.is_owner()
    async def updateprestiege(
        self, ctx, user: discord.Member = None, which: int = 0, amount: int = 0
    ):
        if user is None:
            user = ctx.author
        async with self.client.session as session:
            async with session.begin():
                result = (
                    await session.scalars(
                        select(models.economy.Prestiege).where(
                            models.economy.Prestiege.user_id == user.id
                        )
                    )
                ).one_or_none()

                if result:
                    setattr(result, f"pres{which}", amount)
                else:
                    session.add(models.economy.Prestiege(user_id=user.id))

        await ctx.send(await econ.get_prestiege(user))

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(
                f"This command is on cooldown, you can use it "
                f"<t:{int(time.time()) + int(error.retry_after) + 3}:R>"
            )
        elif isinstance(error, commands.MaxConcurrencyReached):
            await ctx.reply(
                "Too many people are using this command! Please try again later."
            )
        elif isinstance(error, commands.NSFWChannelRequired):
            await ctx.reply("<:weirdchamp:1037242286439931974>")
        elif isinstance(error, commands.CommandNotFound):
            return
        elif isinstance(error, commands.UserNotFound):
            await ctx.reply(
                "The specified user was not found. Did you type the name correctly? Try pinging them or pasting their ID."
            )
            ctx.command.reset_cooldown(ctx)
        elif isinstance(error, commands.NotOwner):
            return
        elif isinstance(error, commands.UserNotFound) or isinstance(
            error, commands.MemberNotFound
        ):
            await ctx.reply("The person you specified was not found! Try pinging them.")
            ctx.command.reset_cooldown(ctx)
        elif isinstance(error, commands.BadArgument):
            ctx.command.reset_cooldown(ctx)
            await ctx.reply("One of the arguments you specified was not valid.")
        elif isinstance(error, commands.MissingPermissions):
            ctx.command.reset_cooldown(ctx)
            await ctx.reply(
                "You lack the appropriate permissions to perform this command."
            )
        elif isinstance(error, commands.MissingRequiredArgument):
            ctx.command.reset_cooldown(ctx)
            await ctx.reply(error)  # this one is perfect by default
        elif isinstance(error, commands.UnexpectedQuoteError) or isinstance(
            error, commands.InvalidEndOfQuotedStringError
        ):
            ctx.command.reset_cooldown(ctx)
            await ctx.reply("You did not close a quote in your arguments!")
        else:
            ctx.command.reset_cooldown(ctx)
            channel = await self.client.fetch_channel(
                config["channels"]["error_reporting_channel"]
            )
            embed = discord.Embed(
                title="An Error has occurred",
                description=f"Error: \n `{error}`\nCommand: `{ctx.command}`",
                timestamp=ctx.message.created_at,
                color=242424,
            )
            await channel.send(embed=embed)
            print(error)
            traceback.print_exception(
                type(error), error, error.__traceback__, file=sys.stderr
            )
            print("-" * 20)
            await ctx.reply("An unexpected error occurred! Please try again.")


async def setup(client):
    await client.add_cog(Economy(client))
