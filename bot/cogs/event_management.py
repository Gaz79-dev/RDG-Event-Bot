import discord
from discord.ext import commands
from discord import app_commands, ui
import datetime
import traceback
import os
import pytz
import re
from urllib.parse import urlencode
import asyncio
from typing import List, Dict, Optional
from collections import defaultdict
from dateutil.parser import parse

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
    "Tank Commander": os.getenv("EMOJI_TANK_COMMANDER", "�‍✈️"),
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

# --- New DM Conversation for Event Creation ---
class EventCreationConversation:
    def __init__(self, cog: 'EventManagement', interaction: discord.Interaction, channel: discord.TextChannel):
        self.cog = cog
        self.bot = cog.bot
        self.interaction = interaction
        self.user = interaction.user
        self.channel = channel
        self.guild = interaction.guild
        self.db = cog.db
        self.data = {}
        self.dm_channel = None
        self.timeout = 300.0

    async def start(self):
        self.dm_channel = self.user.dm_channel or await self.user.create_dm()
        await self.dm_channel.send(
            "Hello! Let's create a new event. Please reply to my questions. "
            "You can type `cancel` at any time to stop."
        )
        await self.ask_title()

    def check(self, message):
        return message.author == self.user and message.channel == self.dm_channel

    async def ask(self, question, next_step, validation_func=None):
        try:
            await self.dm_channel.send(question)
            msg = await self.bot.wait_for('message', check=self.check, timeout=self.timeout)

            if msg.content.lower() == 'cancel':
                await self.dm_channel.send("Event creation cancelled.")
                self.cog.end_conversation(self.user.id)
                return

            if validation_func:
                validated_data = await validation_func(msg.content)
                if validated_data is None:
                    await self.ask(question, next_step, validation_func)
                    return
                return await next_step(validated_data)
            else:
                return await next_step(msg.content)
        except asyncio.TimeoutError:
            await self.dm_channel.send("Event creation timed out. Please start over.")
            self.cog.end_conversation(self.user.id)

    async def ask_title(self):
        await self.ask("1. What is the **title** of the event?", self.ask_timezone)

    async def ask_timezone(self, title):
        self.data['title'] = title
        await self.ask("2. What is the **timezone**? (e.g., `BST`, `GMT`, `EST`, `US/Eastern`, `Europe/London`)", self.ask_start_datetime, self._validate_timezone)

    async def _validate_timezone(self, content):
        try:
            return pytz.timezone(content)
        except pytz.UnknownTimeZoneError:
            await self.dm_channel.send("Sorry, that's not a valid timezone. Please try again.")
            return None

    async def ask_start_datetime(self, tz):
        self.data['timezone'] = tz
        await self.ask("3. What is the **start date and time**? (Format: `DD-MM-YYYY HH:MM`)", self.ask_end_time, self._validate_start_datetime)

    async def _validate_start_datetime(self, content):
        try:
            dt = datetime.datetime.strptime(content, "%d-%m-%Y %H:%M")
            return self.data['timezone'].localize(dt)
        except ValueError:
            await self.dm_channel.send("Invalid format. Please use `DD-MM-YYYY HH:MM`.")
            return None

    async def ask_end_time(self, start_time):
        self.data['start_time'] = start_time
        await self.ask("4. What is the **end time**? (Format: `HH:MM`, or type `none`)", self.ask_description, self._validate_end_time)

    async def _validate_end_time(self, content):
        if content.lower() == 'none':
            return None
        try:
            end_t = datetime.datetime.strptime(content, "%H:%M").time()
            start_dt = self.data['start_time']
            end_dt = start_dt.replace(hour=end_t.hour, minute=end_t.minute, second=0, microsecond=0)
            if end_dt <= start_dt:
                end_dt += datetime.timedelta(days=1)
            return end_dt
        except ValueError:
            await self.dm_channel.send("Invalid format. Please use `HH:MM` or `none`.")
            return None

    async def ask_description(self, end_time):
        self.data['end_time'] = end_time
        await self.ask("5. What is the **description** for the event? (Type `none` for no description)", self.ask_recurring)

    async def ask_recurring(self, description):
        self.data['description'] = None if description.lower() == 'none' else description
        await self.ask("6. Is this a **recurring** event? (yes/no)", self.ask_restricted_roles, self._validate_yes_no)

    async def _validate_yes_no(self, content):
        if content.lower() in ['yes', 'y', 'no', 'n']:
            return content.lower().startswith('y')
        await self.dm_channel.send("Please answer `yes` or `no`.")
        return None

    async def ask_restricted_roles(self, is_recurring):
        self.data['is_recurring'] = is_recurring
        await self.ask("7. **Restrict signups to specific roles?** (Enter role names, separated by commas, or type `none`)", self.ask_mention_roles, self._validate_roles)

    async def _validate_roles(self, content):
        if content.lower() == 'none':
            return []
        role_names = [r.strip() for r in content.split(',')]
        roles = []
        for name in role_names:
            role = discord.utils.get(self.guild.roles, name=name)
            if role:
                roles.append(role)
            else:
                await self.dm_channel.send(f"I couldn't find a role named `{name}`. Please check the spelling and try again.")
                return None
        return roles

    async def ask_mention_roles(self, restricted_roles):
        self.data['restrict_to_role_ids'] = [r.id for r in restricted_roles]
        await self.ask("8. **Mention roles in the announcement?** (Enter role names, separated by commas, or type `none`)", self.finish, self._validate_roles)

    async def finish(self, mention_roles):
        self.data['mention_role_ids'] = [r.id for r in mention_roles]
        
        try:
            event_id = await self.db.create_event(
                self.guild.id,
                self.channel.id,
                self.user.id,
                self.data
            )
            
            view = PersistentEventView(self.db)
            embed = await create_event_embed(self.bot, event_id, self.db)
            
            content_mentions = " ".join([f"<@&{rid}>" for rid in self.data['mention_role_ids']])
            msg = await self.channel.send(content=content_mentions, embed=embed, view=view)
            await self.db.update_event_message_id(event_id, msg.id)

            await self.dm_channel.send(f"✅ Event '{self.data['title']}' created successfully in {self.channel.mention}!")
        except Exception as e:
            await self.dm_channel.send("I failed to create the event. Please check the bot logs.")
            print(f"Error finishing conversation: {e}")
        finally:
            self.cog.end_conversation(self.user.id)

