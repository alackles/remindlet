"""Entry point: bot setup, command sync, and the event loop."""

import logging

import discord
from discord.ext import commands

import config
import db

log = logging.getLogger("remindlet")


class ReminderBot(commands.Bot):
    def __init__(self, guild_ids: list[int]) -> None:
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
        # Not `self.guilds`: discord.Client already has that (servers it's in).
        self.guild_ids = guild_ids

    async def setup_hook(self) -> None:
        # Runs once, before connecting. on_ready can fire again on reconnect.
        self.db = db.connect(config.DB_PATH)
        log.info("Opened database %s", config.DB_PATH)
        await self.load_extension("cogs.timezone")
        await self.load_extension("cogs.reminders")
        for guild_id in self.guild_ids:
            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            try:
                synced = await self.tree.sync(guild=guild)
            except discord.Forbidden:
                # Not invited yet, or removed. Keep serving the other servers.
                log.error("Can't sync commands to guild %s: is the bot in it?", guild_id)
                continue
            log.info("Synced %d command(s) to guild %s", len(synced), guild_id)

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id %s)", self.user, self.user.id)

    async def close(self) -> None:
        await super().close()
        if hasattr(self, "db"):
            self.db.close()


def main() -> None:
    if not config.DISCORD_TOKEN or not config.GUILD_IDS:
        raise SystemExit(
            "DISCORD_TOKEN and GUILD_IDS must be set in .env "
            "(GUILD_IDS, comma-separated, replaced GUILD_ID)"
        )
    bot = ReminderBot(config.GUILD_IDS)
    bot.run(config.DISCORD_TOKEN, root_logger=True)


if __name__ == "__main__":
    main()
