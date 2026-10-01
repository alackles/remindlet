# Decisions

Design choices the spec doesn't cover. Format: milestone — choice (convention | judgment call).

- M0 — Dependencies in `requirements.txt` with minimum versions (`>=`), not exact pins; local env is `.venv/`. (convention)
- M0 — Sync slash commands to the single guild (`GUILD_ID`) on every startup in `setup_hook`, rather than global sync or a manual sync command. (judgment call)
- M0 — `/ping` lives in `bot.py` as a temporary health check, not in a cog. (judgment call)
- M1 — Stdlib `sqlite3` called synchronously from the event loop, not `aiosqlite`; queries are sub-millisecond at this scale. (judgment call)
- M1 — Schema version stored in `PRAGMA user_version`; `db.connect()` creates the schema on a fresh file and refuses to open a mismatched version. (convention)
- M1 — `CHECK` constraints on `reminders.status` and `reminder_log.action`; index on `reminders (status, fire_at)` for the scheduler. (convention)
- M1 — `AUTOINCREMENT` on reminder IDs so a user-visible `#12` is never reused. (judgment call)
- M1 — `reminder_log.actor_id` is nullable; a `fired` entry has no human actor. (judgment call)
- M1 — Timestamps stored only via `db.to_iso()`: UTC, second precision, `+00:00` suffix, so string order is chronological. (convention)
- M1 — `DB_PATH` from `.env`, defaulting to `remindlet.db` next to `config.py` rather than the working directory. (convention)
- M1 — `pytest` in `requirements-dev.txt` so the VPS doesn't install it; `pytest.ini` puts the repo root on the import path. (convention)
- M1 — One `sqlite3` connection opened in `setup_hook`, stored as `bot.db`, and reached by cogs via `self.bot.db`. (convention)
- M1 — Zone lookup and autocomplete helpers live in `time_parser.py`, since Milestone 2's explicit-zone parsing needs them too. (judgment call)
- M1 — Empty autocomplete input suggests the four main US zones plus UTC instead of the first 25 alphabetically. (judgment call)
- M1 — `/timezone set` errors are ephemeral; only successful changes post publicly. (judgment call)
- M1 — Public confirmations name the user by display name, not @mention, so changing a setting doesn't ping anyone. (judgment call)
- M2 — `UTC±N` accepts whole hours only and is stored as the IANA name `Etc/GMT∓N` (sign inverted per IANA), so `original_tz` is always loadable by `ZoneInfo`. (judgment call)
- M2 — Display labels: `ET`/`CT`/`MT`/`PT` for the main US zones (as in the spec's examples), `UTC±N` for offsets, otherwise tzdata's own abbreviation (`BST`). (judgment call)
- M2 — Naming more than one zone in one expression (`9am ET their time`) is an error rather than last-one-wins. (judgment call)
