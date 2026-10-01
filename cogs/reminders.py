"""/remind, and firing reminders when the scheduler says they're due."""

import asyncio
import logging
import sqlite3
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import db
import formatting
import time_parser
from scheduler import Scheduler

log = logging.getLogger(__name__)


def _name(member: discord.abc.User) -> str:
    return discord.utils.escape_markdown(member.display_name)


class Reminders(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.scheduler = Scheduler(bot.db, self.fire)
        self._starter: asyncio.Task | None = None

    async def cog_load(self) -> None:
        # Channels aren't known until the bot is ready, and setup_hook (where
        # cogs load) must finish before that can happen, so start in a task.
        self._starter = asyncio.create_task(self._start_when_ready())

    async def _start_when_ready(self) -> None:
        await self.bot.wait_until_ready()
        self.scheduler.start()
        log.info("Scheduler started")

    async def cog_unload(self) -> None:
        if self._starter is not None:
            self._starter.cancel()
        await self.scheduler.stop()

    @app_commands.command(description="Remind someone (or yourself) about something.")
    @app_commands.describe(
        who="Who to remind",
        when="e.g. 9am, tomorrow 3pm, friday 9am their time, oct 3 10am ET, in 2 hours",
        what="What to remind them about",
        also="Someone else to remind at the same time",
        also2="A third person to remind",
    )
    async def remind(
        self,
        interaction: discord.Interaction,
        who: discord.Member,
        when: str,
        what: app_commands.Range[str, 1, 500],
        also: discord.Member | None = None,
        also2: discord.Member | None = None,
    ) -> None:
        conn = self.bot.db
        targets = list({m.id: m for m in (who, also, also2) if m is not None}.values())

        if bots := [t for t in targets if t.bot]:
            names = ", ".join(_name(b) for b in bots)
            await interaction.response.send_message(f"Bots can't be reminded: {names}.", ephemeral=True)
            return

        creator_tz = db.get_timezone(conn, interaction.user.id)
        target_tzs = {t.id: db.get_timezone(conn, t.id) for t in targets}
        missing = (["you"] if creator_tz is None else []) + [
            _name(t) for t in targets if target_tzs[t.id] is None and t.id != interaction.user.id
        ]
        if missing:
            await interaction.response.send_message(
                "Nothing was created. These people need to run `/timezone set` first: "
                + ", ".join(missing) + ".",
                ephemeral=True,
            )
            return

        now = datetime.now(timezone.utc)
        try:
            parsed = [
                time_parser.parse_when(when, creator_tz=creator_tz, target_tz=target_tzs[t.id], now=now)
                for t in targets
            ]
        except time_parser.ParseError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        ids = db.create_reminders(
            conn,
            creator_id=interaction.user.id,
            channel_id=interaction.channel_id,
            guild_id=interaction.guild_id,
            message=what,
            targets=[
                db.NewReminder(t.id, p.fire_at, p.zone, p.display) for t, p in zip(targets, parsed)
            ],
        )
        self.scheduler.wake()

        text = formatting.confirmation(
            message=what,
            creator_name=_name(interaction.user),
            channel_id=interaction.channel_id,
            created=[
                formatting.Created(rid, t.id, p.display, p.fire_at, p.zone)
                for rid, t, p in zip(ids, targets, parsed)
            ],
            now=now,
        )
        await interaction.response.send_message(
            text, allowed_mentions=discord.AllowedMentions(users=targets)
        )

    async def fire(self, row: sqlite3.Row) -> None:
        """Post a due reminder in its channel. Called by the scheduler."""
        channel_id = int(row["channel_id"])
        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        target = discord.Object(int(row["target_id"]))
        text = formatting.fired(
            target_id=target.id,
            message=row["message"],
            creator_name=await self._creator_name(row),
            display=row["original_time_str"],
            fire_at=db.from_iso(row["fire_at"]),
            now=datetime.now(timezone.utc),
        )
        await channel.send(text, allowed_mentions=discord.AllowedMentions(users=[target]))
        log.info("Fired reminder #%s", row["id"])

    async def _creator_name(self, row: sqlite3.Row) -> str:
        # The member cache is empty without the privileged members intent, so
        # ask the API; fall back to a mention (which won't ping: see fire()).
        guild = self.bot.get_guild(int(row["guild_id"]))
        creator_id = int(row["creator_id"])
        if guild is not None:
            try:
                return _name(guild.get_member(creator_id) or await guild.fetch_member(creator_id))
            except discord.HTTPException:
                pass
        return formatting.mention(creator_id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Reminders(bot))
