# Discord Reminder Bot — Spec

A shared-secretary reminder bot for a small research collaboration server.

## Overview

A Discord bot for a small research collaboration server (currently 3 users across Central and Eastern time zones). The mental model: a shared secretary that anyone can tell something, anyone can tell to reschedule, and anyone can tell to shut up. No ownership hierarchy, no permission gatekeeping.

The bot manages one-shot reminders that fire in the channel where they were created. Any user can create a reminder targeting any other user (or themselves). Any user can reschedule or cancel any reminder. All changes post a visible note in the channel so nothing disappears silently.

Built with discord.py and SQLite. Deployed on a VPS.

## Commands

| Command | Syntax | Description |
| --- | --- | --- |
| /timezone set | `/timezone set <zone>` | Set your timezone. Accepts IANA names (`America/Chicago`), with autocomplete suggestions as you type. Required before creating reminders or being the target of one. |
| /remind | `/remind who:@user when:<time> [qualifier] what:<message> [also:@user] [also2:@user]` | Create a reminder. Time defaults to creator's timezone. Optional qualifier in `when`: `their time`, `my time`, or an explicit timezone. Extra targets in `also`/`also2` create separate linked reminders. Elsewhere this spec abbreviates the syntax as `/remind @acacia 9am do the thing`. |
| /reschedule | `/reschedule id:<id> when:<time> [reason:<text>]` | Move a reminder to a new time. `when` is read like `/remind`'s, with the person rescheduling as "me": default and `my time` are their zone, `their time` is the target's. Optional reason is posted in the channel. |
| /cancel | `/cancel id:<id> [reason:<text>]` | Cancel a reminder. Optional reason is posted in the channel. |
| /snooze | `/snooze id:<id> duration:<duration>` | Push a reminder back by a duration (`15m`, `1h`, `2h`, `1h30m`, `1d`), counted from its due time or from now, whichever is later. Also available as buttons on fired reminders. |
| /done | `/done id:<id>` | Mark a reminder completed. Same as the Done button, and still works after a restart has made the buttons inert. |
| /list | `/list [who:@user] [from:@user]` | List open reminders, visible only to the person asking. No args = all server reminders. `who` filters by target, `from` by creator. Two sections: upcoming (sorted by fire time, soonest first), then fired but not marked done. |

In every command that takes an `id`, the field autocompletes with matching open reminders (`#12 acacia: submit IRB revision`). Commands that change a reminder work on any open reminder (`pending` or `fired`); a reminder that is `done` or `cancelled` is closed, and acting on it is an error.

## Timezone System

Per-user timezones stored in the database. Discord does not expose user timezone settings to bots, so each user must run `/timezone set` before creating reminders. If a user tries to create a reminder without a stored timezone, the bot prompts them to set one rather than silently defaulting to UTC. Likewise, a user cannot be the target of a reminder until they have set a timezone; the bot tells the creator that the target needs to run `/timezone set` first.

`/timezone set` accepts IANA `Area/Location` names (plus `UTC`), case-insensitively, and offers autocomplete as the user types. Fixed-offset zones (`EST`, `Etc/GMT+6`) are rejected because they don't follow daylight saving time. The confirmation is posted publicly in the channel and names the previous timezone if one was set.

### Parsing

Time expressions are parsed with `dateparser` (Python). The creator's stored timezone is the default reference. Three qualifiers modify this:

- **`their time`** — interpret the time in the target's timezone. `/remind @acacia 9am their time do the thing` = 9 AM Central if Acacia is set to `America/Chicago`.
- **`my time`** — explicit but redundant (this is already the default). Useful for clarity.
- **Explicit timezone** — `/remind @acacia 9am UTC-6 do the thing` or `/remind @acacia 9am ET do the thing`.

The qualifier is detected and stripped before the remaining time string is handed to `dateparser`.

With multiple targets, `their time` is resolved per target: `9am their time` fires at 9 AM in each target's own zone.

Accepted explicit zones:

- US abbreviations, which follow daylight saving time: `ET`/`EST`/`EDT` all mean `America/New_York` wall-clock time (so `9am EST` in July is 9 AM on New York clocks). Likewise `CT`/`CST`/`CDT`, `MT`/`MST`/`MDT`, `PT`/`PST`/`PDT`.
- `UTC` / `GMT`, and whole-hour offsets `UTC±N` / `GMT±N` (fixed, no DST).
- IANA names, e.g. `Europe/London`.

