"""Entry point: bot setup, command sync, and the event loop."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
import db

log = logging.getLogger("remindlet")


@app_commands.command(description="Check that the bot is alive.")
async def ping(interaction: discord.Interaction) -> None:
    latency_ms = round(interaction.client.latency * 1000)
    await interaction.response.send_message(f"Pong! ({latency_ms} ms)")


class ReminderBot(commands.Bot):
    def __init__(self, guild_id: int) -> None:
        # Slash commands need no privileged intents. The prefix is a placeholder:
        # commands.Bot requires one, but we only use app commands.
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.default(),
        )
        self.guild = discord.Object(id=guild_id)

    async def setup_hook(self) -> None:
        # Runs once, before connecting. on_ready can fire again on reconnect.
        self.db = db.connect(config.DB_PATH)
        log.info("Opened database %s", config.DB_PATH)
        await self.load_extension("cogs.timezone")
        self.tree.add_command(ping)
        self.tree.copy_global_to(guild=self.guild)
        synced = await self.tree.sync(guild=self.guild)
        log.info("Synced %d command(s) to guild %s", len(synced), self.guild.id)

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id %s)", self.user, self.user.id)

    async def close(self) -> None:
        await super().close()
        if hasattr(self, "db"):
            self.db.close()


def main() -> None:
    if not config.DISCORD_TOKEN or config.GUILD_ID is None:
        raise SystemExit("DISCORD_TOKEN and GUILD_ID must be set in .env")
    bot = ReminderBot(config.GUILD_ID)
    bot.run(config.DISCORD_TOKEN, root_logger=True)


if __name__ == "__main__":
    main()
