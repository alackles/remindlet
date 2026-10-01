# Discord Reminder Bot

A shared-secretary reminder bot for a 3-person research Discord server.
Anyone can remind anyone, anyone can reschedule or cancel anything, and
every change is announced in the channel where the reminder lives.

## Source of truth

- `docs/SPEC.md` defines behavior. Read the relevant sections before planning a milestone.
- If the implementation needs to diverge from the spec, stop and ask. Don't silently adapt.
- When you make a design choice the spec doesn't cover, add one line to
  `docs/DECISIONS.md`: milestone, the choice, and whether it's a
  convention (standard practice) or a judgment call (real alternatives exist).
  Also tag it `correction` if the choice changed because I questioned or
  pointed something out, e.g. `(convention, correction)`.

## Working style

- One milestone at a time. Don't start the next until I say so.
- Commit after each logical step within a milestone, not one big commit
  per milestone.
- Commit as yourself: `git commit --author="Claude <noreply@anthropic.com>"`.
  If a commit includes changes I made by hand, leave me as author and add
  yourself as a Co-Authored-By trailer instead.
- Commit DECISIONS.md entries together with the code they explain.
- I'm an expert in Python but new to discord.py and bot deployment. Explain
  discord.py-specific patterns (cogs, interactions, command sync) the first
  time they appear.
<!-- adjust the line above if you've used discord.py before -->

## Conventions

- Python 3.11+, discord.py with app_commands (slash commands) and cogs.
- All times stored in UTC. Convert only at input parsing and display.
- Use `zoneinfo` (stdlib), not `pytz`.
- Token and config come from `.env`, which is never committed.
- Tests: pytest. Time parsing and DB logic must be testable without a Discord connection.

## Commands

- Run: `python bot.py`
- Test: `pytest`

## Milestones

- [x] 0. Skeleton: bot connects and `/ping` responds in the server.
      Done when: the slash command appears and works.
- [x] 1. Data layer + timezones: SQLite schema per spec; `/timezone set`.
      Done when: a stored timezone survives a bot restart.
- [x] 2. Time parser: standalone module, no Discord imports. Handles
      natural language, `my time` / `their time`, and explicit zones.
      Done when: tests cover the spec's examples plus unparseable input.
- [x] 3. Create and fire: `/remind` (single and multi-target with batch_id),
      confirmation message, scheduler, firing in channel, startup recovery.
      Done when: a reminder created before a restart still fires after it.
- [x] Before 4: Clean up how reminders read in Discord. Designed together;
      TASK/FROM/AT labeled lines for all bot messages (see SPEC.md).
- [ ] 4. Management: `/list` with filters, `/reschedule`, `/cancel`,
      `/snooze`, audit posts, sibling notes.
- [ ] 5. Buttons: Snooze 15m / 1h / Done / Cancel, stale-button handling,
      DM fallback when the channel is gone.
- [ ] 6. Deploy: systemd service on the VPS, `.env`, logging.