import os
import subprocess
import sys
import time
import tomllib

import discord
from discord.ext import commands

with open("config.toml", "rb") as f:
    config = tomllib.load(f)


class Example(commands.Cog):
    def __init__(self, client):
        self.client = client

    # events
    @commands.Cog.listener()
    async def on_ready(self):
        print("Example ready")

    @commands.command(aliases=["pong"], hidden=True)
    async def ping(self, ctx):
        """
        pong!
        :param ctx:
        :return: a message containing the API and websocket latency in ms.
        """
        start = time.perf_counter()
        message = await ctx.send("Ping...")
        end = time.perf_counter()
        duration = (end - start) * 1000
        await message.edit(
            content=f"🏓 Pong!\n"
            f"API Latency: `{round(duration)}ms`\n"
            f"Websocket Latency: `{round(self.client.latency * 1000)}ms`"
        )

    @commands.command(hidden=True)
    async def invite(self, ctx):
        await ctx.send(
            "https://discord.com/api/oauth2/authorize?client_id=746934062446542925&permissions=277632642112&scope=bot%20applications.commands"
        )

    @commands.command(hidden=True)
    async def bot(self, ctx):
        await ctx.send(",human")

    @commands.command(hidden=True)
    async def checkcommit(self, ctx):
        try:
            remote_url = (
                subprocess.check_output(["git", "config", "--get", "remote.origin.url"])
                .decode()
                .strip()
            )

            current_branch = (
                subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"])
                .decode()
                .strip()
            )

            subprocess.check_call(["git", "fetch"])

            commits_behind = int(
                subprocess.check_output(
                    [
                        "git",
                        "rev-list",
                        "--count",
                        f"{current_branch}..origin/{current_branch}",
                    ]
                )
                .decode()
                .strip()
            )

            commits_ahead = int(
                subprocess.check_output(
                    [
                        "git",
                        "rev-list",
                        "--count",
                        f"origin/{current_branch}..{current_branch}",
                    ]
                )
                .decode()
                .strip()
            )

            if remote_url.startswith("git@"):
                # Convert SSH to HTTPS
                remote_url = remote_url.replace("git@", "https://")
                remote_url = remote_url.replace(":", "/")
            if not remote_url.startswith("http://") and not remote_url.startswith(
                "https://"
            ):
                return await ctx.send("Could not determine the repository URL.")

            if remote_url.endswith(".git"):
                remote_url = remote_url[:-4]

            remote_commit_hash = (
                subprocess.check_output(
                    ["git", "rev-parse", f"origin/{current_branch}"]
                )
                .decode()
                .strip()
            )

            current_commit_hash = (
                subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
            )

            if remote_url:
                latest_commit_url = f"{remote_url}/commit/{remote_commit_hash}"
                current_commit_url = f"{remote_url}/commit/{current_commit_hash}"

            if commits_behind == 0 and commits_ahead == 0:
                await ctx.send(
                    f"✅ I am up to date with {current_branch}: [latest commit](<{latest_commit_url}>)"
                )
            elif commits_behind > 0 and commits_ahead == 0:
                view = UpdateButtonView(self.client)
                await ctx.send(
                    f"⚠️ I am [{commits_behind} commit(s)](<{current_commit_url}>) behind {current_branch}.",
                    view=view,
                )
            elif commits_ahead > 0 and commits_behind == 0:
                await ctx.send(
                    f"🛠️ I am {commits_ahead} commit(s) ahead of {current_branch}."
                )
            else:
                view = RebaseButtonView(self.client)
                await ctx.send(
                    "⚠️ The local and remote branches have diverged.",
                    view=view,
                )

        except Exception as e:
            await ctx.send(f"An error occurred: {e}")


class UpdateButton(discord.ui.Button):
    def __init__(self, client):
        super().__init__(label="Update Bot", style=discord.ButtonStyle.danger)
        self.client = client

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != config["general"]["owner_id"]:
            await interaction.response.send_message(
                "You do not have permission to update the bot.", ephemeral=True
            )
            return

        await interaction.response.send_message("Updating bot...", ephemeral=True)
        try:
            subprocess.check_call(["git", "pull"])
            await interaction.followup.send(
                "Bot updated. Restarting...", ephemeral=True
            )
            if "INVOCATION_ID" in os.environ:  # if running under systemd
                await self.client.close()
            else:
                os.execv(sys.executable, [sys.executable] + sys.argv)
        except subprocess.CalledProcessError as e:
            await interaction.followup.send(
                f"An error occurred during update: {e}", ephemeral=True
            )


class RebaseButton(discord.ui.Button):
    def __init__(self, client):
        super().__init__(label="Rebase Bot", style=discord.ButtonStyle.danger)
        self.client = client

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != config["general"]["owner_id"]:
            await interaction.response.send_message(
                "You do not have permission to rebase the bot.", ephemeral=True
            )
            return

        current_branch_name = (
            subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"])
            .decode()
            .strip()
        )

        await interaction.response.send_message("Rebasing bot...", ephemeral=True)
        try:
            subprocess.check_call(["git", "fetch"])
            subprocess.check_call(["git", "rebase", f"origin/{current_branch_name}"])
            await interaction.followup.send(
                "Bot rebased successfully. Restarting...", ephemeral=True
            )
            if "INVOCATION_ID" in os.environ:  # if running under systemd
                await self.client.close()
            else:
                os.execv(sys.executable, [sys.executable] + sys.argv)
        except subprocess.CalledProcessError as e:
            await interaction.followup.send(
                f"An error occurred during rebase: {e}", ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"An unexpected error occurred: {e}", ephemeral=True
            )


class UpdateButtonView(discord.ui.View):
    def __init__(self, client):
        super().__init__()
        self.add_item(UpdateButton(client))


class RebaseButtonView(discord.ui.View):
    def __init__(self, client):
        super().__init__()
        self.add_item(RebaseButton(client))


async def setup(client):
    await client.add_cog(Example(client))
