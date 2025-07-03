import discord
from discord.ext import commands
from discord import app_commands
import os

# Use relative import to go up one level to the 'bot' package root
from .event_management import update_event_list_message

GUILD_ID = os.getenv("GUILD_ID")
if not GUILD_ID: raise ValueError("GUILD_ID not set in environment.")

sort_group = app_commands.Group(name="sort", description="Commands for sorting the event list.", guild_ids=[int(GUILD_ID)])

class SortCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @sort_group.command(name="ascending", description="Sort events by date, with the soonest at the top.")
    async def sort_asc(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        db = self.bot.db
        await db.set_event_sort_order(interaction.guild_id, "ASC")
        await update_event_list_message(self.bot, interaction.guild_id, db)
        await interaction.followup.send("Event list has been sorted in ascending order (soonest first).", ephemeral=True)

    @sort_group.command(name="descending", description="Sort events by date, with the furthest away at the top.")
    async def sort_desc(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        db = self.bot.db
        await db.set_event_sort_order(interaction.guild_id, "DESC")
        await update_event_list_message(self.bot, interaction.guild_id, db)
        await interaction.followup.send("Event list has been sorted in descending order (furthest first).", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(SortCog(bot))
    bot.tree.add_command(sort_group)
