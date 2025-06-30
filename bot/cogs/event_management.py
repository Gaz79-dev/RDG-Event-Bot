import discord
from discord.ext import commands
from discord import app_commands, ui
import datetime
import traceback
import os
import pytz
import asyncio
from typing import List, Optional
from collections import defaultdict

# Use an absolute import from the 'bot' package root for robustness
from bot.utils.database import Database, RsvpStatus, ROLES, SUBCLASSES, RESTRICTED_ROLES

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
            if squad_roles and squad_roles.get('squad_arty_role_id') in user_role_ids: specialty = " (Arty)"
            elif squad_roles and squad_roles.get('squad_armour_role_id') in user_role_ids: specialty = " (Armour)"
            elif squad_roles and squad_roles.get('squad_attack_role_id') in user_role_ids and squad_roles.get('squad_defence_role_id') in user_role_ids: specialty = " (Flex)"
            elif squad_roles and squad_roles.get('squad_attack_role_id') in user_role_ids: specialty = " (Attack)"
            elif squad_roles and squad_roles.get('squad_defence_role_id') in user_role_ids: specialty = " (Defence)"

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
        if self.role is None:
            await self.db.update_signup_role(self.event_id, self.user.id, "Unassigned", None)
            await self.update_original_embed()
            try:
                await self.user.send("Your role selection has timed out. You have been marked as 'Unassigned'.")
            except discord.Forbidden:
                pass

    async def update_original_embed(self):
        event = await self.db.get_event_by_id(self.event_id)
        if not event: return
        try:
            channel = self.bot.get_channel(event['channel_id']) or await self.bot.fetch_channel(event['channel_id'])
            message = await channel.fetch_message(self.message_id)
            new_embed = await create_event_embed(self.bot, self.event_id, self.db)
            await message.edit(embed=new_embed)
        except (discord.NotFound, discord.Forbidden):
            pass

class PersistentEventView(ui.View):
    def __init__(self, db: Database):
        super().__init__(timeout=None)
        self.db = db

    async def update_embed(self, interaction: discord.Interaction, event_id: int):
        try:
            new_embed = await create_event_embed(interaction.client, event_id, self.db)
            await interaction.message.edit(embed=new_embed)
        except Exception as e:
            print(f"Error updating embed: {e}")

    @ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="persistent_view:accept")
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        event = await self.db.get_event_by_message_id(interaction.message.id)
        if not event: return await interaction.followup.send("Event not found.", ephemeral=True)
        await self.db.set_rsvp(event['event_id'], interaction.user.id, RsvpStatus.ACCEPTED)
        try:
            view = RoleSelectionView(interaction.client, self.db, event['event_id'], interaction.message.id, interaction.user)
            await interaction.user.send(f"You accepted **{event['title']}**. Please select your role:", view=view)
            await interaction.followup.send("Check your DMs to select your role!", ephemeral=True)
        except discord.Forbidden:
            await self.db.update_signup_role(event['event_id'], interaction.user.id, "Unassigned", None)
            await interaction.followup.send("Accepted, but I couldn't DM you. Your role is 'Unassigned'.", ephemeral=True)
        await self.update_embed(interaction, event['event_id'])

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

