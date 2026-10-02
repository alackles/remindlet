"""/remind, /reschedule, /snooze, /cancel, /done, /list, the buttons on fired
reminders, and firing reminders when they come due."""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import db
import formatting
import time_parser
import scheduler

log = logging.getLogger(__name__)

NO_PINGS = discord.AllowedMentions.none()
CLOSED_VERBS = {"done": "completed", "cancelled": "cancelled"}


def _name(member: discord.abc.User) -> str:
    return discord.utils.escape_markdown(member.display_name)


def _parse_id(text: str) -> int | None:
    text = text.strip().lstrip("#")
    return int(text) if text.isdigit() else None


# --- Buttons on fired reminders ----------------------------------------------------

BUTTONS = {
    "s15": ("Snooze 15m", discord.ButtonStyle.secondary),
    "s60": ("Snooze 1h", discord.ButtonStyle.secondary),
    "done": ("Done ✓", discord.ButtonStyle.success),
    "cancel": ("Cancel", discord.ButtonStyle.danger),
}
SNOOZES = {"s15": timedelta(minutes=15), "s60": timedelta(hours=1)}


class ReminderButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"rem:(?P<id>\d+):(?P<at>\d+):(?P<action>s15|s60|done|cancel)",
):
    """A button whose custom_id carries everything needed to handle a click:
    reminder ID, the fire time of the firing it belongs to, and the action.
    Registered with add_dynamic_items, so clicks work after restarts too."""

    def __init__(self, reminder_id: int, fire_unix: int, action: str) -> None:
        label, style = BUTTONS[action]
        super().__init__(
            discord.ui.Button(
                label=label, style=style, custom_id=f"rem:{reminder_id}:{fire_unix}:{action}"
            )
        )
        self.reminder_id = reminder_id
        self.fire_unix = fire_unix
        self.action = action

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["id"]), int(match["at"]), match["action"])

    async def callback(self, interaction: discord.Interaction) -> None:
        cog = interaction.client.get_cog("Reminders")
        await cog.on_button(interaction, self.reminder_id, self.fire_unix, self.action)


def reminder_buttons(reminder_id: int, fire_at: datetime) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for action in BUTTONS:
        view.add_item(ReminderButton(reminder_id, int(fire_at.timestamp()), action))
    return view


def button_problem(row: sqlite3.Row | None, fire_unix: int) -> str | None:
    """Why a button can't act, or None if it can.

    A button belongs to one firing. It's live only while the reminder is still
    in that firing: status 'fired' with the same fire time.
    """
    if row is None:
        return "missing"
    if row["status"] not in db.OPEN:
        return "closed"
    if row["status"] != "fired" or int(db.from_iso(row["fire_at"]).timestamp()) != fire_unix:
        return "moved"
    return None


