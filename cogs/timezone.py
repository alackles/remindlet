"""/timezone set."""

from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import db
import formatting
import time_parser


class Timezone(commands.GroupCog, group_name="timezone"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="set", description="Set your timezone.")
    @app_commands.describe(zone="Start typing a city or region, e.g. Chicago or America/New_York")
    async def set_zone(self, interaction: discord.Interaction, zone: str) -> None:
        tz = time_parser.find_zone(zone)
        if tz is None:
            await interaction.response.send_message(
                f"`{zone}` isn't a timezone I accept. Start typing a city "
                "(e.g. `Chicago`) and pick a zone from the list.",
                ephemeral=True,
            )
            return

        previous = db.set_timezone(self.bot.db, interaction.user.id, tz)
        local = f"currently {formatting.format_in_zone(datetime.now(timezone.utc), tz)}"
        who = discord.utils.escape_markdown(interaction.user.display_name)
        if previous is None:
            text = f"🌐 {who} set their timezone to **{tz}** ({local})."
        elif previous == tz:
            text = f"🌐 {who}'s timezone is already **{tz}** ({local})."
        else:
            text = f"🌐 {who} changed their timezone from **{previous}** to **{tz}** ({local})."
        await interaction.response.send_message(text)

    @set_zone.autocomplete("zone")
    async def zone_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return [app_commands.Choice(name=z, value=z) for z in time_parser.suggest_zones(current)]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Timezone(bot))