Rules for the time expression:

- **A time is required.** A date alone (`friday`, `oct 3`, `tomorrow`, `in 3 days`) is rejected with a hint to add one (`friday 9am`). Relative times (`in 2 hours`, `90m`) count as having a time. A bare number (`9`, `at 9`) is rejected as ambiguous.
- **Time-only input that has already passed today rolls to tomorrow.** `9am` entered at 10:40 AM means 9 AM tomorrow. `today 9am` at 10:40 AM is rejected instead.
- **A month and day without a year means its next occurrence.** `jan 5 9am` in October means next January; so does `sept 30 3pm` on October 1 (a year out). Confirmations show the year whenever it isn't the current one, so a slip is visible.
- **Anything else in the past is rejected** (`yesterday 9am`, `sept 30 2026 3pm`).
- Unparseable input is rejected with example phrasings.

### Display

Every time display uses a two-part format: the time as the creator gave it, labeled with the zone it was given in, followed by a Discord dynamic timestamp that renders in the viewer's local timezone.

Example as seen by someone in Central time:

> (from Elliott, 10:00 AM ET) \[your time: 9:00 AM\]

The bracketed portion is a Discord `<t:UNIX:t>` timestamp that each viewer sees in their own timezone. If the creator and viewer share a timezone, the two times match — slightly redundant, obviously fine.

## Permissions

Flat. No ownership hierarchy.

- **Create:** Any server member can create a reminder targeting any other server member (or themselves).
- **Reschedule / snooze:** Any server member can reschedule or snooze any open reminder.
- **Cancel / done:** Any server member can cancel or complete any open reminder.
- **List:** Any server member can see all open reminders on the server.

There is no opt-in or opt-out mechanism for being reminded. On a 3-person research server this is a feature, not a gap. If the server grows, this is the first thing to revisit.

## Notification and Display

### Where reminders fire

Reminders fire in the channel where they were created. The channel is the context — a reminder set in `#facct-paper` fires there, so the domain is obvious before reading the message.

**Fallback:** If the bot loses access to the original channel (permissions revoked, channel deleted), the reminder is delivered as a DM to the target, with its buttons and a final small-text line about where it was originally set: `-# Sent by DM: I can't post in #facct-paper (Research Server) anymore.` Notes from pressing its buttons try the original channel and fall back to the DM. If the DM also fails (the target blocks DMs from server members), the failure is logged.

### Fired reminder format

```
⏰ @acacia
TASK: submit IRB revision
FROM: Elliott
AT: 10:00 AM ET [your time: 9:00 AM] Oct 1
```

FROM is always shown, even when someone reminds themselves. A reminder delivered late (see Startup recovery) gets a final small-text line: `-# ⚠️ Late: the bot was offline when this was due.`

Followed by interaction buttons (see Interaction UX).

### Audit trail

All state changes post a visible note in the originating channel, in the same labeled-line style as fired reminders. The first line says who did what to which reminder. FOR names the target and pings them, unless they made the change themselves. TASK always follows so the note makes sense on its own. The actor is named without a ping. The note posts in the reminder's channel; if the command was run somewhere else, the person who ran it gets a private pointer to it.

**Reschedule:**

```
🔄 acacia rescheduled reminder #12
FOR: @elliott
TASK: submit IRB revision
AT: 10:00 AM CT [your time: 10:00 AM] Oct 1
REASON: sick
```

**Snooze** (slash command or button):

```
💤 acacia snoozed reminder #12 for 1h
FOR: @elliott
TASK: submit IRB revision
AT: 10:00 AM CT [your time: 10:00 AM] Oct 1
```

**Cancel:**

```
❌ acacia cancelled reminder #12
FOR: @elliott
TASK: submit IRB revision
REASON: Elliott said he's handling it
```

**Done (acknowledged completion):**

```
✅ acacia completed reminder #12
FOR: @elliott
TASK: submit IRB revision
```

Reasons on reschedule and cancel are optional. If omitted, the REASON line is left out. AT is the new time. A reschedule is labeled in the zone the new time was given in, which becomes the reminder's display zone; a snooze keeps the reminder's existing display zone.

### Confirmation on creation

When a reminder is created, the bot confirms in the same channel:

```
Created in #facct-paper
TASK: submit IRB revision
FROM: Elliott
#12 @acacia: 9:00 AM CT [your time: 9:00 AM] Oct 1
```

