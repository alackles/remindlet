# Untested

Manual checks that were written but deliberately not run yet. Each keeps its
label, so a failure can be reported as e.g. "`restart-5` failed". Run them if
the behavior they cover is ever in doubt.

## M3: `restart` (milestone done-when: a reminder created before a restart still fires after it)

Not run in Discord. Partly covered by automated tests: `test_fire_due_fires_overdue_and_due_only`
(scheduler fires overdue reminders on its first pass), `test_reminders_survive_reconnect`
(pending reminders persist), and `test_fired_late_note` (late note text).

1. With the bot running, `/remind who:@you when:in 3 minutes what:survives restart`.
2. Stop the bot (Ctrl+C) and start it again right away.
3. When the 3 minutes are up, it fires on time with **no** late note.
4. `/remind who:@you when:in 2 minutes what:missed while down`, then stop the bot.
5. Wait at least 3 minutes, then start the bot.
6. Within seconds of startup it fires, with a small `⚠️ Late: the bot was offline…` line under it.

## M3: `errors` (rejections are visible only to the person who ran the command)

Not run in Discord. The parser messages are covered by `tests/test_time_parser.py`;
the missing-timezone, bot, and multi-target paths in `cogs/reminders.py` have no automated tests.

1. `/remind who:@you when:friday what:x` → says a time of day is needed.
2. `/remind who:@you when:9 what:x` → says bare numbers are ambiguous.
3. With a member who hasn't set a timezone: `/remind who:@you when:in 5 minutes what:x also:@them`
   → "Nothing was created…" naming them.
4. `/remind who:@you when:in 5 minutes their time what:multi also:@someone-with-a-timezone`
   → one public confirmation with two lines and two IDs; it pings them.
