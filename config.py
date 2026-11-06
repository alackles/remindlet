"""Configuration loaded from .env. Values are validated by bot.py at startup."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def parse_ids(text: str) -> list[int]:
    """Comma-separated Discord IDs, e.g. "111, 222" -> [111, 222]."""
    return [int(part) for part in text.split(",") if part.strip()]


DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
# The servers to sync slash commands to: every server the bot is in.
GUILD_IDS = parse_ids(os.environ.get("GUILD_IDS", ""))
# Default is next to this file, not the working directory, so the bot finds
# the same database however it's launched.
DB_PATH = Path(os.environ.get("DB_PATH") or Path(__file__).parent / "remindlet.db")
