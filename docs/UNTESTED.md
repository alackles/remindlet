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
