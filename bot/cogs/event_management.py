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

# Use an absolute import from the 'bot' package root for robustness
from bot.utils.database import Database, RsvpStatus, ROLES, SUBCLASSES

# --- Constants & Helpers ---
EMOJI_MAPPING = {
    "Commander": os.getenv("EMOJI_COMMANDER", "⭐"), "Infantry": os.getenv("EMOJI_INFANTRY", "💂"),
    "Armour": os.getenv("EMOJI_ARMOUR", "🛡️"), "Recon": os.getenv("EMOJI_RECON", "👁️"),
    "Anti-Tank": os.getenv("EMOJI_ANTI_TANK", "🚀"), "Assault": os.getenv("EMOJI_ASSAULT", "💥"),
    "Automatic Rifleman": os.getenv("EMOJI_AUTOMATIC_RIFLEMAN", "🔥"), "Engineer": os.getenv("EMOJI_ENGINEER", "🛠️"),
    "Machine Gunner": os.getenv("EMOJI_MACHINE_GUNNER", "💣"), "Medic": os.getenv("EMOJI_MEDIC", "➕"),
    "Officer": os.getenv("EMOJI_OFFICER", "🫡"), "Rifleman": os.getenv("EMOJI_RIFLEMAN", "👤"),
    "Support": os.getenv("EMOJI_SUPPORT", "🔧"), "Tank Commander": os.getenv("EMOJI_TANK_COMMANDER", "🧑‍✈️"),
    "Crewman": os.getenv("EMOJI_CREWMAN", "👨‍🔧"), "Spotter": os.getenv("EMOJI_SPOTTER", "👀"),
    "Sniper": os.getenv("EMOJI_SNIPER", "🎯"), "Unassigned": "❔"
}

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
            if squad_roles:
                if squad_roles.get('squad_arty_role_id') in user_role_ids: specialty = " (Arty)"
                elif squad_roles.get('squad_armour_role_id') in user_role_ids: specialty = " (Armour)"
                elif squad_roles.get('squad_attack_role_id') in user_role_ids and squad_roles.get('squad_defence_role_id') in user_role_ids: specialty = " (Flex)"
                elif squad_roles.get('squad_attack_role_id') in user_role_ids: specialty = " (Attack)"
                elif squad_roles.get('squad_defence_role_id') in user_role_ids: specialty = " (Defence)"
            role, subclass = signup['role_name'] or "Unassigned", signup['subclass_name']
            signup_text = f"**{member.display_name}**"
            if subclass: signup_text += f" ({EMOJI_MAPPING.get(subclass, '❔')})"
            signup_text += specialty
            accepted_signups[role].append(signup_text)
        elif signup['rsvp_status'] == RsvpStatus.TENTATIVE: tentative_users.append(member.display_name)
        elif signup['rsvp_status'] == RsvpStatus.DECLINED: declined_users.append(member.display_name)

    total_accepted = sum(len(v) for v in accepted_signups.values())
    embed.add_field(name=f"✅ Accepted ({total_accepted})", value="\u200b", inline=False)
    
    for role in ROLES + ["Unassigned"]:
        if role == "Unassigned" and not accepted_signups.get("Unassigned"): continue
        users_in_role = accepted_signups.get(role, [])
        embed.add_field(name=f"{EMOJI_MAPPING.get(role, '')} **{role}** ({len(users_in_role)})", value="\n".join(users_in_role) or "No one yet", inline=False)

    if tentative_users: embed.add_field(name=f"🤔 Tentative ({len(tentative_users)})", value=", ".join(tentative_users), inline=False)
    if declined_users: embed.add_field(name=f"❌ Declined ({len(declined_users)})", value=", ".join(declined_users), inline=False)
    
    creator_name = "Unknown User"
    if creator_id := event.get('creator_id'):
        try:
            creator = guild.get_member(creator_id) or await guild.fetch_member(creator_id)
            creator_name = creator.display_name if creator else (await bot.fetch_user(creator_id)).name
        except discord.NotFound: pass
    embed.set_footer(text=f"Event ID: {event_id} | Created by: {creator_name}")
    return embed

