"""Configuration loaded from .env. Values are validated by bot.py at startup."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
GUILD_ID = int(os.environ["GUILD_ID"]) if os.environ.get("GUILD_ID") else None
# Default is next to this file, not the working directory, so the bot finds
# the same database however it's launched.
DB_PATH = Path(os.environ.get("DB_PATH") or Path(__file__).parent / "remindlet.db")
