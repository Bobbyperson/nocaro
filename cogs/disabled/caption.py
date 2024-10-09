import json
import os
import random
import shutil
import subprocess

import discord
import requests
from discord.ext import commands
from ffmpy import FFmpeg
from PIL import Image, ImageDraw, ImageFont
from pyquery import PyQuery

# the resulting frames and gifs could probably just be held in memory but io is scary


def gifCaption(file, caption, endname):
    if not os.path.exists(f"giffers/{endname}"):
        os.makedirs(f"giffers/{endname}")
    if not os.path.exists(f"giffers/{endname}/out"):
        os.mkdir(f"giffers/{endname}/out")
    if "\\n" in caption:
        caption = caption.replace("\\n", "\n")
    fps = str(probeFile(file))
    pos = fps.rfind("fps")
    cpos = pos
    while fps[cpos] != ",":  # determine FPS of gif
        cpos -= 1
    fps = float(fps[cpos + 2 : pos - 1])
    folder = gifToImages(file)
    for image in os.listdir(folder):
        im = Image.open(f"./{folder}/{image}")
        width, height = im.size
        fontsize = 42
        my_font = ImageFont.truetype("Montserrat-Bold.ttf", fontsize)
        captionzone = 0
        newlines = caption.count("\n")
        captionzone = 34 * (newlines + 2)
        background = Image.new(
            "RGBA", (width, height + captionzone), (255, 255, 255, 255)
        )
        draw = ImageDraw.Draw(background)
        w, h = draw.textsize(caption, font=my_font)
        while w > width:
            if fontsize == 1:
                break
            if captionzone < 3:
                break
            fontsize -= 1
            captionzone -= 2
            my_font = ImageFont.truetype("Montserrat-Bold.ttf", fontsize)
            background = Image.new(
                "RGBA", (width, height + captionzone), (255, 255, 255, 255)
            )
            draw = ImageDraw.Draw(background)
            w, h = draw.textsize(caption, font=my_font)
        draw.text(
            ((width - w) / 2, 5), caption, (0, 0, 0), font=my_font, align="center"
        )
        background.paste(im, (0, captionzone))
        background.save(f"./giffers/{endname}/out/{image[:-4]}.png")
    ff = FFmpeg(
        inputs={
            f"giffers/{endname}/out/{image[:-8]}%04d.png": f"-f image2 -framerate {fps}",
        },
        outputs={f"{folder}/out.mp4": ""},
    )
    ff.run()
    ff = FFmpeg(
        inputs={
            f"{folder}/out.mp4": "",
        },
        outputs={f"{folder}/palette.png": "-vf palettegen"},
    )
    ff.run()
    ff = FFmpeg(
        inputs={
            f"{folder}/out.mp4": "",
            f"{folder}/palette.png": "-filter_complex paletteuse -r 10",
        },
        outputs={f"giffers/{endname}/{endname}a.gif": ""},
    )
    ff.run()
    fs1 = os.path.getsize(f"giffers/{endname}/{endname}a.gif")
    width, height = background.size
    while fs1 > 8388608:
        os.remove(f"giffers/{endname}/{endname}a.gif")
        ff = FFmpeg(
            inputs={f"{folder}/out.mp4": ""},
            outputs={
                f"giffers/{endname}/{endname}a.gif": f"-vf scale={width}:{height}"
            },
        )
        ff.run()
        fs1 = os.path.getsize(f"giffers/{endname}/{endname}a.gif")
        width = int(width / 2)
        height = int(height / 2)
        if width % 2 != 0:
            width += 1
        if height % 2 != 0:
            height += 1
    shutil.rmtree(folder)
    for file in os.listdir(f"./giffers/{endname}/out"):
        os.remove(f"./giffers/{endname}/out/{file}")


def imageCaption(file, caption, endname):  # 95% chance i will not make this func
    if "\\n" in caption:
        caption = caption.replace("\\n", "\n")
    im = Image.open(f"./{file}")
    width, height = im.size
    fontsize = 42
    my_font = ImageFont.truetype("Montserrat-Bold.ttf", fontsize)
    captionzone = 0
    newlines = caption.count("\n")
    captionzone = 33 * (newlines + 2)
    background = Image.new("RGBA", (width, height + captionzone), (255, 255, 255, 255))
    draw = ImageDraw.Draw(background)
    w, h = draw.textsize(caption, font=my_font)
    while w > width:  # reduce font size till yeah that fits
        if fontsize == 1:
            break
        if captionzone < 3:
            break
        fontsize -= 1
        captionzone -= 2
        my_font = ImageFont.truetype("Montserrat-Bold.ttf", fontsize)
        background = Image.new(
            "RGBA", (width, height + captionzone), (255, 255, 255, 255)
        )
        draw = ImageDraw.Draw(background)
        w, h = draw.textsize(caption, font=my_font)
    draw.text(((width - w) / 2, 5), caption, (0, 0, 0), font=my_font, align="center")
    background.paste(im, (0, captionzone))
    background.save(f"./giffers/{endname}/{endname}a.png")


def gifToImages(input):
    tempfolder = str(random.randint(0, 10000000))  # sucks
    os.mkdir(tempfolder)
    ff = FFmpeg(
        inputs={input: None},
        outputs={f"{tempfolder}/%04d.png": ""},
    )
    ff.run()
    return tempfolder