# --- UI Classes (Must be defined before setup function) ---
class RoleSelect(ui.Select):
    def __init__(self, db: Database, event_id: int):
        self.db = db
        self.event_id = event_id
        super().__init__(placeholder="1. Choose your primary role...", options=[discord.SelectOption(label=r, emoji=EMOJI_MAPPING.get(r, "❔")) for r in ROLES])
    async def callback(self, i: discord.Interaction):
        self.view.role = self.values[0]
        subclass_select = self.view.subclass_select
        if subclass_options := SUBCLASSES.get(self.view.role, []):
            subclass_select.disabled = False
            subclass_select.placeholder, subclass_select.options = "2. Choose your subclass...", [discord.SelectOption(label=s, emoji=EMOJI_MAPPING.get(s, "❔")) for s in subclass_options]
        else:
            await self.db.update_signup_role(self.event_id, i.user.id, self.view.role, None)
            for item in self.view.children: item.disabled = True
            await i.response.edit_message(content=f"Your role is confirmed as **{self.view.role}**!", view=self.view)
            self.view.stop()
            asyncio.create_task(self.view.update_original_embed())
            return
        await i.response.edit_message(view=self.view)

class SubclassSelect(ui.Select):
    def __init__(self, db: Database, event_id: int):
        self.db, self.event_id = db, event_id
        super().__init__(placeholder="Select a primary role first...", disabled=True, options=[discord.SelectOption(label="placeholder")])
    async def callback(self, i: discord.Interaction):
        subclass = self.values[0]
        await self.db.update_signup_role(self.event_id, i.user.id, self.view.role, subclass)
        for item in self.view.children: item.disabled = True
        await i.response.edit_message(content=f"Role confirmed: **{self.view.role} ({subclass})**!", view=self.view)
        self.view.stop()
        asyncio.create_task(self.view.update_original_embed())

class RoleSelectionView(ui.View):
    def __init__(self, bot: commands.Bot, db: Database, event_id: int, message_id: int, user: discord.User):
        super().__init__(timeout=300)
        self.bot, self.db, self.event_id, self.message_id, self.user, self.role = bot, db, event_id, message_id, user, None
        self.subclass_select = SubclassSelect(db, event_id)
        self.add_item(RoleSelect(db, event_id))
        self.add_item(self.subclass_select)
    async def on_timeout(self):
        if self.role is None:
            await self.db.update_signup_role(self.event_id, self.user.id, "Unassigned", None)
            await self.update_original_embed()
            try: await self.user.send("Your role selection timed out. You are 'Unassigned'.")
            except discord.Forbidden: pass
    async def update_original_embed(self):
        if not (event := await self.db.get_event_by_id(self.event_id)): return
        try:
            # --- FIX: The line below was incomplete and is now corrected ---
            channel = self.bot.get_channel(event['channel_id']) or await self.bot.fetch_channel(event['channel_id'])
            message = await channel.fetch_message(self.message_id)
            await message.edit(embed=await create_event_embed(self.bot, self.event_id, self.db))
        except (discord.NotFound, discord.Forbidden): pass

class PersistentEventView(ui.View):
    def __init__(self, db: Database):
        super().__init__(timeout=None)
        self.db = db
    async def update_embed(self, i: discord.Interaction, event_id: int):
        try: await i.message.edit(embed=await create_event_embed(i.client, event_id, self.db))
        except Exception as e: print(f"Error updating embed: {e}")
    @ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="persistent_view:accept")
    async def accept(self, i: discord.Interaction, button: ui.Button):
        await i.response.defer(ephemeral=True)
        if not (event := await self.db.get_event_by_message_id(i.message.id)): return await i.followup.send("Event not found.", ephemeral=True)
        await self.db.set_rsvp(event['event_id'], i.user.id, RsvpStatus.ACCEPTED)
        try:
            await i.user.send(f"You accepted **{event['title']}**. Select your role:", view=RoleSelectionView(i.client, self.db, event['event_id'], i.message.id, i.user))
            await i.followup.send("Check your DMs to select your role!", ephemeral=True)
        except discord.Forbidden:
            await self.db.update_signup_role(event['event_id'], i.user.id, "Unassigned", None)
            await i.followup.send("Accepted, but I couldn't DM you. Role set to 'Unassigned'.", ephemeral=True)
        await self.update_embed(i, event['event_id'])
    @ui.button(label="Tentative", style=discord.ButtonStyle.secondary, custom_id="persistent_view:tentative")
    async def tentative(self, i: discord.Interaction, button: ui.Button):
        await i.response.defer()
        if event := await self.db.get_event_by_message_id(i.message.id):
            await self.db.set_rsvp(event['event_id'], i.user.id, RsvpStatus.TENTATIVE)
            await self.db.update_signup_role(event['event_id'], i.user.id, None, None)
            await self.update_embed(i, event['event_id'])
    @ui.button(label="Decline", style=discord.ButtonStyle.danger, custom_id="persistent_view:decline")
    async def decline(self, i: discord.Interaction, button: ui.Button):
        await i.response.defer()
        if event := await self.db.get_event_by_message_id(i.message.id):
            await self.db.set_rsvp(event['event_id'], i.user.id, RsvpStatus.DECLINED)
            await self.db.update_signup_role(event['event_id'], i.user.id, None, None)
            await self.update_embed(i, event['event_id'])

