import discord
from discord.ext import commands
from discord import app_commands, ui
import datetime
import traceback
import os
import pytz
import asyncio
from typing import Optional
from collections import defaultdict

from bot.utils.database import Database, RsvpStatus, ROLES, SUBCLASSES

# All helper functions and classes (create_event_embed, RoleSelect, Modal, Views, etc.) remain the same as the previous version.
# For brevity, they are omitted here, but should be kept in your file.
# The following is the changed part of the file.

# ... (Keep all helper functions and classes from the previous version of the file here) ...
# --- All of the helper functions and UI classes from the previous version should be here ---

# --- FIX: Define the Group at the module level ---
event_group = app_commands.Group(name="event", description="Commands for creating and managing events.")

# --- FIX: Define the command as a standalone function ---
@event_group.command(name="create", description="Create a new event.")
@app_commands.describe(channel="The channel where the event announcement will be posted.")
async def create_command(interaction: discord.Interaction, channel: discord.TextChannel):
    """Opens a form to create a new event."""
    # To get the db instance, we get the cog from the bot client
    bot = interaction.client
    event_cog = bot.get_cog("EventManagement")
    if not event_cog:
        return await interaction.response.send_message("Event cog is not loaded.", ephemeral=True)

    modal = EventCreationModal(bot, event_cog.db, channel)
    await interaction.response.send_modal(modal)


# --- FIX: The Cog class now only holds state and non-command methods ---
class EventManagement(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
    # NO COMMANDS ARE DEFINED IN THE CLASS
    # The class is now just for state management


# --- FIX: The setup function now registers both the Cog and the command group ---
async def setup(bot: commands.Bot):
    db = bot.web_app.state.db
    # Add the cog for state management
    await bot.add_cog(EventManagement(bot, db))
    # Explicitly add the command group to the bot's tree
    bot.tree.add_command(event_group)
    # Add the persistent view
    bot.add_view(PersistentEventView(db))