# --- Modal for Event Creation ---
class EventCreationModal(ui.Modal, title='Create a New Event'):
    def __init__(self, bot: commands.Bot, db: Database, channel: discord.TextChannel):
        super().__init__()
        self.bot = bot
        self.db = db
        self.target_channel = channel

    # --- Modal Fields (Limited to 5) ---
    event_title = ui.TextInput(label='Event Title', placeholder='e.g., Operation Overlord', required=True)
    event_description = ui.TextInput(label='Description', style=discord.TextStyle.long, placeholder='Details about the event...', required=False)
    event_timezone = ui.TextInput(label='Timezone', placeholder='e.g., Europe/London, US/Eastern, EST, BST', required=True, default='UTC')
    start_datetime = ui.TextInput(label='Start Date & Time (DD-MM-YYYY HH:MM)', placeholder='e.g., 25-12-2024 19:30', required=True)
    end_time = ui.TextInput(label='End Time (HH:MM) (Optional)', placeholder='e.g., 21:00', required=False)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        data = {}
        errors = []
        tz = None

        # --- Data Validation ---
        try:
            tz = pytz.timezone(self.event_timezone.value)
            data['timezone'] = str(tz)
        except pytz.UnknownTimeZoneError:
            errors.append(f"Invalid Timezone: `{self.event_timezone.value}`. Please use a valid identifier like `Europe/London`.")
        
        if tz:
            try:
                start_dt_naive = datetime.datetime.strptime(self.start_datetime.value, "%d-%m-%Y %H:%M")
                data['start_time'] = tz.localize(start_dt_naive)
            except ValueError:
                errors.append(f"Invalid Start Date/Time format: `{self.start_datetime.value}`. Must be `DD-MM-YYYY HH:MM`.")

        if self.end_time.value:
            try:
                end_t = datetime.datetime.strptime(self.end_time.value, "%H:%M").time()
                start_dt = data.get('start_time')
                if start_dt:
                    end_dt = start_dt.replace(hour=end_t.hour, minute=end_t.minute, second=0, microsecond=0)
                    if end_dt <= start_dt:
                        end_dt += datetime.timedelta(days=1)
                    data['end_time'] = end_dt
            except (ValueError, KeyError):
                 if 'start_time' not in data:
                     errors.append("Cannot set End Time without a valid Start Time.")
                 else:
                    errors.append(f"Invalid End Time format: `{self.end_time.value}`. Must be `HH:MM`.")

        if errors:
            await interaction.followup.send("Please correct the following errors:\n- " + "\n- ".join(errors), ephemeral=True)
            return

        # --- Data Preparation & DB Insertion ---
        data['title'] = self.event_title.value
        data['description'] = self.event_description.value or "No description provided."
        # Advanced features are hardcoded here but could be implemented via an `/event edit` command.
        data['is_recurring'] = False
        data['mention_role_ids'] = []
        data['restrict_to_role_ids'] = []

        try:
            event_id = await self.db.create_event(
                interaction.guild.id,
                self.target_channel.id,
                interaction.user.id,
                data
            )
            
            view = PersistentEventView(self.db)
            embed = await create_event_embed(self.bot, event_id, self.db)
            
            msg = await self.target_channel.send(embed=embed, view=view)
            await self.db.update_event_message_id(event_id, msg.id)

            await interaction.followup.send(f"✅ Event '{data['title']}' created successfully in {self.target_channel.mention}!", ephemeral=True)

        except Exception as e:
            print(f"Error during modal submission: {e}")
            traceback.print_exc()
            await interaction.followup.send("An unexpected error occurred while creating the event. Please check the bot logs.", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        traceback.print_exc()
        await interaction.followup.send('Oops! Something went wrong with the form.', ephemeral=True)

# --- Main Cog ---
# --- FIX: Converted the Cog to a GroupCog to ensure commands are registered ---
class EventManagement(commands.GroupCog, group_name="event", description="Commands for creating and managing events."):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        super().__init__()

    @app_commands.command(name="create", description="Create a new event.")
    @app_commands.describe(channel="The channel where the event announcement will be posted.")
    async def create(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Opens a form to create a new event."""
        modal = EventCreationModal(self.bot, self.db, channel)
        await interaction.response.send_modal(modal)

    # --- Setup Command Group (This needs to be a separate top-level cog or command) ---
    # For now, we will define it as a separate top-level group.
    
setup_group = app_commands.Group(name="setup", description="Commands for setting up the bot.", default_permissions=discord.Permissions(administrator=True))
squad_config_group = app_commands.Group(name="squad_config", description="Commands for configuring squad roles.", parent=setup_group)

@squad_config_group.command(name="attack_role", description="Set the role for Attack specialty.")
async def set_attack_role(interaction: discord.Interaction, role: discord.Role):
    # We need access to the database, which requires a little restructuring.
    # The simplest way is to fetch it from the bot instance.
    db = interaction.client.web_app.state.db
    await db.set_squad_config_role(interaction.guild.id, "attack", role.id)
    await interaction.response.send_message(f"Attack specialty role set to {role.mention}.", ephemeral=True)

@squad_config_group.command(name="defence_role", description="Set the role for Defence specialty.")
async def set_defence_role(interaction: discord.Interaction, role: discord.Role):
    db = interaction.client.web_app.state.db
    await db.set_squad_config_role(interaction.guild.id, "defence", role.id)
    await interaction.response.send_message(f"Defence specialty role set to {role.mention}.", ephemeral=True)

@squad_config_group.command(name="arty_role", description="Set the role for Arty Certified players.")
async def set_arty_role(interaction: discord.Interaction, role: discord.Role):
    db = interaction.client.web_app.state.db
    await db.set_squad_config_role(interaction.guild.id, "arty", role.id)
    await interaction.response.send_message(f"Arty specialty role set to {role.mention}.", ephemeral=True)

@squad_config_group.command(name="armour_role", description="Set the role for Armour specialty players.")
async def set_armour_role(interaction: discord.Interaction, role: discord.Role):
    db = interaction.client.web_app.state.db
    await db.set_squad_config_role(interaction.guild.id, "armour", role.id)
    await interaction.response.send_message(f"Armour specialty role set to {role.mention}.", ephemeral=True)


async def setup(bot: commands.Bot):
    db = bot.web_app.state.db
    # --- FIX: Add the cog to the bot ---
    await bot.add_cog(EventManagement(bot, db))
    # --- FIX: Add the separate setup command tree to the bot ---
    bot.tree.add_command(setup_group)
    bot.add_view(PersistentEventView(db))