For multi-target reminders, TASK and FROM appear once and each reminder gets its own line with its own ID, time, and date (times can differ with `their time`):

```
#12 @acacia: 9:00 AM CT [your time: 9:00 AM] Oct 1
#13 @elliott: 10:00 AM ET [your time: 9:00 AM] Oct 1
```

The confirmation pings the targets, so they know something was set for them. The date shows the year only when it isn't the current year.

If the creator or any target has no stored timezone, nothing is created; the error names everyone who needs to run `/timezone set`.

No bot message ever pings `@everyone`, `@here`, or roles, even if they appear in reminder text. A fired reminder pings only its target.

## Multi-Target Reminders

`/remind @acacia @elliott 9am do the thing` creates two separate reminders that share a `batch_id` in the database.

### Independence

Each reminder has its own ID, fires separately, and can be rescheduled or cancelled independently. Cancelling one does not affect the other. Rescheduling one does not move the other. They are separate entries that happen to have been born together.

### Light linking

When a reminder with siblings is cancelled or rescheduled, the channel notification ends with an ALSO line for each sibling that is still open (not done or cancelled):

```
🔄 acacia rescheduled reminder #14
FOR: @acacia
TASK: do the thing
AT: 10:00 AM CT [your time: 10:00 AM] Oct 1
REASON: need more time
ALSO: elliott's copy #15 is still active
```

This is awareness, not coordination. No cascading operations, no prompts to update siblings, no group commands. The secretary tells you the other one's still on the books; the secretary doesn't make decisions about it.

### Firing

Siblings fire as separate messages, each with their own interaction buttons. This means each target can snooze or dismiss independently.

## Interaction UX

### Buttons on fired reminders

When a reminder fires, the message includes a row of Discord buttons:

`[Snooze 15m]` `[Snooze 1h]` `[Done ✓]` `[Cancel]`

- **Snooze 15m / 1h** — pushes the reminder back by that duration (from now). Posts a snooze note in the channel and re-fires later. Clears the buttons on this message; fresh ones come with the re-fired message.
- **Done ✓** — marks the reminder as completed. Posts the done note (see Audit trail) in the channel. Clears the buttons.
- **Cancel** — cancels the reminder. Posts the cancel note in the channel (no reason via button; use `/cancel <id> reason` for that). Clears the buttons.

Any server member can press any button (flat permissions). The note identifies who pressed it.

### Slash commands for deliberate management

Buttons handle the immediate "I just got pinged" interaction. Slash commands handle everything else: creating reminders, rescheduling to a specific time, cancelling with a reason, listing pending reminders.

The reminder ID (shown in `/list` output and in creation confirmations) is how slash commands reference a specific reminder.

### Button expiry

Buttons keep working across bot restarts: each button's ID encodes the reminder ID, the fire time of the firing it belongs to, and the action, so the bot can handle a click without remembering anything about the message.

A button is **stale** when its reminder has changed since that message was sent. It has been done or cancelled, snoozed or rescheduled (so its fire time no longer matches), or deleted. Pressing a stale button changes nothing: the presser gets a private reply ("Reminder #12 was already completed by acacia", or "Reminder #12 has moved since this message; use `/snooze 12 <duration>` or `/done 12`"), and the stale buttons are removed from that message. Buttons left on a message after a slash command changed its reminder are cleaned up this way the first time someone presses one.

## Data Model

SQLite, single file, deployed alongside the bot.

### `users` table

| Column | Type | Notes |
| --- | --- | --- |
| discord\_id | TEXT PK | Discord user snowflake |
| timezone | TEXT | IANA timezone string, e.g. `America/Chicago` |
| created\_at | TEXT | ISO 8601 |

### `reminders` table

