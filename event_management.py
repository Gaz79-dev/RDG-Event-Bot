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
    for role in ROLES:
        role_emoji = EMOJI_MAPPING.get(role, "")
        users_in_role = accepted_signups.get(role, [])
        field_value = "\n".join(users_in_role) or "No one yet"
        embed.add_field(name=f"{role_emoji} **{role}** ({len(users_in_role)})", value=field_value, inline=False)

    if tentative_users: embed.add_field(name=f"🤔 Tentative ({len(tentative_users)})", value=", ".join(tentative_users), inline=False)
    if declined_users: embed.add_field(name=f"❌ Declined ({len(declined_users)})", value=", ".join(declined_users), inline=False)
    
    return embed

# --- UI Components ---
class RoleMultiSelect(ui.RoleSelect):
    def __init__(self, placeholder: str):
        super().__init__(placeholder=placeholder, min_values=1, max_values=25)

    async def callback(self, interaction: discord.Interaction):
        self.view.selection = [role.id for role in self.values]
        await interaction.response.defer()
        self.view.stop()

class MultiRoleSelectView(ui.View):
    selection: List[int] = None
    def __init__(self, placeholder: str):
        super().__init__(timeout=180)
        self.add_item(RoleMultiSelect(placeholder=placeholder))

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

class TimezoneSelect(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="UTC (Coordinated Universal Time)", value="UTC"),
            discord.SelectOption(label="GMT (Greenwich Mean Time)", value="GMT"),
            discord.SelectOption(label="EST (Eastern Standard Time)", value="EST"),
            discord.SelectOption(label="PST (Pacific Standard Time)", value="PST"),
            discord.SelectOption(label="CET (Central European Time)", value="CET"),
            discord.SelectOption(label="AEST (Australian Eastern Standard Time)", value="Australia/Sydney"),
        ]
        super().__init__(placeholder="Choose a timezone...", min_values=1, max_values=1, options=options)
    
    async def callback(self, interaction: discord.Interaction):
        self.view.selection = self.values[0]
        await interaction.response.defer()
        self.view.stop()

class TimezoneSelectView(ui.View):
    selection: str = None
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(TimezoneSelect())

class PersistentEventView(ui.View):
    def __init__(self, db: Database):
        super().__init__(timeout=None)
        self.db = db
    # ... (button logic for accept, tentative, decline)

# --- Conversation Class ---
class Conversation:
    def __init__(self, cog: 'EventManagement', interaction: discord.Interaction, db: Database, event_id: int = None):
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
            (None, self.process_timezone, 'timezone'),
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
        view = TimezoneSelectView()
        msg = await self.user.send("Please select a timezone for the event.", view=view)
        await view.wait()
        if view.selection:
            self.data[data_key] = view.selection
            await msg.edit(content=f"Timezone set to **{view.selection}**.", view=None)
            return True
        else:
            await msg.edit(content="Timezone selection timed out. Conversation cancelled.", view=None)
            await self.cancel()
            return False

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
        msg = await self.user.send("Is this a recurring event?", view=view)
        await view.wait()
        if view.value is None: await msg.delete(); await self.user.send("Timed out."); await self.cancel(); return False
        await msg.delete(); self.data['is_recurring'] = view.value
        if view.value: return await self.process_recurrence_rule(None, 'recurrence_rule')
        else: self.data['recurrence_rule'], self.data['recreation_hours'] = None, None; return True

    async def process_recurrence_rule(self, prompt, data_key):
        p = "How often should it recur? (`daily`, `weekly`, `monthly`)"
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
        p = "How many hours before the event should the new embed be created? (e.g., `168` for 7 days)"
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
            await select_view.wait(); await m.delete(); self.data[data_key] = select_view.selection or []
        else: self.data[data_key] = []
        return True

    async def ask_mention_roles(self, prompt, data_key):
        return await self._ask_roles(prompt, data_key, "Mention roles in the announcement?")
    async def ask_restrict_roles(self, prompt, data_key):
        return await self._ask_roles(prompt, data_key, "Restrict sign-ups to specific roles?")
        
    async def finish(self):
        if self.is_finished: return
        self.is_finished = True
        if self.user.id in self.cog.active_conversations:
            del self.cog.active_conversations[self.user.id]

        if self.event_id:
            await self.db.update_event(self.event_id, self.data)
            await self.user.send("Event updated successfully!")
            # ... update existing embed ...
        else:
            event_id = None
            try:
                event_id = await self.db.create_event(self.interaction.guild.id, self.interaction.channel.id, self.user.id, self.data)
                await self.user.send(f"Event created successfully! (ID: {event_id}). Posting it in the channel now...")
                
                target_channel = self.bot.get_channel(self.interaction.channel.id)
                if not target_channel:
                    await self.user.send("Error: I could not find the original channel to post the event in.")
                    return

                view = PersistentEventView(self.db)
                embed = await create_event_embed(self.bot, event_id, self.db)
                content = " ".join([f"<@&{rid}>" for rid in self.data.get('mention_role_ids', [])])

                msg = await target_channel.send(content=content, embed=embed, view=view)
                await self.db.update_event_message_id(event_id, msg.id)

            except Exception as e:
                await self.user.send("An error occurred while posting the event.")
                traceback.print_exc()
                if event_id: await self.db.delete_event(event_id)

    async def cancel(self):
        if self.is_finished: return
        self.is_finished = True
        if self.user.id in self.cog.active_conversations:
            del self.cog.active_conversations[self.user.id]
        await self.user.send("Event creation/editing cancelled")

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
            conv = Conversation(self, interaction, self.db, event_id)
            self.active_conversations[interaction.user.id] = conv
            asyncio.create_task(conv.start())
        except discord.Forbidden:
            await interaction.followup.send("I couldn't send you a DM. Please check your privacy settings.", ephemeral=True)

    # --- Event Command Group ---
    event_group = app_commands.Group(name="event", description="Commands for creating and managing events.")

    @event_group.command(name="create", description="Create a new event via DM.")
    async def create(self, interaction: discord.Interaction):
        await self.start_conversation(interaction)

    @event_group.command(name="edit", description="Edit an existing event via DM.")
    @app_commands.describe(event_id="The ID of the event to edit.")
    async def edit(self, interaction: discord.Interaction, event_id: int):
        event = await self.db.get_event_by_id(event_id)
        if not event or event['guild_id'] != interaction.guild_id:
            await interaction.response.send_message("Event not found.", ephemeral=True)
            return
        await self.start_conversation(interaction, event_id)

    @event_group.command(name="delete", description="Delete an existing event by its ID.")
    @app_commands.describe(event_id="The ID of the event to delete.")
    async def delete(self, interaction: discord.Interaction, event_id: int):
        await interaction.response.send_message("Delete functionality placeholder.", ephemeral=True)

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

async def setup(bot: commands.Bot, db: Database):
    await bot.add_cog(EventManagement(bot, db))
    bot.add_view(PersistentEventView(db))
�
