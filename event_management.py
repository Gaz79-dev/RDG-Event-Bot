import discord
from discord.ext import commands
from discord import app_commands, ui
import datetime
import traceback
import os
import pytz
from urllib.parse import urlencode
import asyncio
from typing import List, Dict
from collections import defaultdict

# Adjust the import path based on your project structure
from utils.database import Database, RsvpStatus, ROLES, SUBCLASSES, RESTRICTED_ROLES

# --- HLL Emoji Mapping (Loaded from Environment) ---
EMOJI_MAPPING = {
    # Primary Roles
    "Commander": os.getenv("EMOJI_COMMANDER", "⭐"),
    "Infantry": os.getenv("EMOJI_INFANTRY", "💂"),
    "Armour": os.getenv("EMOJI_ARMOUR", "🛡️"),
    "Recon": os.getenv("EMOJI_RECON", "👁️"),
    # Subclasses
    "Anti-Tank": os.getenv("EMOJI_ANTI_TANK", "🚀"),
    "Assault": os.getenv("EMOJI_ASSAULT", "💥"),
    "Automatic Rifleman": os.getenv("EMOJI_AUTOMATIC_RIFLEMAN", "🔥"),
    "Engineer": os.getenv("EMOJI_ENGINEER", "🛠️"),
    "Machine Gunner": os.getenv("EMOJI_MACHINE_GUNNER", "💣"),
    "Medic": os.getenv("EMOJI_MEDIC", "➕"),
    "Officer": os.getenv("EMOJI_OFFICER", "🫡"),
    "Rifleman": os.getenv("EMOJI_RIFLEMAN", "👤"),
    "Support": os.getenv("EMOJI_SUPPORT", "🔧"),
    "Tank Commander": os.getenv("EMOJI_TANK_COMMANDER", "🧑‍✈️"),
    "Crewman": os.getenv("EMOJI_CREWMAN", "👨‍🔧"),
    "Spotter": os.getenv("EMOJI_SPOTTER", "👀"),
    "Sniper": os.getenv("EMOJI_SNIPER", "🎯"),
    "Unassigned": "❔"
}

# --- Helper function to generate Google Calendar Link ---
def create_google_calendar_link(event: dict) -> str:
    base_url = "https://www.google.com/calendar/render?action=TEMPLATE"
    start_time_utc = event['event_time'].astimezone(pytz.utc)
    end_time_utc = (event['end_time'] or (start_time_utc + datetime.timedelta(hours=2))).astimezone(pytz.utc)
    params = {'text': event['title'],'dates': f"{start_time_utc.strftime('%Y%m%dT%H%M%SZ')}/{end_time_utc.strftime('%Y%m%dT%H%M%SZ')}",'details': event['description'],'ctz': 'UTC'}
    return f"{base_url}&{urlencode(params)}"

# --- Helper function to generate the event embed ---
async def create_event_embed(bot: commands.Bot, event_id: int, db: Database) -> discord.Embed:
    event = await db.get_event_by_id(event_id)
    if not event: return discord.Embed(title="Error", description="Event not found.", color=discord.Color.red())
    guild = bot.get_guild(event['guild_id'])
    if not guild: return discord.Embed(title="Error", description="Could not find the server for this event.", color=discord.Color.red())

    signups = await db.get_signups_for_event(event_id)
    squad_roles = await db.get_squad_config_roles(guild.id)
    
    embed = discord.Embed(title=f"📅 {event['title']}", color=discord.Color.blue())
    # ... (rest of embed creation logic) ...
    
    accepted_signups = defaultdict(list)
    tentative_users, declined_users = [], []

    for signup in signups:
        member = guild.get_member(signup['user_id'])
        if not member: continue

        if signup['rsvp_status'] == RsvpStatus.ACCEPTED:
            user_role_ids = {r.id for r in member.roles}
            specialty = ""
            if squad_roles.get('squad_arty_role_id') in user_role_ids: specialty = " (Arty)"
            elif squad_roles.get('squad_armour_role_id') in user_role_ids: specialty = " (Armour)"
            elif squad_roles.get('squad_attack_role_id') in user_role_ids and squad_roles.get('squad_defence_role_id') in user_role_ids: specialty = " (Flex)"
            elif squad_roles.get('squad_attack_role_id') in user_role_ids: specialty = " (Attack)"
            elif squad_roles.get('squad_defence_role_id') in user_role_ids: specialty = " (Defence)"

            role = signup['role_name'] or "Unassigned"
            subclass = signup['subclass_name']
            
            signup_text = f"**{member.display_name}**"
            if subclass: signup_text += f" ({EMOJI_MAPPING.get(subclass, '❔')})"
            signup_text += specialty
            
            accepted_signups[role].append(signup_text)
        elif signup['rsvp_status'] == RsvpStatus.TENTATIVE:
            tentative_users.append(member.display_name)
        elif signup['rsvp_status'] == RsvpStatus.DECLINED:
            declined_users.append(member.display_name)

    # ... (rest of embed generation) ...
    return embed

