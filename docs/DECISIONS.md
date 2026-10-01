# Decisions

Design choices the spec doesn't cover. Format: milestone — choice (convention | judgment call).

- M0 — Dependencies in `requirements.txt` with minimum versions (`>=`), not exact pins; local env is `.venv/`. (convention)
- M0 — Sync slash commands to the single guild (`GUILD_ID`) on every startup in `setup_hook`, rather than global sync or a manual sync command. (judgment call)
- M0 — `/ping` lives in `bot.py` as a temporary health check, not in a cog. (judgment call)
