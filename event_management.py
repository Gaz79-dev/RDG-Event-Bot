import discord
from discord.ext import commands
from discord import app_commands, ui
import datetime
import traceback
import os
import pytz
from urllib.parse import urlencode
import asyncio
from typing import List

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
    gcal_link = create_google_calendar_link(event)
    embed_description = f"{event['description']}\n\n[Add to Google Calendar]({gcal_link})"
    embed = discord.Embed(title=f"📅 {event['title']}", description=embed_description, color=discord.Color.blue())
    
    time_str = f"**Starts:** {discord.utils.format_dt(event['event_time'], style='F')} ({discord.utils.format_dt(event['event_time'], style='R')})"
    if event['end_time']: time_str += f"\n**Ends:** {discord.utils.format_dt(event['end_time'], style='F')}"
    if event['timezone']: time_str += f"\nTimezone: {event['timezone']}"
    embed.add_field(name="Time", value=time_str, inline=False)
    
    if event.get('is_recurring') and event.get('recurrence_rule'):
        embed.add_field(name="🔁 Recurring Event", value=f"This event recurs **{event['recurrence_rule'].capitalize()}**.", inline=False)

    creator = guild.get_member(event['creator_id']) or (await bot.fetch_user(event['creator_id']))
    embed.set_footer(text=f"Event ID: {event_id} | Created by: {creator.display_name}")

    accepted_signups, tentative_users, declined_users = {}, [], []
    for r in ROLES: accepted_signups[r] = []
    for signup in signups:
        user = guild.get_member(signup['user_id']) or (await bot.fetch_user(signup['user_id']))
        if not user: continue
        if signup['rsvp_status'] == RsvpStatus.ACCEPTED:
            role = signup['role_name'] or "Unassigned"
            subclass = signup['subclass_name']
            subclass_emoji = EMOJI_MAPPING.get(subclass, "")
            signup_text = f"**{user.display_name}**"
            if subclass: signup_text += f" ({subclass_emoji})"
            if role in accepted_signups: accepted_signups[role].append(signup_text)
        elif signup['rsvp_status'] == RsvpStatus.TENTATIVE: tentative_users.append(user.display_name)
        elif signup['rsvp_status'] == RsvpStatus.DECLINED: declined_users.append(user.display_name)

    total_accepted = sum(len(v) for v in accepted_signups.values())
    embed.add_field(name=f"✅ Accepted ({total_accepted})", value="\u200b", inline=False)
    for role in ROLES:
        role_emoji = EMOJI_MAPPING.get(role, "")
        users_in_role = accepted_signups.get(role, [])
        field_value = "\n".join(users_in_role) or "No one yet"
        embed.add_field(name=f"{role_emoji} **{role}** ({len(users_in_role)})", value=field_value, inline=False)

    if tentative_users: embed.add_field(name=f"🤔 Tentative ({len(tentative_users)})", value=", ".join(tentative_users), inline=False)
    if declined_users: embed.add_field(name=f"❌ Declined ({len(declined_users)})", value=", ".join(declined_users), inline=False)
    
    if event.get('restrict_to_role_ids'):
        roles = [guild.get_role(r_id) for r_id in event['restrict_to_role_ids']]
        role_names = [r.name for r in roles if r]
        embed.add_field(name="🔒 Restricted Event", value=f"Sign-ups are restricted to members with the following role(s): **{', '.join(role_names)}**", inline=False)

    return embed

# --- UI Components ---

class MultiRoleSelectView(ui.View):
    """A view containing a multi-select role dropdown, using a decorator for the callback."""
    selection: List[int] = None

    def __init__(self, placeholder: str):
        super().__init__(timeout=180)
        # The select menu is defined by the decorator below.
        # We access it via its `__discord_ui_model_type__` attribute to set the placeholder.
        # This ensures the placeholder is set correctly on the component.
        for child in self.children:
            if isinstance(child, ui.RoleSelect):
                child.placeholder = placeholder
                break

    @ui.select(cls=ui.RoleSelect, min_values=1, max_values=25)
    async def role_select(self, interaction: discord.Interaction, select: ui.RoleSelect):
        """Callback for when the user selects roles."""
        self.selection = [role.id for role in select.values]
        await interaction.response.defer()
        self.stop()


