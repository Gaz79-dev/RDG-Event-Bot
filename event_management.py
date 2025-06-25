import discord
from discord.ext import commands
from discord import app_commands, ui
import datetime
from typing import Optional
import traceback
import os

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


# --- Helper function to generate the event embed ---

async def create_event_embed(interaction: discord.Interaction, event_id: int, db: Database) -> discord.Embed:
    """Generates the main embed for an event, showing details and signups."""
    event = await db.get_event_by_id(event_id)
    if not event:
        return discord.Embed(title="Error", description="Event not found.", color=discord.Color.red())

    signups = await db.get_signups_for_event(event_id)

    embed = discord.Embed(
        title=f"📅 {event['title']}",
        description=event['description'],
        color=discord.Color.blue()
    )
    
    time_str = f"**Starts:** {discord.utils.format_dt(event['event_time'], style='F')} ({discord.utils.format_dt(event['event_time'], style='R')})"
    if event['end_time']:
        time_str += f"\n**Ends:** {discord.utils.format_dt(event['end_time'], style='F')}"
    embed.add_field(name="Time", value=time_str, inline=False)
    
    creator = interaction.guild.get_member(event['creator_id']) or (await interaction.client.fetch_user(event['creator_id']))
    embed.set_footer(text=f"Event ID: {event_id} | Created by: {creator.display_name}")

    # Process signups
    accepted_signups = {}
    tentative_users = []
    declined_users = []

    for r in ROLES: # Pre-populate to maintain order
        accepted_signups[r] = []

    for signup in signups:
        user = interaction.guild.get_member(signup['user_id']) or (await interaction.client.fetch_user(signup['user_id']))
        if not user: continue

        if signup['rsvp_status'] == RsvpStatus.ACCEPTED:
            role = signup['role_name'] or "Unassigned"
            subclass = signup['subclass_name']
            
            subclass_emoji = EMOJI_MAPPING.get(subclass, "")
            signup_text = f"**{user.display_name}**"
            if subclass:
                signup_text += f" ({subclass_emoji})"

            if role in accepted_signups:
                accepted_signups[role].append(signup_text)
        
        elif signup['rsvp_status'] == RsvpStatus.TENTATIVE:
            tentative_users.append(user.display_name)
        elif signup['rsvp_status'] == RsvpStatus.DECLINED:
            declined_users.append(user.display_name)

    total_accepted = sum(len(v) for v in accepted_signups.values())
    embed.add_field(name=f"✅ Accepted ({total_accepted})", value="\u200b", inline=False)
    
    # Display each primary role on a new line
    for role in ROLES:
        role_emoji = EMOJI_MAPPING.get(role, "")
        users_in_role = accepted_signups.get(role, [])
        field_value = "\n".join(users_in_role) or "No one yet"
        embed.add_field(name=f"{role_emoji} **{role}** ({len(users_in_role)})", value=field_value, inline=False)

    if tentative_users:
        embed.add_field(name=f"🤔 Tentative ({len(tentative_users)})", value=", ".join(tentative_users), inline=False)
    if declined_users:
        embed.add_field(name=f"❌ Declined ({len(declined_users)})", value=", ".join(declined_users), inline=False)

    return embed

# --- UI Components ---