class EventManagement(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        # ... rest of __init__ ...

    # --- NEW Command Group for Events ---
    event_group = app_commands.Group(name="event", description="Commands for creating and managing events.")

    @event_group.command(name="create", description="Create a new event via DM.")
    # @app_commands.check(is_event_manager) # This check would be added back
    async def create(self, interaction: discord.Interaction):
        # ... start_conversation logic ...
        pass

    @event_group.command(name="edit", description="Edit an existing event via DM.")
    @app_commands.describe(event_id="The ID of the event to edit.")
    # @app_commands.check(is_event_manager)
    async def edit(self, interaction: discord.Interaction, event_id: int):
        # ... edit logic ...
        pass

    @event_group.command(name="delete", description="Delete an existing event by its ID.")
    @app_commands.describe(event_id="The ID of the event to delete.")
    # @app_commands.check(is_event_manager)
    async def delete(self, interaction: discord.Interaction, event_id: int):
        # ... delete logic ...
        pass

    setup = app_commands.Group(name="setup", description="Commands for setting up the bot.", default_permissions=discord.Permissions(administrator=True))
    squad_config_group = app_commands.Group(name="squad_config", description="Commands for configuring squad roles.", parent=setup)

    @squad_config_group.command(name="attack_role", description="Set the role for Attack specialty.")
    async def set_attack_role(self, interaction: discord.Interaction, role: discord.Role):
        await self.db.set_squad_config_role(interaction.guild.id, "attack", role.id)
        await interaction.response.send_message(f"Attack specialty role set to {role.mention}.", ephemeral=True)

    @squad_config_group.command(name="defence_role", description="Set the role for Defence specialty.")
    async def set_defence_role(self, interaction: discord.Interaction, role: discord.Role):
        await self.db.set_squad_config_role(interaction.guild.id, "defence", role.id)
        await interaction.response.send_message(f"Defence specialty role set to {role.mention}.", ephemeral=True)

    @squad_config_group.command(name="arty_role", description="Set the role for Arty Certified players.")
    async def set_arty_role(self, interaction: discord.Interaction, role: discord.Role):
        await self.db.set_squad_config_role(interaction.guild.id, "arty", role.id)
        await interaction.response.send_message(f"Arty specialty role set to {role.mention}.", ephemeral=True)

    @squad_config_group.command(name="armour_role", description="Set the role for Armour specialty players.")
    async def set_armour_role(self, interaction: discord.Interaction, role: discord.Role):
        await self.db.set_squad_config_role(interaction.guild.id, "armour", role.id)
        await interaction.response.send_message(f"Armour specialty role set to {role.mention}.", ephemeral=True)

    # ... (rest of the cog) ...

async def setup(bot: commands.Bot, db: Database):
    await bot.add_cog(EventManagement(bot, db))
    # The PersistentEventView should also be added here as before
    # bot.add_view(PersistentEventView(db))
