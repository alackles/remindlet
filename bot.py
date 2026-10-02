"""Entry point: bot setup, command sync, and the event loop."""

import logging

import discord
from discord.ext import commands

import config
import db

log = logging.getLogger("remindlet")


class ReminderBot(commands.Bot):
    def __init__(self, guild_id: int) -> None:
        # The members intent (privileged: also enabled in the Developer Portal)
        # keeps every server member cached, so names never need an API call.
        intents = discord.Intents.default()
        intents.members = True
        # The prefix is a placeholder: commands.Bot requires one, but we only
        # use app commands.
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            # Never ping @everyone/@here or roles, even if reminder text has them.
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
        )
        self.guild = discord.Object(id=guild_id)

    async def setup_hook(self) -> None:
        # Runs once, before connecting. on_ready can fire again on reconnect.
        self.db = db.connect(config.DB_PATH)
        log.info("Opened database %s", config.DB_PATH)
        await self.load_extension("cogs.timezone")
        await self.load_extension("cogs.reminders")
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