class RoleSelect(ui.Select):
    """Dropdown for selecting a primary role."""
    def __init__(self, db: Database, event_id: int):
        self.db = db
        self.event_id = event_id # Store event_id directly
        options = [
            discord.SelectOption(label=role, emoji=EMOJI_MAPPING.get(role)) for role in ROLES
        ]
        super().__init__(placeholder="Choose your primary role...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer() 
        selected_role = self.values[0]
        
        required_role_id = await self.db.get_required_role_id(interaction.guild.id, selected_role)
        if required_role_id and required_role_id not in [r.id for r in interaction.user.roles]:
            await interaction.followup.send(f"You don't have the required Discord role to sign up as {selected_role}.", ephemeral=True)
            return
        
        if selected_role in SUBCLASSES:
            await interaction.followup.send("Now, select your subclass.", view=SubclassSelectView(self.db, selected_role, self.event_id), ephemeral=True)
        else:
            await self.db.update_signup_role(self.event_id, interaction.user.id, selected_role)
            event_record = await self.db.get_event_by_id(self.event_id)
            original_message = await interaction.channel.fetch_message(event_record['message_id'])
            new_embed = await create_event_embed(interaction, self.event_id, self.db)
            await original_message.edit(embed=new_embed)
            await interaction.followup.send(f"You have signed up as **{selected_role}**!", ephemeral=True)
        
        await interaction.message.delete()


class SubclassSelect(ui.Select):
    """Dropdown for selecting a subclass."""
    def __init__(self, db: Database, parent_role: str, event_id: int):
        self.db = db
        self.parent_role = parent_role
        self.event_id = event_id
        options = [
            discord.SelectOption(label=subclass, emoji=EMOJI_MAPPING.get(subclass)) 
            for subclass in SUBCLASSES.get(parent_role, [])
        ]
        super().__init__(placeholder=f"Choose your {parent_role} subclass...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        selected_subclass = self.values[0]

        required_role_id = await self.db.get_required_role_id(interaction.guild.id, selected_subclass)
        if required_role_id and required_role_id not in [r.id for r in interaction.user.roles]:
            await interaction.followup.send(f"You don't have the required Discord role to sign up as {selected_subclass}.", ephemeral=True)
            return
        
        await self.db.update_signup_role(self.event_id, interaction.user.id, self.parent_role, selected_subclass)
        
        event_record = await self.db.get_event_by_id(self.event_id)
        original_message = await interaction.guild.get_channel(event_record['channel_id']).fetch_message(event_record['message_id'])
        
        new_embed = await create_event_embed(interaction, self.event_id, self.db)
        await original_message.edit(embed=new_embed)
        
        await interaction.followup.send(f"You have signed up as **{self.parent_role} ({selected_subclass})**!", ephemeral=True)
        await interaction.message.delete()

class RoleSelectView(ui.View):
    def __init__(self, db: Database, event_id: int): # Accept event_id
        super().__init__(timeout=180)
        self.add_item(RoleSelect(db, event_id)) # Pass event_id to the select

class SubclassSelectView(ui.View):
    def __init__(self, db: Database, parent_role: str, event_id: int):
        super().__init__(timeout=180)
        self.add_item(SubclassSelect(db, parent_role, event_id))

class EventCreateModal(ui.Modal, title="Create New Event"):
    """Modal for creating a new event."""
    title_input = ui.TextInput(label="Event Title", style=discord.TextStyle.short, placeholder="e.g., Operation Serpent Strike", required=True, max_length=100)
    description_input = ui.TextInput(label="Description", style=discord.TextStyle.long, placeholder="Details about the mission, objectives, etc.", required=True)
    time_input = ui.TextInput(label="Start Time (DD-MM-YYYY HH:MM in UTC)", style=discord.TextStyle.short, placeholder="e.g., 20-07-2025 19:00", required=True)
    end_time_input = ui.TextInput(label="End Time (DD-MM-YYYY HH:MM, Optional)", style=discord.TextStyle.short, placeholder="e.g., 20-07-2025 21:00", required=False)

    def __init__(self, db: Database):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        try:
            event_time = datetime.datetime.strptime(self.time_input.value, "%d-%m-%Y %H:%M").replace(tzinfo=datetime.timezone.utc)
            end_time = None
            if self.end_time_input.value:
                end_time = datetime.datetime.strptime(self.end_time_input.value, "%d-%m-%Y %H:%M").replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            await interaction.response.send_message("Invalid date/time format. Please use DD-MM-YYYY HH:MM.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            event_id = await self.db.create_event(
                guild_id=interaction.guild.id,
                channel_id=interaction.channel.id,
                creator_id=interaction.user.id,
                title=self.title_input.value,
                description=self.description_input.value,
                event_time=event_time,
                end_time=end_time
            )
            if not event_id:
                await interaction.followup.send("Failed to create event in the database.", ephemeral=True)
                return

            view = PersistentEventView(self.db)
            embed = await create_event_embed(interaction, event_id, self.db)
            
            msg = await interaction.channel.send(embed=embed, view=view)
            await self.db.update_event_message_id(event_id, msg.id)
            
            await interaction.followup.send(f"Event '{self.title_input.value}' created! The discussion thread will be created automatically before the event.", ephemeral=True)
        except Exception as e:
            print(f"--- An error occurred in EventCreateModal on_submit ---")
            traceback.print_exc()
            print("--- End of error ---")
            await interaction.followup.send(f"An unexpected error occurred while creating the event. Please check the bot's logs for more details.", ephemeral=True)


class EventEditModal(ui.Modal, title="Edit Event"):
    """Modal for editing an existing event."""
    title_input = ui.TextInput(label="Event Title", style=discord.TextStyle.short, required=True, max_length=100)
    description_input = ui.TextInput(label="Description", style=discord.TextStyle.long, required=True)
    time_input = ui.TextInput(label="Start Time (DD-MM-YYYY HH:MM in UTC)", style=discord.TextStyle.short, required=True)
    end_time_input = ui.TextInput(label="End Time (DD-MM-YYYY HH:MM, Optional)", style=discord.TextStyle.short, required=False)


    def __init__(self, db: Database, event: dict):
        super().__init__()
        self.db = db
        self.event_id = event['event_id']

        # Pre-fill the form with existing data
        self.title_input.default = event['title']
        self.description_input.default = event['description']
        self.time_input.default = event['event_time'].strftime("%d-%m-%Y %H:%M")
        if event['end_time']:
            self.end_time_input.default = event['end_time'].strftime("%d-%m-%Y %H:%M")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            event_time = datetime.datetime.strptime(self.time_input.value, "%d-%m-%Y %H:%M").replace(tzinfo=datetime.timezone.utc)
            end_time = None
            if self.end_time_input.value:
                end_time = datetime.datetime.strptime(self.end_time_input.value, "%d-%m-%Y %H:%M").replace(tzinfo=datetime.timezone.utc)

        except ValueError:
            await interaction.response.send_message("Invalid date/time format. Please use DD-MM-YYYY HH:MM.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            await self.db.update_event(
                self.event_id,
                self.title_input.value,
                self.description_input.value,
                event_time,
                end_time
            )

            # Update the original event message
            event_record = await self.db.get_event_by_id(self.event_id)
            original_message = await interaction.guild.get_channel(event_record['channel_id']).fetch_message(event_record['message_id'])
            new_embed = await create_event_embed(interaction, self.event_id, self.db)
            await original_message.edit(embed=new_embed)

            await interaction.followup.send("Event updated successfully!", ephemeral=True)

        except Exception as e:
            print(f"--- An error occurred in EventEditModal on_submit ---")
            traceback.print_exc()
            await interaction.followup.send("An unexpected error occurred while updating the event.", ephemeral=True)


class PersistentEventView(ui.View):
    """The main view with RSVP and management buttons that persists across bot restarts."""
    def __init__(self, db: Database):
        super().__init__(timeout=None)
        self.db = db

    async def get_event_id(self, interaction: discord.Interaction) -> Optional[int]:
        event_record = await self.db.get_event_by_message_id(interaction.message.id)
        if event_record:
            return event_record['event_id']
        return None

    @ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="persistent_view:accept")
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        event_id = await self.get_event_id(interaction)
        if not event_id: 
            await interaction.response.send_message("Could not find the event ID for this message.", ephemeral=True)
            return

        await self.db.set_rsvp(event_id, interaction.user.id, RsvpStatus.ACCEPTED)
        await interaction.response.send_message("Please select your role.", view=RoleSelectView(self.db, event_id), ephemeral=True)
        
        new_embed = await create_event_embed(interaction, event_id, self.db)
        await interaction.message.edit(embed=new_embed)

    @ui.button(label="Tentative", style=discord.ButtonStyle.secondary, custom_id="persistent_view:tentative")
    async def tentative(self, interaction: discord.Interaction, button: ui.Button):
        event_id = await self.get_event_id(interaction)
        if not event_id: 
            await interaction.response.send_message("Could not find the event ID for this message.", ephemeral=True)
            return
        await self.db.set_rsvp(event_id, interaction.user.id, RsvpStatus.TENTATIVE)
        await interaction.response.defer()
        new_embed = await create_event_embed(interaction, event_id, self.db)
        await interaction.message.edit(embed=new_embed)

    @ui.button(label="Decline", style=discord.ButtonStyle.danger, custom_id="persistent_view:decline")
    async def decline(self, interaction: discord.Interaction, button: ui.Button):
        event_id = await self.get_event_id(interaction)
        if not event_id: 
            await interaction.response.send_message("Could not find the event ID for this message.", ephemeral=True)
            return
        await self.db.set_rsvp(event_id, interaction.user.id, RsvpStatus.DECLINED)
        await interaction.response.defer()
        new_embed = await create_event_embed(interaction, event_id, self.db)
        await interaction.message.edit(embed=new_embed)
    
    @ui.button(label="Edit", style=discord.ButtonStyle.primary, custom_id="persistent_view:edit")
    async def edit(self, interaction: discord.Interaction, button: ui.Button):
        try:
            event_id = await self.get_event_id(interaction)
            if not event_id: 
                await interaction.response.send_message("Could not find the event ID for this message.", ephemeral=True)
                return

            event = await self.db.get_event_by_id(event_id)
            if not event:
                await interaction.response.send_message("This event could not be found in the database.", ephemeral=True)
                return

            manager_role_id = await self.db.get_manager_role_id(interaction.guild.id)
            user_roles = [r.id for r in interaction.user.roles]

            is_creator = interaction.user.id == event['creator_id']
            is_manager = manager_role_id and manager_role_id in user_roles
            is_admin = interaction.user.guild_permissions.administrator

            if not (is_creator or is_manager or is_admin):
                await interaction.response.send_message("You don't have permission to edit this event.", ephemeral=True)
                return

            await interaction.response.send_modal(EventEditModal(self.db, event))

        except Exception as e:
            print(f"--- An error occurred in the edit button callback ---")
            traceback.print_exc()
            print("--- End of error ---")
            if not interaction.response.is_done():
                await interaction.response.send_message("An unexpected error occurred. Please check the bot's logs.", ephemeral=True)

    @ui.button(label="Delete", style=discord.ButtonStyle.danger, custom_id="persistent_view:delete")
    async def delete(self, interaction: discord.Interaction, button: ui.Button):
        event_id = await self.get_event_id(interaction)
        if not event_id: 
            await interaction.response.send_message("Could not find the event ID for this message.", ephemeral=True)
            return

        event = await self.db.get_event_by_id(event_id)
        manager_role_id = await self.db.get_manager_role_id(interaction.guild.id)
        user_roles = [r.id for r in interaction.user.roles]
        
        is_creator = interaction.user.id == event['creator_id']
        is_manager = manager_role_id and manager_role_id in user_roles
        is_admin = interaction.user.guild_permissions.administrator

        if not (is_creator or is_manager or is_admin):
            await interaction.response.send_message("You don't have permission to delete this event.", ephemeral=True)
            return
        
        await self.db.delete_event(event_id)
        await interaction.message.delete()
        await interaction.response.send_message(f"Event '{event['title']}' has been deleted.", ephemeral=True, delete_after=10)

class EventManagement(commands.Cog):
    """Cog for all event management commands and interactions."""
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db

    @app_commands.command(name="create", description="Create a new event.")
    async def create(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EventCreateModal(self.db))

    setup = app_commands.Group(name="setup", description="Commands for setting up the bot.")

    @setup.command(name="manager_role", description="Set the role that can manage events.")
    @app_commands.describe(role="The role to designate as Event Manager")
    @app_commands.default_permissions(administrator=True)
    async def set_manager_role(self, interaction: discord.Interaction, role: discord.Role):
        await self.db.set_manager_role(interaction.guild.id, role.id)
        await interaction.response.send_message(f"**{role.name}** has been set as the Event Manager role.", ephemeral=True)

    @setup.command(name="restricted_role", description="Set the required Discord role for an in-game role.")
    @app_commands.describe(ingame_role="The in-game role to restrict", discord_role="The Discord role required")
    @app_commands.choices(ingame_role=[app_commands.Choice(name=r, value=r) for r in RESTRICTED_ROLES])
    @app_commands.default_permissions(administrator=True)
    async def set_restricted_role(self, interaction: discord.Interaction, ingame_role: app_commands.Choice[str], discord_role: discord.Role):
        await self.db.set_restricted_role(interaction.guild.id, ingame_role.value, discord_role.id)
        await interaction.response.send_message(f"Users now need the **{discord_role.name}** role to sign up as **{ingame_role.name}**.", ephemeral=True)
    
    @setup.command(name="thread_schedule", description="Set how many hours before an event its discussion thread is created.")
    @app_commands.describe(hours="Number of hours before the event (e.g., 24)")
    @app_commands.default_permissions(administrator=True)
    async def set_thread_schedule(self, interaction: discord.Interaction, hours: app_commands.Range[int, 1, 168]):
        await self.db.set_thread_creation_hours(interaction.guild.id, hours)
        await interaction.response.send_message(f"Event threads will now be created **{hours}** hour(s) before the event starts.", ephemeral=True)


async def setup(bot: commands.Bot, db: Database):
    """Sets up the cog and adds the persistent view."""
    if not hasattr(db, 'get_event_by_id'):
        async def get_event_by_id(self, event_id: int):
            async with self.pool.acquire() as connection:
                return await connection.fetchrow("SELECT * FROM events WHERE event_id = $1;", event_id)
        Database.get_event_by_id = get_event_by_id
    
    bot.add_view(PersistentEventView(db))
    await bot.add_cog(EventManagement(bot, db))