class EventCreationModal(ui.Modal, title='Create a New Event'):
    def __init__(self, bot: commands.Bot, db: Database, channel: discord.TextChannel):
        super().__init__()
        self.bot, self.db, self.target_channel = bot, db, channel
    event_title = ui.TextInput(label='Event Title', placeholder='e.g., Operation Overlord', required=True)
    event_description = ui.TextInput(label='Description', style=discord.TextStyle.long, placeholder='Details about the event...', required=False)
    event_timezone = ui.TextInput(label='Timezone', placeholder='e.g., Europe/London, US/Eastern', required=True, default='UTC')
    start_datetime = ui.TextInput(label='Start Date & Time (DD-MM-YYYY HH:MM)', placeholder='e.g., 25-12-2024 19:30', required=True)
    end_time = ui.TextInput(label='End Time (HH:MM) (Optional)', placeholder='e.g., 21:00', required=False)
    async def on_submit(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True, thinking=True)
        data, errors, tz = {}, [], None
        try:
            tz = pytz.timezone(self.event_timezone.value)
            data['timezone'] = str(tz)
        except pytz.UnknownTimeZoneError: errors.append(f"Invalid Timezone: `{self.event_timezone.value}`.")
        if tz:
            try: data['start_time'] = tz.localize(datetime.datetime.strptime(self.start_datetime.value, "%d-%m-%Y %H:%M"))
            except ValueError: errors.append(f"Invalid Start Date/Time: `{self.start_datetime.value}`.")
        if self.end_time.value:
            try:
                if start_dt := data.get('start_time'):
                    end_t = datetime.datetime.strptime(self.end_time.value, "%H:%M").time()
                    end_dt = start_dt.replace(hour=end_t.hour, minute=end_t.minute, second=0, microsecond=0)
                    if end_dt <= start_dt: end_dt += datetime.timedelta(days=1)
                    data['end_time'] = end_dt
            except (ValueError, KeyError): errors.append(f"Invalid End Time: `{self.end_time.value}`.")
        if errors: return await i.followup.send("Please correct errors:\n- " + "\n- ".join(errors), ephemeral=True)
        
        data.update({ 'title': self.event_title.value, 'description': self.event_description.value or "No description.", 'is_recurring': False, 'mention_role_ids': [], 'restrict_to_role_ids': []})
        try:
            event_id = await self.db.create_event(i.guild.id, self.target_channel.id, i.user.id, data)
            msg = await self.target_channel.send(embed=await create_event_embed(self.bot, event_id, self.db), view=PersistentEventView(self.db))
            await self.db.update_event_message_id(event_id, msg.id)
            await i.followup.send(f"✅ Event '{data['title']}' created in {self.target_channel.mention}!", ephemeral=True)
        except Exception as e:
            print(f"Error on modal submit: {e}"), traceback.print_exc()
            await i.followup.send("An unexpected error occurred.", ephemeral=True)
    async def on_error(self, i: discord.Interaction, error: Exception):
        traceback.print_exc()
        await i.followup.send('Oops! Something went wrong.', ephemeral=True)

# --- Command Definition (Module Level) ---
event_group = app_commands.Group(name="event", description="Commands for creating and managing events.")

@event_group.command(name="create", description="Create a new event.")
@app_commands.describe(channel="The channel where the event announcement will be posted.")
async def create_command(interaction: discord.Interaction, channel: discord.TextChannel):
    """Opens a form to create a new event."""
    bot = interaction.client
    event_cog = bot.get_cog("EventManagement")
    if not event_cog:
        return await interaction.response.send_message("Event cog is not loaded.", ephemeral=True)
    modal = EventCreationModal(bot, event_cog.db, channel)
    await interaction.response.send_modal(modal)

# --- Cog Definition (For State Management) ---
class EventManagement(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db

# --- Setup Function (Called by bot to load the extension) ---
async def setup(bot: commands.Bot):
    db = bot.web_app.state.db
    # Add the cog for state management
    await bot.add_cog(EventManagement(bot, db))
    # Explicitly add the command group to the bot's tree
    bot.tree.add_command(event_group)
    # Add the persistent view
    bot.add_view(PersistentEventView(db))