| Column | Type | Notes |
| --- | --- | --- |
| id | INTEGER PK | Auto-increment, used in slash commands (`#12`) |
| creator\_id | TEXT FK | Discord ID of who created it |
| target\_id | TEXT FK | Discord ID of who gets pinged |
| channel\_id | TEXT | Channel where it was created and will fire |
| guild\_id | TEXT | Server ID |
| message | TEXT | The reminder text |
| fire\_at | TEXT | ISO 8601 UTC — internal storage always in UTC |
| created\_at | TEXT | ISO 8601 UTC |
| status | TEXT | `pending` (waiting to fire), `fired`, `done`, `cancelled`. The first two are open; a fired reminder stays open until someone marks it done or cancels it. Reschedule and snooze both set `pending`; the log records which happened. |
| batch\_id | TEXT NULL | Shared UUID for multi-target reminders, NULL for singles |
| recurrence\_rule | TEXT NULL | Reserved for future recurring reminders, always NULL in v1 |
| original\_tz | TEXT | IANA zone the time was given in (creator's by default; target's for `their time`; the explicit zone if one was named), for display |
| original\_time\_str | TEXT | The time as entered, normalized for display in `original_tz` (e.g. "10:00 AM ET") |

### `reminder_log` table

| Column | Type | Notes |
| --- | --- | --- |
| id | INTEGER PK | Auto-increment |
| reminder\_id | INTEGER FK | Which reminder |
| action | TEXT | `created`, `rescheduled`, `snoozed`, `cancelled`, `done`, `fired` |
| actor\_id | TEXT | Discord ID of who did it |
| reason | TEXT NULL | Optional reason string |
| old\_fire\_at | TEXT NULL | Previous fire time (for reschedule/snooze) |
| new\_fire\_at | TEXT NULL | New fire time (for reschedule/snooze) |
| timestamp | TEXT | ISO 8601 UTC |

The log table provides a full history of each reminder. This is useful for debugging and for the audit trail, though the channel messages are the primary user-facing record.

## Deployment

### Stack

- **Python 3.11+** with discord.py (slash commands, buttons, interactions)
- **SQLite** for persistence (single file, no external database service)
- **dateparser** for natural language time parsing
- **discord.ext.tasks** loop polling the database every 15 seconds to fire due reminders
- **zoneinfo** (stdlib) for timezone handling

### VPS setup

Run as a systemd service for automatic restart on crash or reboot, using the unit template in `deploy/remindlet.service` (steps in `docs/SETUP.md`). The bot runs as a dedicated unprivileged `remindlet` user. The bot token goes in a `.env` file in the clone's directory, which is gitignored and readable only by that user. Logs go to the systemd journal (`journalctl -u remindlet`). Only one copy of the bot may run per token.

### Startup recovery

The database is the schedule: every 15 seconds the bot fires all `pending` reminders whose time has come. The first pass after a restart therefore picks up anything that came due while the bot was down, with no separate recovery step.

Reminders that came due while the bot was offline fire immediately on startup, with a note that they are late so the arrival time isn't mistaken for the time they were set for.

### Discord bot setup

Requires a Discord application with a bot user and the privileged **Server Members** intent enabled (for display names). Invite scopes: `bot` and `applications.commands`. Permissions needed: Send Messages, Embed Links, Read Message History. The bot should be added to the server with an OAuth2 URL scoped to the specific server.

### Repo structure

Single-repo project:

```
remindlet/
├── bot.py              # Entry point, bot setup, command sync
├── cogs/
│   ├── reminders.py    # /remind, /reschedule, /cancel, /snooze, /done, /list, buttons, firing
│   └── timezone.py     # /timezone set
├── db.py               # SQLite connection, schema and migrations, queries
├── time_parser.py      # Reading input: times, zones, qualifiers, durations
├── formatting.py       # Writing output: every message the bot posts
├── config.py           # Token, guild ID, DB path from .env
├── deploy/
│   └── remindlet.service  # systemd unit template
├── docs/               # SPEC.md, DECISIONS.md, SETUP.md, UNTESTED.md
├── tests/
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

## Future Extensions

Deferred from v1 but the data model and architecture should not close them off.

**Recurring reminders.** The `recurrence_rule` column is already reserved. Implementation would add an RRULE-style string (RFC 5545) and a scheduler hook that creates the next occurrence after each firing. The `/remind` command would accept interval syntax like `every monday 9am` or `every friday at 3pm`. No changes to the permissions model or display format needed.

**Reminder categories or tags.** Could add a `tags` column for organizing reminders by topic (`#facct`, `#irb`, `#grading`). Would let `/list` filter by tag. Low effort, unclear if needed at current server size.

**Thread-based reminders.** Fire the reminder as a reply in a specific thread rather than the top-level channel. Useful if the server develops more structured channel usage.

**Escalation.** If a reminder is snoozed more than N times, optionally notify the creator. Passive accountability without being punitive. Questionable whether this is wanted.