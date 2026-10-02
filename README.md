# remindlet

A Discord reminder bot that works like a shared secretary for a small research
server. Anyone can remind anyone (`/remind who:@elliott when:friday 9am their time
what:submit IRB revision`), and anyone can reschedule, snooze, cancel, or mark any
reminder done. Every change is announced in the channel where the reminder lives,
so nothing disappears silently. Each person sets their timezone once; times are
read in natural language and shown both in the zone they were given in and in
each viewer's own time. Fired reminders carry Snooze / Done / Cancel buttons.

Full behavior: [docs/SPEC.md](docs/SPEC.md). Running and deploying: [docs/SETUP.md](docs/SETUP.md).

```
remindlet/
├── bot.py                  # entry point: connects, loads cogs, syncs slash commands
├── config.py               # reads the token, server ID, and database path from .env
├── db.py                   # SQLite schema, migrations, and every query
├── time_parser.py          # reads input: "friday 9am their time", zones, snooze lengths
├── formatting.py           # writes output: the text of every message the bot posts
├── cogs/
│   ├── reminders.py        # /remind, /reschedule, /snooze, /cancel, /done, /list, buttons, firing
│   └── timezone.py         # /timezone set
├── deploy/
│   └── remindlet.service   # systemd unit template for the server
├── docs/
│   ├── SPEC.md             # what the bot does (source of truth)
│   ├── DECISIONS.md        # design choices the spec doesn't cover, and why
│   ├── SETUP.md            # local development and deployment steps
│   └── UNTESTED.md         # manual checks written but not yet run
├── tests/
│   ├── conftest.py         # shared database fixture
│   ├── helpers.py          # fake users and a reminder factory
│   ├── test_time_parser.py # parsing phrases, zones, and durations
│   ├── test_formatting.py  # exact message formats
│   ├── test_db.py          # storage, state changes, listing, migration
│   ├── test_firing.py      # firing due reminders, startup recovery
│   └── test_buttons.py     # button IDs and stale-button rules
├── .env.example            # template for the untracked .env
├── requirements.txt        # runtime dependencies
├── requirements-dev.txt    # adds pytest
├── pytest.ini              # test discovery settings
└── CLAUDE.md               # working notes and milestones for Claude Code
```