def probeFile(filename):
    cmnd = ["ffprobe", "-show_format", "-pretty", filename]
    p = subprocess.Popen(cmnd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print(filename)
    out, err = p.communicate()
    if err:
        print(err)
        return err
    return err


class Caption(commands.Cog):
    def __init__(self, client):
        self.client = client

    @commands.command(hidden=True)
    @commands.max_concurrency(1, per=commands.BucketType.user, wait=False)
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def caption(self, ctx, *, caption: str = None):
        if caption is None:
            await ctx.reply("Please provide a caption!")
            return
        if ctx.message.reference:
            original = await ctx.fetch_message(ctx.message.reference.message_id)
            if original.attachments:
                file = original.attachments[0]
                spoiler = file.is_spoiler()
                if not spoiler and file.url.lower().split("?")[0].endswith("gif"):
                    await ctx.reply(
                        "ok im workin on it, if this fails you will NOT be alerted. this does NOT mean spam the command."
                    )
                    spliff = requests.get(file.url)
                    with open(f"{ctx.message.author.id}.gif", "wb") as f:
                        f.write(spliff.content)
                    await self.client.loop.run_in_executor(
                        None,
                        gifCaption,
                        f"{ctx.message.author.id}.gif",
                        caption,
                        ctx.message.author.id,
                    )
                    await ctx.reply(
                        file=discord.File(
                            fp=f"giffers/{ctx.message.author.id}/{ctx.message.author.id}a.gif",
                            filename="urgif.gif",
                        ),
                    )
                    os.remove(
                        f"giffers/{ctx.message.author.id}/{ctx.message.author.id}a.gif"
                    )
                    os.remove(f"{ctx.message.author.id}.gif")
                elif not spoiler and file.url.lower().endswith(
                    ("png", "jpeg", "jpg")
                ):  # test
                    await ctx.reply(
                        "ok im workin on it, if this fails you will NOT be alerted. this does NOT mean spam the command."
                    )
                    spliff = requests.get(file.url)
                    with open(f"{ctx.message.author.id}.png", "wb") as f:
                        f.write(spliff.content)
                    await self.client.loop.run_in_executor(
                        None,
                        imageCaption,
                        f"{ctx.message.author.id}.png",
                        caption,
                        ctx.message.author.id,
                    )
                    await ctx.reply(
                        file=discord.File(
                            fp=f"giffers/{ctx.message.author.id}/{ctx.message.author.id}a.png",
                            filename="urimg.png",
                        ),
                    )
                    os.remove(
                        f"giffers/{ctx.message.author.id}/out/{ctx.message.author.id}a.png"
                    )
                    os.remove(f"{ctx.message.author.id}.gif")
            elif original.content.startswith("https://tenor.com/"):
                await ctx.reply(
                    "ok im workin on it, if this fails you will NOT be alerted. this does NOT mean spam the command."
                )
                res = requests.get(original.content)
                pq = PyQuery(res.text)
                jsonData = pq("#store-cache")
                data = json.loads(jsonData.html())
                print(data)
                id = original.content.split("-")[-1]
                results = data["gifs"]["byId"][id]["results"][0]
                url = results["media"][0]["gif"]["url"]
                spliff = requests.get(url)
                with open(f"{ctx.message.author.id}.gif", "wb") as f:
                    f.write(spliff.content)
                await self.client.loop.run_in_executor(
                    None,
                    gifCaption,
                    f"{ctx.message.author.id}.gif",
                    caption,
                    ctx.message.author.id,
                )
                await ctx.reply(
                    file=discord.File(
                        fp=f"giffers/{ctx.message.author.id}/{ctx.message.author.id}a.gif",
                        filename="urgif.gif",
                    ),
                )
                os.remove(
                    f"giffers/{ctx.message.author.id}/{ctx.message.author.id}a.gif"
                )
                os.remove(f"{ctx.message.author.id}.gif")
        elif ctx.message.attachments:
            file = ctx.message.attachments[0]
            spoiler = file.is_spoiler()
            if not spoiler and file.url.lower().endswith("gif"):
                await ctx.reply(
                    "ok im workin on it, if this fails you will NOT be alerted. this does NOT mean spam the command."
                )
                spliff = requests.get(file.url)
                with open(f"{ctx.message.author.id}.gif", "wb") as f:
                    f.write(spliff.content)
                await self.client.loop.run_in_executor(
                    None,
                    gifCaption,
                    f"{ctx.message.author.id}.gif",
                    caption,
                    ctx.message.author.id,
                )
                await ctx.reply(
                    file=discord.File(
                        fp=f"giffers/{ctx.message.author.id}/{ctx.message.author.id}a.gif",
                        filename="urgif.gif",
                    ),
                )
                os.remove(
                    f"giffers/{ctx.message.author.id}/{ctx.message.author.id}a.gif"
                )
                os.remove(f"{ctx.message.author.id}.gif")
            else:
                await ctx.reply("Nope!")
                return
        else:
            await ctx.reply("Please provide a gif.")


async def setup(client):
    await client.add_cog(Caption(client))