# --- Main Cog ---
class EventManagement(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        self.active_conversations = {}

    def end_conversation(self, user_id: int):
        if user_id in self.active_conversations:
            del self.active_conversations[user_id]

    async def _start_dm_conversation_task(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """A helper function to run the conversation as a background task."""
        try:
            # We send an initial followup to the deferred response so the user knows what's happening.
            await interaction.followup.send("I've sent you a DM to start creating the event!", ephemeral=True)
            conv = EventCreationConversation(self, interaction, channel)
            self.active_conversations[interaction.user.id] = conv
            await conv.start()
        except discord.Forbidden:
            await interaction.followup.send("I couldn't send you a DM. Please enable DMs from server members.", ephemeral=True)
            self.end_conversation(interaction.user.id)
        except Exception as e:
            print(f"Error during DM conversation task: {e}")
            traceback.print_exc()
            try:
                await interaction.followup.send("An unexpected error occurred while starting our conversation.", ephemeral=True)
            except discord.HTTPException:
                pass 
            self.end_conversation(interaction.user.id)

    # --- Event Command Group ---
    event_group = app_commands.Group(name="event", description="Commands for creating and managing events.")

    @event_group.command(name="create", description="Create a new event via DM.")
    @app_commands.describe(channel="The channel where the event will be posted.")
    async def create(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if interaction.user.id in self.active_conversations:
            return await interaction.response.send_message("You are already creating an event.", ephemeral=True)
        
        # Defer the response immediately to guarantee a response within 3 seconds.
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        # Run the actual conversation logic in a background task.
        asyncio.create_task(self._start_dm_conversation_task(interaction, channel))

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
    db = bot.web_app.state.db
    await bot.add_cog(EventManagement(bot, db))
    bot.add_view(PersistentEventView(db))
�
