import discord
from discord.ext import commands
from discord import app_commands, ui
import datetime
import traceback
import os
import pytz
from urllib.parse import urlencode
import asyncio
from typing import List, Dict, Optional
from collections import defaultdict

# Use relative import to go up one level to the 'bot' package root
from ..utils.database import Database, RsvpStatus, ROLES, SUBCLASSES, RESTRICTED_ROLES

# --- HLL Emoji Mapping (Loaded from Environment) ---
EMOJI_MAPPING = {
    "Commander": os.getenv("EMOJI_COMMANDER", "⭐"),
    "Infantry": os.getenv("EMOJI_INFANTRY", "💂"),
    "Armour": os.getenv("EMOJI_ARMOUR", "🛡️"),
    "Recon": os.getenv("EMOJI_RECON", "👁️"),
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

# --- Helper function to generate the event embed ---
async def create_event_embed(bot: commands.Bot, event_id: int, db: Database) -> discord.Embed:
    event = await db.get_event_by_id(event_id)
    if not event: return discord.Embed(title="Error", description="Event not found.", color=discord.Color.red())
    guild = bot.get_guild(event['guild_id'])
    if not guild: return discord.Embed(title="Error", description="Could not find the server for this event.", color=discord.Color.red())

    signups = await db.get_signups_for_event(event_id)
    squad_roles = await db.get_squad_config_roles(guild.id)
    
    embed = discord.Embed(title=f"📅 {event['title']}", description=event['description'], color=discord.Color.blue())
    
    time_str = f"**Starts:** {discord.utils.format_dt(event['event_time'], style='F')} ({discord.utils.format_dt(event['event_time'], style='R')})"
    if event['end_time']: time_str += f"\n**Ends:** {discord.utils.format_dt(event['end_time'], style='F')}"
    if event['timezone']: time_str += f"\nTimezone: {event['timezone']}"
    embed.add_field(name="Time", value=time_str, inline=False)

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

    total_accepted = sum(len(v) for v in accepted_signups.values())
    embed.add_field(name=f"✅ Accepted ({total_accepted})", value="\u200b", inline=False)
    
    display_roles = ROLES + ["Unassigned"]
    for role in display_roles:
        if role == "Unassigned" and not accepted_signups.get("Unassigned"):
            continue
        role_emoji = EMOJI_MAPPING.get(role, "")
        users_in_role = accepted_signups.get(role, [])
        field_value = "\n".join(users_in_role) or "No one yet"
        embed.add_field(name=f"{role_emoji} **{role}** ({len(users_in_role)})", value=field_value, inline=False)

    if tentative_users: embed.add_field(name=f"🤔 Tentative ({len(tentative_users)})", value=", ".join(tentative_users), inline=False)
    if declined_users: embed.add_field(name=f"❌ Declined ({len(declined_users)})", value=", ".join(declined_users), inline=False)
    
    creator_name = "Unknown User"
    creator_id = event.get('creator_id')
    if creator_id:
        try:
            creator = guild.get_member(creator_id) or await guild.fetch_member(creator_id)
            if creator:
                creator_name = creator.display_name
        except discord.NotFound:
            try:
                user = await bot.fetch_user(creator_id)
                creator_name = user.name
            except discord.NotFound:
                pass

    embed.set_footer(text=f"Event ID: {event_id} | Created by: {creator_name}")
    
    return embed

# --- UI Components ---
class RoleSelect(ui.Select):
    """The first dropdown for selecting a primary role."""
    def __init__(self, db: Database, event_id: int):
        self.db = db
        self.event_id = event_id
        options = [discord.SelectOption(label=role, emoji=EMOJI_MAPPING.get(role, "❔")) for role in ROLES]
        super().__init__(placeholder="1. Choose your primary role...", options=options)

    async def callback(self, interaction: discord.Interaction):
        self.view.role = self.values[0]
        
        subclass_options = SUBCLASSES.get(self.view.role, [])
        subclass_select = self.view.subclass_select
        subclass_select.disabled = not subclass_options
        
        if subclass_options:
            subclass_select.placeholder = "2. Choose your subclass..."
            subclass_select.options = [discord.SelectOption(label=sub, emoji=EMOJI_MAPPING.get(sub, "❔")) for sub in subclass_options]
        else:
            await self.db.update_signup_role(self.event_id, interaction.user.id, self.view.role, None)
            for item in self.view.children: item.disabled = True
            await interaction.response.edit_message(content=f"Your role has been confirmed as **{self.view.role}**! You can dismiss this message.", view=self.view)
            self.view.stop()
            asyncio.create_task(self.view.update_original_embed())
            return

        await interaction.response.edit_message(view=self.view)

class SubclassSelect(ui.Select):
    """The second dropdown for selecting a subclass."""
    def __init__(self, db: Database, event_id: int):
        self.db = db
        self.event_id = event_id
        super().__init__(placeholder="Select a primary role first...", disabled=True, options=[discord.SelectOption(label="placeholder")])

    async def callback(self, interaction: discord.Interaction):
        subclass = self.values[0]
        await self.db.update_signup_role(self.event_id, interaction.user.id, self.view.role, subclass)
        
        for item in self.view.children: item.disabled = True
        await interaction.response.edit_message(
            content=f"Your role has been confirmed as **{self.view.role} ({subclass})**! You can dismiss this message.",
            view=self.view
        )
        self.view.stop()
        asyncio.create_task(self.view.update_original_embed())

class RoleSelectionView(ui.View):
    """The view sent in a DM to the user for role selection."""
    def __init__(self, bot: commands.Bot, db: Database, event_id: int, message_id: int, user: discord.User):
        super().__init__(timeout=300)
        self.bot = bot
        self.db = db
        self.event_id = event_id
        self.message_id = message_id
        self.user = user
        self.role: Optional[str] = None
        
        self.subclass_select = SubclassSelect(db, event_id)
        self.add_item(RoleSelect(db, event_id))
        self.add_item(self.subclass_select)

    async def on_timeout(self):
        """Handle the case where the user does not select a role in time."""
        if self.role is None:
            print(f"Role selection timed out for user {self.user.id} for event {self.event_id}.")
            await self.db.update_signup_role(self.event_id, self.user.id, "Unassigned", None)
            await self.update_original_embed()
            try:
                await self.user.send(
                    "Your role selection has timed out. You have been marked as 'Unassigned' for the event. "
                    "To select a role, please click 'Decline' and then 'Accept' on the event again."
                )
            except discord.Forbidden:
                pass

    async def update_original_embed(self):
        """Finds the original event message and updates the embed."""
        event = await self.db.get_event_by_id(self.event_id)
        if not event: return

        try:
            channel = self.bot.get_channel(event['channel_id']) or await self.bot.fetch_channel(event['channel_id'])
            message = await channel.fetch_message(self.message_id)
            new_embed = await create_event_embed(self.bot, self.event_id, self.db)
            await message.edit(embed=new_embed)
        except (discord.NotFound, discord.Forbidden):
            print(f"Could not update original embed for event {self.event_id}")
        except Exception as e:
            print(f"Error updating original embed: {e}")

class PersistentEventView(ui.View):
    def __init__(self, db: Database):
        super().__init__(timeout=None)
        self.db = db

    async def update_embed(self, interaction: discord.Interaction, event_id: int):
        """Safely updates the event embed."""
        try:
            new_embed = await create_event_embed(interaction.client, event_id, self.db)
            await interaction.message.edit(embed=new_embed)
        except (discord.NotFound, discord.Forbidden) as e:
            print(f"Error updating embed for event {event_id}: {e}")
        except Exception as e:
            print(f"Unexpected error updating embed for event {event_id}: {e}")
            traceback.print_exc()

    @ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="persistent_view:accept")
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)

            event = await self.db.get_event_by_message_id(interaction.message.id)
            if not event:
                await interaction.followup.send("This event could not be found or is no longer active.", ephemeral=True)
                return

            await self.db.set_rsvp(event['event_id'], interaction.user.id, RsvpStatus.ACCEPTED)
            
            try:
                role_view = RoleSelectionView(interaction.client, self.db, event['event_id'], interaction.message.id, interaction.user)
                await interaction.user.send(
                    f"You have accepted the event: **{event['title']}**.\nPlease select your role for this event below.",
                    view=role_view
                )
                await interaction.followup.send("You have accepted the event! Please check your DMs to select your role.", ephemeral=True)
            except discord.Forbidden:
                await self.db.update_signup_role(event['event_id'], interaction.user.id, "Unassigned", None)
                await interaction.followup.send("You've accepted the event, but I couldn't DM you to select a role. Your role is set to 'Unassigned'. Please enable DMs from server members to use role selection.", ephemeral=True)
            
            await self.update_embed(interaction, event['event_id'])

        except Exception as e:
            print(f"Error in 'Accept' button: {e}"); traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message("An unexpected error occurred.", ephemeral=True)
            else:
                await interaction.followup.send("An unexpected error occurred.", ephemeral=True)

    @ui.button(label="Tentative", style=discord.ButtonStyle.secondary, custom_id="persistent_view:tentative")
    async def tentative(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        event = await self.db.get_event_by_message_id(interaction.message.id)
        if not event: return
        
        await self.db.set_rsvp(event['event_id'], interaction.user.id, RsvpStatus.TENTATIVE)
        await self.db.update_signup_role(event['event_id'], interaction.user.id, None, None)
        await self.update_embed(interaction, event['event_id'])

    @ui.button(label="Decline", style=discord.ButtonStyle.danger, custom_id="persistent_view:decline")
    async def decline(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        event = await self.db.get_event_by_message_id(interaction.message.id)
        if not event: return
        
        await self.db.set_rsvp(event['event_id'], interaction.user.id, RsvpStatus.DECLINED)
        await self.db.update_signup_role(event['event_id'], interaction.user.id, None, None)
        await self.update_embed(interaction, event['event_id'])

# --- Main Cog ---
class EventManagement(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        self.active_conversations = {}

    async def start_conversation(self, interaction: discord.Interaction, event_id: int = None):
        if interaction.user.id in self.active_conversations:
            await interaction.response.send_message("You are already in an active event creation process.", ephemeral=True)
            return
        try:
            await interaction.response.send_message("I've sent you a DM to start the process!", ephemeral=True)
            # This conversation logic is no longer used for web creation but kept for potential future use
            # conv = Conversation(self, interaction, self.db, event_id)
            # self.active_conversations[interaction.user.id] = conv
            # asyncio.create_task(conv.start())
        except discord.Forbidden:
            await interaction.followup.send("I couldn't send you a DM. Please check your privacy settings.", ephemeral=True)

    # --- Event Command Group ---
    event_group = app_commands.Group(name="event", description="Commands for creating and managing events.")

    @event_group.command(name="create", description="Create a new event via DM.")
    async def create(self, interaction: discord.Interaction):
        await self.start_conversation(interaction)

    # ... (other event commands like edit, delete would go here) ...

    # --- Setup Command Group ---
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

async def setup(bot: commands.Bot):
    # The database is now managed in main.py's state
    db = bot.web_app.state.db
    await bot.add_cog(EventManagement(bot, db))
    bot.add_view(PersistentEventView(db))
