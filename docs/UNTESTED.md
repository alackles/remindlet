# Untested

Manual checks that were written but deliberately not run yet. Each keeps its
label, so a failure can be reported as e.g. "`errors-3` failed". Run them if
the behavior they cover is ever in doubt.

## M3: `errors` (rejections are visible only to the person who ran the command)

Not run in Discord. The parser messages are covered by `tests/test_time_parser.py`;
the missing-timezone, bot, and multi-target paths in `cogs/reminders.py` have no automated tests.

1. `/remind who:@you when:friday what:x` → says a time of day is needed.
2. `/remind who:@you when:9 what:x` → says bare numbers are ambiguous.
3. With a member who hasn't set a timezone: `/remind who:@you when:in 5 minutes what:x also:@them`
   → "Nothing was created…" naming them.
4. `/remind who:@you when:in 5 minutes their time what:multi also:@someone-with-a-timezone`
   → one public confirmation: TASK/FROM once, then a `#id` line for each person; it pings them.

## M4: `others` (sibling ALSO lines, and pings when changing someone else's reminder)

Not run in Discord; needs a second member with a timezone set. Partly covered by automated
tests: `test_open_siblings` (which siblings count as open) and `test_reschedule_note_matches_spec`
(ALSO line text). The ping rule (FOR pings the target unless they made the change) is only in
`cogs/reminders.py` and has no automated test.

1. `/remind who:@you when:in 1 hour what:sibling test also:@them`.
2. Cancel *your* copy → the note ends with `ALSO: <their name>'s copy #N is still active`.
3. Cancel *their* copy → the note **pings them** via the `FOR:` line.

## M6: `reboot` (the bot comes back on its own after the VPS restarts)

Not run. Nothing automated covers it; it depends on `systemctl enable` having
linked the unit into the boot sequence.

1. On the VPS: `sudo reboot`.
2. After it's back up: `systemctl status remindlet` → `active (running)`, with a start
   time just after the reboot.
3. In Discord, the bot shows as online without anyone having started it.