class Reminders(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # Display names seen so far. Without the privileged members intent
        # there's no member cache, and autocomplete can't wait on API calls.
        self._names: dict[int, str] = {}

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(ReminderButton)
        self.poll.start()

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(ReminderButton)
        self.poll.cancel()

    @tasks.loop(seconds=scheduler.POLL_SECONDS)
    async def poll(self) -> None:
        try:
            await scheduler.fire_due(self.bot.db, self.fire, datetime.now(timezone.utc))
        except Exception:
            # An uncaught error would stop the loop for good; log and keep polling.
            log.exception("Polling for due reminders failed")

    @poll.before_loop
    async def before_poll(self) -> None:
        # Channels aren't known until the bot has connected.
        await self.bot.wait_until_ready()

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
        """Find an open reminder in this server by the `id` option, or reply
        privately with why not and return None."""
        rid = _parse_id(id_text)
        row = db.get_reminder(self.bot.db, rid) if rid is not None else None
        if row is None or row["guild_id"] != str(interaction.guild_id):
            text = f"There's no reminder `{id_text}`. `/list` shows open ones."
        elif row["status"] not in db.OPEN:
            text = await self._closed_text(row)
        else:
            return row
        await interaction.response.send_message(text, ephemeral=True)
        return None

    async def _closed_text(self, row: sqlite3.Row) -> str:
        text = f"Reminder #{row['id']} was already {CLOSED_VERBS[row['status']]}"
        if closer_id := db.closed_by(self.bot.db, row["id"]):
            text += f" by {await self._member_name(row['guild_id'], closer_id)}"
        return text + "."

    async def _note(
        self,
        row: sqlite3.Row,
        header: str,
        actor_id: int,
        *,
        show_time: bool = False,
        reason: str | None = None,
        show_siblings: bool = False,
    ) -> tuple[str, discord.AllowedMentions]:
        """The audit note for a change just made, and who it may ping: the
        target, unless they made the change themselves."""
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
            NO_PINGS if target == actor_id else discord.AllowedMentions(users=[discord.Object(target)])
        )
        return note, mentions

    async def _announce_change(
        self, interaction: discord.Interaction, row: sqlite3.Row, header: str, **note_options
    ) -> None:
        """Announce a slash-command change (already made) in the reminder's channel."""
        note, mentions = await self._note(row, header, interaction.user.id, **note_options)
        await self._announce(interaction, int(row["channel_id"]), note, mentions)

    async def _send_to_channel(
        self, channel_id: int, note: str, mentions: discord.AllowedMentions
    ) -> bool:
        try:
            channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            await channel.send(note, allowed_mentions=mentions)
            return True
        except discord.HTTPException:
            log.warning("Couldn't post in channel %s", channel_id)
            return False

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
        elif await self._send_to_channel(channel_id, note, mentions):
            await interaction.response.send_message(f"Done. Posted in <#{channel_id}>.", ephemeral=True)
        else:
            await interaction.response.send_message(note, allowed_mentions=mentions)

    async def on_button(
        self, interaction: discord.Interaction, rid: int, fire_unix: int, action: str
    ) -> None:
        """Handle a click on a fired reminder's button (see ReminderButton)."""
        self._remember(interaction.user)
        conn = self.bot.db
        row = db.get_reminder(conn, rid)
        if (problem := button_problem(row, fire_unix)) is not None:
            await self._reject_button(interaction, rid, row, problem)
            return

        # No await between the check above and these changes, so no other
        # click can slip in between them.
        actor = _name(interaction.user)
        uid = interaction.user.id
        if action in SNOOZES:
            length = SNOOZES[action]
            row = db.snooze(conn, rid, actor_id=uid, duration=length, now=datetime.now(timezone.utc))
            header = f"💤 {actor} snoozed reminder #{rid} for {time_parser.format_duration(length)}"
            options = {"show_time": True}
        elif action == "done":
            row = db.complete(conn, rid, actor_id=uid)
            header = f"✅ {actor} completed reminder #{rid}"
            options = {}
        else:
            row = db.cancel(conn, rid, actor_id=uid)
            header = f"❌ {actor} cancelled reminder #{rid}"
            options = {"show_siblings": True}

        await interaction.response.edit_message(view=None)
        note, mentions = await self._note(row, header, uid, **options)
        if not await self._send_to_channel(int(row["channel_id"]), note, mentions):
            # Delivered by DM fallback, or the channel vanished since: note goes here.
            await interaction.followup.send(note, allowed_mentions=mentions)

    async def _reject_button(
        self, interaction: discord.Interaction, rid: int, row: sqlite3.Row | None, problem: str
    ) -> None:
        if problem == "missing":
            text = f"Reminder #{rid} no longer exists."
        elif problem == "closed":
            text = await self._closed_text(row)
        else:
            text = (
                f"Reminder #{rid} has moved since this message. "
                f"Use `/snooze {rid} <duration>` or `/done {rid}` instead."
            )
        await interaction.response.send_message(text, ephemeral=True)
        try:
            await interaction.message.edit(view=None)  # these buttons are dead; remove them
        except discord.HTTPException:
            pass

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
        row = db.reschedule(
            self.bot.db, row["id"], actor_id=interaction.user.id, fire_at=parsed.fire_at,
            original_tz=parsed.zone, original_time_str=parsed.display, reason=reason,
        )
        await self._announce_change(
            interaction,
            row,
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
        row = db.snooze(
            self.bot.db, row["id"], actor_id=interaction.user.id, duration=length,
            now=datetime.now(timezone.utc),
        )
        await self._announce_change(
            interaction,
            row,
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
        row = db.cancel(self.bot.db, row["id"], actor_id=interaction.user.id, reason=reason)
        await self._announce_change(
            interaction,
            row,
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
        row = db.complete(self.bot.db, row["id"], actor_id=interaction.user.id)
        await self._announce_change(
            interaction,
            row,
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
        """Post a due reminder in its channel, or DM the target if the channel
        is gone or off-limits. Called by poll() via scheduler.fire_due()."""
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
        buttons = reminder_buttons(row["id"], fire_at)
        channel_id = int(row["channel_id"])
        try:
            channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            await channel.send(
                text, view=buttons, allowed_mentions=discord.AllowedMentions(users=[target])
            )
            log.info("Fired reminder #%s", row["id"])
        except (discord.NotFound, discord.Forbidden):
            guild = self.bot.get_guild(int(row["guild_id"]))
            user = self.bot.get_user(target.id) or await self.bot.fetch_user(target.id)
            await user.send(
                text + "\n" + formatting.dm_fallback(channel_id, guild.name if guild else None),
                view=buttons,
            )
            log.warning("Channel %s unreachable; DMed reminder #%s", channel_id, row["id"])


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Reminders(bot))