class ConfirmationView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.value = None
    @ui.button(label="Yes", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        self.value = True; await interaction.response.defer(); self.stop()
    @ui.button(label="No/Skip", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        self.value = False; await interaction.response.defer(); self.stop()

class RoleSelect(ui.Select):
    def __init__(self, db: Database, event_id: int):
        self.db, self.event_id = db, event_id
        options = [discord.SelectOption(label=role, emoji=EMOJI_MAPPING.get(role)) for role in ROLES]
        super().__init__(placeholder="Choose your primary role...", options=options)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        selected_role = self.values[0]
        event = await self.db.get_event_by_id(self.event_id)
        guild = interaction.client.get_guild(event['guild_id'])
        member = await guild.fetch_member(interaction.user.id)
        req_role_id = await self.db.get_required_role_id(guild.id, selected_role)
        if req_role_id and req_role_id not in [r.id for r in member.roles]:
            await interaction.followup.send(f"You don't have the required Discord role to sign up as {selected_role}.", ephemeral=True)
            return
        if selected_role in SUBCLASSES:
            await interaction.followup.send("Now, select your subclass.", view=SubclassSelectView(self.db, selected_role, self.event_id), ephemeral=True)
        else:
            await self.db.update_signup_role(self.event_id, interaction.user.id, selected_role)
            await interaction.followup.send(f"You have signed up as **{selected_role}**! The event has been updated.", ephemeral=True)
            msg = await guild.get_channel(event['channel_id']).fetch_message(event['message_id'])
            await msg.edit(embed=await create_event_embed(interaction.client, self.event_id, self.db))
        await interaction.message.delete()

class SubclassSelect(ui.Select):
    def __init__(self, db: Database, parent_role: str, event_id: int):
        self.db, self.parent_role, self.event_id = db, parent_role, event_id
        options = [discord.SelectOption(label=sc, emoji=EMOJI_MAPPING.get(sc)) for sc in SUBCLASSES.get(parent_role, [])]
        super().__init__(placeholder=f"Choose your {parent_role} subclass...", options=options)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        subclass = self.values[0]
        event = await self.db.get_event_by_id(self.event_id)
        guild = interaction.client.get_guild(event['guild_id'])
        member = await guild.fetch_member(interaction.user.id)
        req_role_id = await self.db.get_required_role_id(guild.id, subclass)
        if req_role_id and req_role_id not in [r.id for r in member.roles]:
            await interaction.followup.send(f"You don't have the required Discord role to sign up as {subclass}.", ephemeral=True)
            return
        await self.db.update_signup_role(self.event_id, interaction.user.id, self.parent_role, subclass)
        await interaction.followup.send(f"You have signed up as **{self.parent_role} ({subclass})**! The event has been updated.", ephemeral=True)
        msg = await guild.get_channel(event['channel_id']).fetch_message(event['message_id'])
        await msg.edit(embed=await create_event_embed(interaction.client, self.event_id, self.db))
        await interaction.message.delete()

class RoleSelectView(ui.View):
    def __init__(self, db: Database, event_id: int):
        super().__init__(timeout=180); self.add_item(RoleSelect(db, event_id))

class SubclassSelectView(ui.View):
    def __init__(self, db: Database, parent_role: str, event_id: int):
        super().__init__(timeout=180); self.add_item(SubclassSelect(db, parent_role, event_id))

class PersistentEventView(ui.View):
    def __init__(self, db: Database):
        super().__init__(timeout=None); self.db = db
    async def check_restrictions(self, interaction, event):
        if event.get('restrict_to_role_ids'):
            if not any(r.id in event['restrict_to_role_ids'] for r in interaction.user.roles):
                roles = [interaction.guild.get_role(r_id) for r_id in event['restrict_to_role_ids']]
                await interaction.response.send_message(f"Sorry, this event is restricted to: **{', '.join([r.name for r in roles if r])}**", ephemeral=True)
                return False
        return True
    async def update_embed(self, interaction, event_id):
        new_embed = await create_event_embed(interaction.client, event_id, self.db)
        await interaction.message.edit(embed=new_embed)
    @ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="persistent_view:accept")
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        try:
            event = await self.db.get_event_by_message_id(interaction.message.id)
            if not event or not await self.check_restrictions(interaction, event): return
            await self.db.set_rsvp(event['event_id'], interaction.user.id, RsvpStatus.ACCEPTED)
            await interaction.response.defer()
            await self.update_embed(interaction, event['event_id'])
            await interaction.followup.send("I've sent you a DM to complete your signup!", ephemeral=True)
            await interaction.user.send(f"To complete your signup for **{event['title']}**, please select your role below.", view=RoleSelectView(self.db, event['event_id']))
        except discord.Forbidden:
            await interaction.followup.send("I couldn't send you a DM. Please check your privacy settings.", ephemeral=True)
        except Exception as e:
            print(f"Error in 'Accept' button: {e}"); traceback.print_exc()
    @ui.button(label="Tentative", style=discord.ButtonStyle.secondary, custom_id="persistent_view:tentative")
    async def tentative(self, interaction: discord.Interaction, button: ui.Button):
        event = await self.db.get_event_by_message_id(interaction.message.id)
        if not event or not await self.check_restrictions(interaction, event): return
        await self.db.set_rsvp(event['event_id'], interaction.user.id, RsvpStatus.TENTATIVE)
        await interaction.response.defer()
        await self.update_embed(interaction, event['event_id'])
    @ui.button(label="Decline", style=discord.ButtonStyle.danger, custom_id="persistent_view:decline")
    async def decline(self, interaction: discord.Interaction, button: ui.Button):
        event = await self.db.get_event_by_message_id(interaction.message.id)
        if not event: return
        await self.db.set_rsvp(event['event_id'], interaction.user.id, RsvpStatus.DECLINED)
        await interaction.response.defer()
        await self.update_embed(interaction, event['event_id'])

class ConfirmDeleteView(ui.View):
    def __init__(self, interaction: discord.Interaction):
        super().__init__(timeout=60); self.value, self.original_interaction = None, interaction
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.original_interaction.user.id
    @ui.button(label="Confirm Delete", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        self.value = True; await interaction.response.defer(); self.stop()
    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        self.value = False; await interaction.response.defer(); self.stop()

# --- Permission Checks ---
async def is_event_manager(interaction: discord.Interaction) -> bool:
    """Check if the user is an administrator or has an event manager role."""
    if interaction.user.guild_permissions.administrator:
        return True
    
    cog = interaction.client.get_cog("EventManagement")
    if not cog:
        return False
        
    manager_roles = await cog.db.get_manager_role_ids(interaction.guild.id)
    if not manager_roles:
        await interaction.response.send_message("No Event Manager roles are configured for this server.", ephemeral=True)
        return False

    user_role_ids = {role.id for role in interaction.user.roles}
    if not any(role_id in user_role_ids for role_id in manager_roles):
        await interaction.response.send_message("You do not have the required Event Manager role to use this command.", ephemeral=True)
        return False
        
    return True

class EventManagement(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot, self.db, self.active_conversations = bot, db, {}
        
    async def start_conversation(self, interaction: discord.Interaction, event_id: int = None):
        if interaction.user.id in self.active_conversations:
            await interaction.response.send_message("You are already in an active event creation process.", ephemeral=True)
            return
        try:
            await interaction.response.send_message("I've sent you a DM to start the process!", ephemeral=True)
            conv = Conversation(self, interaction, self.db, event_id)
            self.active_conversations[interaction.user.id] = conv
            asyncio.create_task(conv.start())
        except discord.Forbidden:
            await interaction.followup.send("I couldn't send you a DM. Please check your privacy settings.", ephemeral=True)
        except Exception as e:
            print(f"Error starting conversation: {e}"); traceback.print_exc()

    @app_commands.command(name="create", description="Create a new event via DM.")
    @app_commands.check(is_event_manager)
    async def create(self, interaction: discord.Interaction):
        await self.start_conversation(interaction)

    @app_commands.command(name="edit", description="Edit an existing event via DM.")
    @app_commands.describe(event_id="The ID of the event to edit.")
    @app_commands.check(is_event_manager)
    async def edit(self, interaction: discord.Interaction, event_id: int):
        event = await self.db.get_event_by_id(event_id)
        if not event or event['guild_id'] != interaction.guild_id:
            await interaction.response.send_message("Event not found.", ephemeral=True); return
        if not interaction.user.guild_permissions.administrator and event['creator_id'] != interaction.user.id:
             manager_roles = await self.db.get_manager_role_ids(interaction.guild.id)
             user_role_ids = {role.id for role in interaction.user.roles}
             if not any(role_id in user_role_ids for role_id in manager_roles):
                await interaction.response.send_message("You can only edit events you have created.", ephemeral=True); return
        await self.start_conversation(interaction, event_id)

    @app_commands.command(name="delete", description="Delete an existing event by its ID.")
    @app_commands.describe(event_id="The ID of the event to delete.")
    @app_commands.check(is_event_manager)
    async def delete(self, interaction: discord.Interaction, event_id: int):
        event = await self.db.get_event_by_id(event_id)
        if not event or event['guild_id'] != interaction.guild_id:
            await interaction.response.send_message("Event not found in this server.", ephemeral=True); return
        
        view = ConfirmDeleteView(interaction)
        await interaction.response.send_message(f"Are you sure you want to permanently delete event: **{event['title']}** (ID: {event_id})?", view=view, ephemeral=True)
        await view.wait()
        if view.value:
            try:
                if event.get('message_id'):
                    channel = self.bot.get_channel(event['channel_id'])
                    if channel: await channel.get_partial_message(event['message_id']).delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                print(f"Could not delete message for event {event_id}: {e}")
            await self.db.delete_event(event_id)
            await interaction.followup.send("Event has been deleted.", ephemeral=True)
        else:
            await interaction.followup.send("Deletion cancelled.", ephemeral=True)

    setup = app_commands.Group(name="setup", description="Commands for setting up the bot.", default_permissions=discord.Permissions(administrator=True))

    @setup.command(name="manager_roles", description="Set the roles that can manage events.")
    async def set_manager_roles(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True); return
        
        view = MultiRoleSelectView("Select one or more Event Manager roles")
        await interaction.response.send_message("Please select the roles that should be allowed to manage events.", view=view, ephemeral=True)
        await view.wait()

        if view.selection is not None:
            await self.db.set_manager_roles(interaction.guild.id, view.selection)
            role_mentions = [f"<@&{role_id}>" for role_id in view.selection]
            await interaction.followup.send(f"Event Manager roles have been set to: {', '.join(role_mentions) if role_mentions else 'None'}.", ephemeral=True)
        else:
            await interaction.followup.send("No roles selected. The operation was cancelled or timed out.", ephemeral=True)

    @setup.command(name="restricted_role", description="Set the required Discord role for an in-game role.")
    @app_commands.describe(ingame_role="The in-game role to restrict", discord_role="The Discord role required")
    @app_commands.choices(ingame_role=[app_commands.Choice(name=r, value=r) for r in RESTRICTED_ROLES])
    async def set_restricted_role(self, interaction: discord.Interaction, ingame_role: app_commands.Choice[str], discord_role: discord.Role):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True); return
        await self.db.set_restricted_role(interaction.guild.id, ingame_role.value, discord_role.id)
        await interaction.response.send_message(f"Users now need the **{discord_role.name}** role to sign up as **{ingame_role.name}**.", ephemeral=True)

    @setup.command(name="thread_schedule", description="Set how many hours before an event its discussion thread is created.")
    @app_commands.describe(hours="Number of hours before the event (e.g., 24)")
    async def set_thread_schedule(self, interaction: discord.Interaction, hours: app_commands.Range[int, 1, 168]):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True); return
        await self.db.set_thread_creation_hours(interaction.guild.id, hours)
        await interaction.response.send_message(f"Event threads will now be created **{hours}** hour(s) before the event starts.", ephemeral=True)

async def setup(bot: commands.Bot, db: Database):
    bot.add_view(PersistentEventView(db))
    await bot.add_cog(EventManagement(bot, db))

class Conversation:
    def __init__(self, cog: EventManagement, interaction: discord.Interaction, db: Database, event_id: int = None):
        self.cog, self.bot, self.interaction, self.user, self.db, self.event_id = cog, cog.bot, interaction, interaction.user, db, event_id
        self.data, self.is_finished = {}, False
    async def start(self):
        try:
            if self.event_id:
                event_data = await self.db.get_event_by_id(self.event_id)
                self.data = dict(event_data) if event_data else {}
                await self.user.send(f"Now editing event: **{self.data.get('title', 'Unknown')}**.\nYou can type `cancel` at any time to stop.")
            else:
                await self.user.send("Let's create a new event! You can type `cancel` at any time to stop.")
            await self.run_conversation()
        except Exception as e:
            print(f"Error at start of conversation for {self.user.id}: {e}"); traceback.print_exc(); await self.cancel()
    async def run_conversation(self):
        steps = [
            ("What is the title of the event?", self.process_text, 'title'),
            ("What timezone should this event use? (e.g., `UTC`, `EST`, `Europe/London`).", self.process_timezone, 'timezone'),
            ("What is the start date and time? Please use `DD-MM-YYYY HH:MM` format.", self.process_start_time, 'start_time'),
            ("What is the end date and time? (Optional, press Enter to skip). Format: `DD-MM-YYYY HH:MM`.", self.process_end_time, 'end_time'),
            ("Please provide a detailed description for the event.", self.process_text, 'description'),
            (None, self.ask_is_recurring, 'is_recurring'),
            (None, self.ask_mention_roles, 'mention_role_ids'),
            (None, self.ask_restrict_roles, 'restrict_to_role_ids'),
        ]
        for prompt, processor, data_key in steps:
            if not await processor(prompt, data_key): return
        await self.finish()
    async def _wait_for_message(self):
        return await self.bot.wait_for('message', check=lambda m: m.author == self.user and isinstance(m.channel, discord.DMChannel), timeout=300.0)
    async def process_text(self, prompt, data_key):
        if self.event_id and self.data.get(data_key): prompt += f"\n(Current: `{self.data.get(data_key)}`)"
        await self.user.send(prompt)
        try:
            msg = await self._wait_for_message()
            if msg.content.lower() == 'cancel': await self.cancel(); return False
            self.data[data_key] = msg.content; return True
        except asyncio.TimeoutError: await self.user.send("You took too long. Conversation cancelled."); await self.cancel(); return False
    async def process_timezone(self, prompt, data_key):
        while True:
            p = prompt + (f"\n(Current: `{self.data.get(data_key)}`)" if self.event_id and self.data.get(data_key) else "")
            await self.user.send(p)
            try:
                msg = await self._wait_for_message()
                if msg.content.lower() == 'cancel': await self.cancel(); return False
                try: pytz.timezone(msg.content); self.data[data_key] = msg.content; return True
                except pytz.UnknownTimeZoneError: await self.user.send("Invalid timezone. Please try again.")
            except asyncio.TimeoutError: await self.user.send("You took too long. Conversation cancelled."); await self.cancel(); return False
    async def process_start_time(self, prompt, data_key):
        while True:
            val = self.data.get(data_key).strftime('%d-%m-%Y %H:%M') if self.data.get(data_key) else ''
            p = prompt + (f"\n(Current: `{val}`)" if self.event_id and val else "")
            await self.user.send(p)
            try:
                msg = await self._wait_for_message()
                if msg.content.lower() == 'cancel': await self.cancel(); return False
                try:
                    tz = pytz.timezone(self.data.get('timezone', 'UTC'))
                    self.data[data_key] = tz.localize(datetime.datetime.strptime(msg.content, "%d-%m-%Y %H:%M")); return True
                except ValueError: await self.user.send("Invalid date format. Use `DD-MM-YYYY HH:MM`.")
            except asyncio.TimeoutError: await self.user.send("You took too long. Conversation cancelled."); await self.cancel(); return False
    async def process_end_time(self, prompt, data_key):
        val = self.data.get(data_key).strftime('%d-%m-%Y %H:%M') if self.data.get(data_key) else 'Not set'
        p = prompt + (f"\n(Current: `{val}`)" if self.event_id else "")
        await self.user.send(p)
        try:
            msg = await self._wait_for_message()
            if msg.content.lower() == 'cancel': await self.cancel(); return False
            if not msg.content: self.data[data_key] = None; return True
            try:
                tz = pytz.timezone(self.data.get('timezone', 'UTC'))
                self.data[data_key] = tz.localize(datetime.datetime.strptime(msg.content, "%d-%m-%Y %H:%M")); return True
            except ValueError:
                await self.user.send("Invalid date format. Use `DD-MM-YYYY HH:MM`."); return await self.process_end_time(prompt, data_key)
        except asyncio.TimeoutError: await self.user.send("You took too long. Conversation cancelled."); await self.cancel(); return False
    async def ask_is_recurring(self, prompt, data_key):
        view = ConfirmationView()
        p = "Is this a recurring event?" + (f"\n(Current: `{'Yes' if self.data.get('is_recurring') else 'No'}`)" if self.event_id else "")
        msg = await self.user.send(p, view=view)
        await view.wait()
        if view.value is None: await msg.delete(); await self.user.send("Timed out."); await self.cancel(); return False
        await msg.delete(); self.data['is_recurring'] = view.value
        if view.value: return await self.process_recurrence_rule(None, 'recurrence_rule')
        else: self.data['recurrence_rule'], self.data['recreation_hours'] = None, None; return True
    async def process_recurrence_rule(self, prompt, data_key):
        p = "How often should it recur? (`daily`, `weekly`, `monthly`)" + (f"\n(Current: `{self.data.get(data_key)}`)" if self.event_id and self.data.get(data_key) else "")
        await self.user.send(p)
        try:
            msg = await self._wait_for_message()
            if msg.content.lower() == 'cancel': await self.cancel(); return False
            rule = msg.content.lower()
            if rule not in ['daily', 'weekly', 'monthly']:
                await self.user.send("Invalid input."); return await self.process_recurrence_rule(prompt, data_key)
            self.data[data_key] = rule
            return await self.process_recreation_hours(None, 'recreation_hours')
        except asyncio.TimeoutError: await self.user.send("You took too long. Conversation cancelled."); await self.cancel(); return False
    async def process_recreation_hours(self, prompt, data_key):
        p = "How many hours before the event should the new embed be created? (e.g., `168` for 7 days)" + (f"\n(Current: `{self.data.get(data_key)}`)" if self.event_id and self.data.get(data_key) else "")
        await self.user.send(p)
        try:
            msg = await self._wait_for_message()
            if msg.content.lower() == 'cancel': await self.cancel(); return False
            try: self.data[data_key] = int(msg.content); return True
            except ValueError: await self.user.send("Please enter a valid number."); return await self.process_recreation_hours(prompt, data_key)
        except asyncio.TimeoutError: await self.user.send("You took too long. Conversation cancelled."); await self.cancel(); return False
    async def _ask_roles(self, prompt, data_key, question):
        view = ConfirmationView()
        msg = await self.user.send(question, view=view)
        await view.wait()
        if view.value is None: await msg.delete(); return False
        await msg.delete()
        if view.value:
            select_view = MultiRoleSelectView(f"Select roles for: {data_key}")
            m = await self.user.send("Please select roles below.", view=select_view)
            await select_view.wait(); await m.delete(); self.data[data_key] = select_view.selection
        else: self.data[data_key] = None
        return True
    async def ask_mention_roles(self, prompt, data_key):
        return await self._ask_roles(prompt, data_key, "Mention roles in the announcement?")
    async def ask_restrict_roles(self, prompt, data_key):
        return await self._ask_roles(prompt, data_key, "Restrict sign-ups to specific roles?")
    async def finish(self):
        if self.is_finished: return
        self.is_finished = True; 
        if self.user.id in self.cog.active_conversations:
            del self.cog.active_conversations[self.user.id]
        if self.event_id:
            await self.db.update_event(self.event_id, self.data)
            await self.user.send("Event updated successfully!")
            event_record = await self.db.get_event_by_id(self.event_id)
            if event_record and event_record.get('message_id'):
                try:
                    channel = self.interaction.guild.get_channel(event_record['channel_id'])
                    msg = await channel.fetch_message(event_record['message_id'])
                    await msg.edit(embed=await create_event_embed(self.bot, self.event_id, self.db))
                except (discord.NotFound, discord.Forbidden): print(f"Could not edit message for event {self.event_id}")
        else:
            event_id = await self.db.create_event(self.interaction.guild.id, self.interaction.channel.id, self.user.id, self.data)
            await self.user.send("Event created successfully! Posting it now.")
            view = PersistentEventView(self.db)
            embed = await create_event_embed(self.bot, event_id, self.db)
            content = " ".join([f"<@&{rid}>" for rid in self.data.get('mention_role_ids', [])])
            msg = await self.interaction.channel.send(content=content, embed=embed, view=view)
            await self.db.update_event_message_id(event_id, msg.id)
    async def cancel(self):
        if self.is_finished: return
        self.is_finished = True
        if self.user.id in self.cog.active_conversations:
            del self.cog.active_conversations[self.user.id]
        await self.user.send("Event creation/editing cancelled
