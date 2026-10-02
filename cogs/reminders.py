"""/remind, /reschedule, /snooze, /cancel, /done, /list, and firing reminders
when the scheduler says they're due."""

import asyncio
import logging
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import db
import formatting
import time_parser
from scheduler import Scheduler

log = logging.getLogger(__name__)

NO_PINGS = discord.AllowedMentions.none()
CLOSED_VERBS = {"done": "completed", "cancelled": "cancelled"}


def _name(member: discord.abc.User) -> str:
    return discord.utils.escape_markdown(member.display_name)


def _parse_id(text: str) -> int | None:
    text = text.strip().lstrip("#")
    return int(text) if text.isdigit() else None


class Reminders(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.scheduler = Scheduler(bot.db, self.fire)
        self._starter: asyncio.Task | None = None
        # Display names seen so far. Without the privileged members intent
        # there's no member cache, and autocomplete can't wait on API calls.
        self._names: dict[int, str] = {}

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

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Runs before every command in this cog: remember who we've seen.
        self._remember(interaction.user)
        return True

    def _remember(self, *members: discord.abc.User | None) -> None:
        for m in members:
            if m is not None:
                self._names[m.id] = _name(m)

    async def _member_name(self, guild_id: int | str, user_id: int | str) -> str:
        """Display name, from what we've seen or the API; a non-pinging mention
        as a last resort (every send here restricts who can be pinged)."""
        user_id = int(user_id)
        if user_id in self._names:
            return self._names[user_id]
        guild = self.bot.get_guild(int(guild_id))
        if guild is not None:
            try:
                self._remember(guild.get_member(user_id) or await guild.fetch_member(user_id))
                return self._names[user_id]
            except discord.HTTPException:
                pass
        return formatting.mention(user_id)

    # --- /remind -----------------------------------------------------------------

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
        self._remember(who, also, also2)
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
                formatting.Created(rid, t.id, p.fire_at, p.zone)
                for rid, t, p in zip(ids, targets, parsed)
            ],
            now=now,
        )
        await interaction.response.send_message(
            text, allowed_mentions=discord.AllowedMentions(users=targets)
        )

    # --- Changing a reminder -------------------------------------------------------

    async def _lookup(self, interaction: discord.Interaction, id_text: str) -> sqlite3.Row | None:
        """Find a reminder in this server by the `id` option, or reply with why not."""
        rid = _parse_id(id_text)
        row = db.get_reminder(self.bot.db, rid) if rid is not None else None
        if row is None or row["guild_id"] != str(interaction.guild_id):
            await interaction.response.send_message(
                f"There's no reminder `{id_text}`. `/list` shows open ones.", ephemeral=True
            )
            return None
        return row

    async def _closed_message(self, error: db.ReminderClosed) -> str:
        row = error.row
        text = f"Reminder #{row['id']} was already {CLOSED_VERBS[row['status']]}"
        if error.closed_by:
            text += f" by {await self._member_name(row['guild_id'], error.closed_by)}"
        return text + "."

    async def _apply(
        self,
        interaction: discord.Interaction,
        row: sqlite3.Row,
        change: Callable[[], sqlite3.Row],
        header: str,
        *,
        show_time: bool = False,
        reason: str | None = None,
        show_siblings: bool = False,
    ) -> None:
        """Run a state change and announce it in the reminder's channel."""
        try:
            row = change()
        except db.ReminderClosed as e:
            await interaction.response.send_message(await self._closed_message(e), ephemeral=True)
            return
        self.scheduler.wake()

        siblings = []
        if show_siblings:
            for sib in db.open_siblings(self.bot.db, row):
                siblings.append((await self._member_name(sib["guild_id"], sib["target_id"]), sib["id"]))
        note = formatting.audit_note(
            header=header,
            target_id=row["target_id"],
            message=row["message"],
            fire_at=db.from_iso(row["fire_at"]) if show_time else None,
            zone=row["original_tz"],
            now=datetime.now(timezone.utc),
            reason=reason,
            siblings=siblings,
        )
        target = int(row["target_id"])
        mentions = (
            NO_PINGS if target == interaction.user.id
            else discord.AllowedMentions(users=[discord.Object(target)])
        )
        await self._announce(interaction, int(row["channel_id"]), note, mentions)

    async def _announce(
        self,
        interaction: discord.Interaction,
        channel_id: int,
        note: str,
        mentions: discord.AllowedMentions,
    ) -> None:
        """Post in the reminder's channel: as the reply if we're already there,
        otherwise directly, with a private pointer for the person who asked."""
        if interaction.channel_id == channel_id:
            await interaction.response.send_message(note, allowed_mentions=mentions)
            return
        try:
            channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            await channel.send(note, allowed_mentions=mentions)
        except discord.HTTPException:
            log.warning("Couldn't post in channel %s; announcing here instead", channel_id)
            await interaction.response.send_message(note, allowed_mentions=mentions)
            return
        await interaction.response.send_message(f"Done. Posted in <#{channel_id}>.", ephemeral=True)

    @app_commands.command(description="Move a reminder to a new time.")
    @app_commands.rename(id_="id")
    @app_commands.describe(
        id_="Which reminder (start typing a number or words from it)",
        when="New time, e.g. tomorrow 9am. Your timezone unless you add `their time` or a zone",
        reason="Optional; posted with the change",
    )
    async def reschedule(
        self,
        interaction: discord.Interaction,
        id_: str,
        when: str,
        reason: app_commands.Range[str, 1, 200] | None = None,
    ) -> None:
        if (row := await self._lookup(interaction, id_)) is None:
            return
        actor_tz = db.get_timezone(self.bot.db, interaction.user.id)
        if actor_tz is None:
            await interaction.response.send_message(
                "Run `/timezone set` first, so I know what your times mean.", ephemeral=True
            )
            return
        target_tz = db.get_timezone(self.bot.db, int(row["target_id"]))
        try:
            parsed = time_parser.parse_when(
                when, creator_tz=actor_tz, target_tz=target_tz, now=datetime.now(timezone.utc)
            )
        except time_parser.ParseError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        await self._apply(
            interaction,
            row,
            lambda: db.reschedule(
                self.bot.db, row["id"], actor_id=interaction.user.id, fire_at=parsed.fire_at,
                original_tz=parsed.zone, original_time_str=parsed.display, reason=reason,
            ),
            f"🔄 {_name(interaction.user)} rescheduled reminder #{row['id']}",
            show_time=True,
            reason=reason,
            show_siblings=True,
        )

    @app_commands.command(description="Push a reminder back by a while.")
    @app_commands.rename(id_="id")
    @app_commands.describe(
        id_="Which reminder (start typing a number or words from it)",
        duration="e.g. 15m, 1h, 1h30m, 1d",
    )
    async def snooze(self, interaction: discord.Interaction, id_: str, duration: str) -> None:
        if (row := await self._lookup(interaction, id_)) is None:
            return
        try:
            length = time_parser.parse_duration(duration)
        except time_parser.ParseError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        await self._apply(
            interaction,
            row,
            lambda: db.snooze(
                self.bot.db, row["id"], actor_id=interaction.user.id, duration=length,
                now=datetime.now(timezone.utc),
            ),
            f"💤 {_name(interaction.user)} snoozed reminder #{row['id']} "
            f"for {time_parser.format_duration(length)}",
            show_time=True,
        )

    @app_commands.command(description="Cancel a reminder.")
    @app_commands.rename(id_="id")
    @app_commands.describe(
        id_="Which reminder (start typing a number or words from it)",
        reason="Optional; posted with the cancellation",
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        id_: str,
        reason: app_commands.Range[str, 1, 200] | None = None,
    ) -> None:
        if (row := await self._lookup(interaction, id_)) is None:
            return
        await self._apply(
            interaction,
            row,
            lambda: db.cancel(self.bot.db, row["id"], actor_id=interaction.user.id, reason=reason),
            f"❌ {_name(interaction.user)} cancelled reminder #{row['id']}",
            reason=reason,
            show_siblings=True,
        )

    @app_commands.command(description="Mark a reminder as done.")
    @app_commands.rename(id_="id")
    @app_commands.describe(id_="Which reminder (start typing a number or words from it)")
    async def done(self, interaction: discord.Interaction, id_: str) -> None:
        if (row := await self._lookup(interaction, id_)) is None:
            return
        await self._apply(
            interaction,
            row,
            lambda: db.complete(self.bot.db, row["id"], actor_id=interaction.user.id),
            f"✅ {_name(interaction.user)} completed reminder #{row['id']}",
        )

    @reschedule.autocomplete("id_")
    @snooze.autocomplete("id_")
    @cancel.autocomplete("id_")
    @done.autocomplete("id_")
    async def id_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        query = current.strip().lstrip("#").lower()
        now = datetime.now(timezone.utc)
        choices = []
        for row in db.list_open(self.bot.db, interaction.guild_id):
            name = self._names.get(int(row["target_id"]), "")
            if query and not (
                str(row["id"]).startswith(query)
                or query in row["message"].lower()
                or query in name.lower()
            ):
                continue
            fire_at = db.from_iso(row["fire_at"])
            when = (
                f"{formatting.short_date(fire_at, row['original_tz'], now)}, "
                f"{time_parser.format_in_zone(fire_at, row['original_tz'])}"
            )
            who = f"{name}: " if name else ""
            label = f"#{row['id']} {who}{row['message']}"
            suffix = f" ({when})"
            label = label[: 100 - len(suffix) - 1] + "…" + suffix if len(label) + len(suffix) > 100 else label + suffix
            choices.append(app_commands.Choice(name=label, value=str(row["id"])))
            if len(choices) == 25:
                break
        return choices

    # --- /list ----------------------------------------------------------------------

    @app_commands.command(name="list", description="Show open reminders (only you see this).")
    @app_commands.rename(from_="from")
    @app_commands.describe(who="Only reminders for this person", from_="Only reminders from this person")
    async def list_(
        self,
        interaction: discord.Interaction,
        who: discord.Member | None = None,
        from_: discord.Member | None = None,
    ) -> None:
        self._remember(who, from_)
        rows = db.list_open(
            self.bot.db,
            interaction.guild_id,
            target_id=who.id if who else None,
            creator_id=from_.id if from_ else None,
        )
        title = (f" for {who.mention}" if who else "") + (f" from {from_.mention}" if from_ else "")
        text = formatting.reminder_list(rows, title=title, now=datetime.now(timezone.utc))
        await interaction.response.send_message(text, ephemeral=True, allowed_mentions=NO_PINGS)

    # --- Firing -----------------------------------------------------------------------

    async def fire(self, row: sqlite3.Row) -> None:
        """Post a due reminder in its channel. Called by the scheduler."""
        channel_id = int(row["channel_id"])
        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        target = discord.Object(int(row["target_id"]))
        fire_at = db.from_iso(row["fire_at"])
        text = formatting.fired(
            target_id=target.id,
            message=row["message"],
            creator_name=await self._member_name(row["guild_id"], row["creator_id"]),
            fire_at=fire_at,
            zone=row["original_tz"],
            now=datetime.now(timezone.utc),
        )
        await channel.send(text, allowed_mentions=discord.AllowedMentions(users=[target]))
        log.info("Fired reminder #%s", row["id"])


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Reminders(bot))
