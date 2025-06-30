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
    accepted_signups, tentative_users, declined_users = defaultdict(list), [], []
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

# --- UI Classes ---
class RoleSelect(ui.Select):
    def __init__(self, db: Database, event_id: int):
        self.db, self.event_id = db, event_id
        super().__init__(placeholder="1. Choose your primary role...", options=[discord.SelectOption(label=r, emoji=EMOJI_MAPPING.get(r, "❔")) for r in ROLES])
    async def callback(self, i: discord.Interaction):
        self.view.role = self.values[0]
        subclass_select = self.view.subclass_select
        if subclass_options := SUBCLASSES.get(self.view.role, []):
            subclass_select.disabled, subclass_select.placeholder, subclass_select.options = False, "2. Choose your subclass...", [discord.SelectOption(label=s, emoji=EMOJI_MAPPING.get(s, "❔")) for s in subclass_options]
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
        self.add_item(RoleSelect(db, event_id)), self.add_item(self.subclass_select)
    async def on_timeout(self):
        if self.role is None:
            await self.db.update_signup_role(self.event_id, self.user.id, "Unassigned", None)
            await self.update_original_embed()
            try: await self.user.send("Your role selection timed out. You are 'Unassigned'.")
            except discord.Forbidden: pass
    async def update_original_embed(self):
        if not (event := await self.db.get_event_by_id(self.event_id)): return
        try:
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

class ConfirmationView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.value = None
    @ui.button(label="Yes", style=discord.ButtonStyle.green)
    async def confirm(self, i: discord.Interaction, button: ui.Button): self.value, self.stop() = True, await i.response.defer()
    @ui.button(label="No/Skip", style=discord.ButtonStyle.red)
    async def cancel(self, i: discord.Interaction, button: ui.Button): self.value, self.stop() = False, await i.response.defer()

class TimezoneSelect(ui.Select):
    def __init__(self):
        super().__init__(placeholder="Choose a timezone...", options=[discord.SelectOption(label=tz, value=tz) for tz in ["Europe/London", "UTC", "GMT", "EST", "PST", "CET", "Australia/Sydney"]])
    async def callback(self, i: discord.Interaction): self.view.selection = self.values[0]; self.view.stop(); await i.response.defer()

class TimezoneSelectView(ui.View):
    def __init__(self):
        super().__init__(timeout=180); self.selection: str = None; self.add_item(TimezoneSelect())

# --- FIX: Replaced incorrect MultiRoleSelectView with the correct, two-class pattern ---
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

class Conversation:
    def __init__(self, cog: 'EventManagement', interaction: discord.Interaction, db: Database, event_id: int = None):
        self.cog, self.bot, self.interaction, self.user, self.db, self.event_id = cog, cog.bot, interaction, interaction.user, db, event_id
        self.data, self.is_finished = {}, False

    async def start(self):
        try:
            if self.event_id and (event_data := await self.db.get_event_by_id(self.event_id)): self.data = dict(event_data)
            await self.user.send(f"Starting event {'editing' if self.event_id else 'creation'}. Type `cancel` at any time to stop.")
            await self.run_conversation()
        except Exception as e: print(f"Error starting conversation: {e}"); traceback.print_exc(); await self.cancel()
    
    async def run_conversation(self):
        steps = [
            ("What is the title of the event?", self.process_text, 'title'),
            (None, self.process_timezone, 'timezone'),
            ("What is the start date and time? Please use `DD-MM-YYYY HH:MM` format.", self.process_start_time, 'start_time'),
            ("What is the end date and time? Format: `DD-MM-YYYY HH:MM`.", self.process_end_time, 'end_time'),
            ("Please provide a detailed description for the event.", self.process_text, 'description'),
            (None, self.ask_is_recurring, 'is_recurring'),
            (None, self.ask_mention_roles, 'mention_role_ids'),
            (None, self.ask_restrict_roles, 'restrict_to_role_ids'),
        ]
        for prompt, processor, data_key in steps:
            if self.is_finished: break
            if not await processor(prompt, data_key): await self.cancel(); return
        await self.finish()

    async def _wait_for_message(self):
        return await self.bot.wait_for('message', check=lambda m: m.author == self.user and isinstance(m.channel, discord.DMChannel), timeout=300.0)

    async def process_text(self, prompt, data_key):
        if self.event_id and self.data.get(data_key): prompt += f"\n(Current: `{self.data.get(data_key)}`)"
        await self.user.send(prompt)
        try:
            msg = await self._wait_for_message()
            if msg.content.lower() == 'cancel': return False
            self.data[data_key] = msg.content; return True
        except asyncio.TimeoutError: await self.user.send("Conversation timed out."); return False

    async def process_timezone(self, prompt, data_key):
        view, prompt_msg = TimezoneSelectView(), "Please select a timezone for the event."
        if self.event_id and self.data.get(data_key): prompt_msg += f"\n(Current: `{self.data.get(data_key)}`)"
        msg = await self.user.send(prompt_msg, view=view)
        await view.wait()
        if view.selection: self.data[data_key] = view.selection; await msg.edit(content=f"Timezone set to **{view.selection}**.", view=None); return True
        await msg.edit(content="Timezone selection timed out.", view=None); return False

    async def process_start_time(self, prompt, data_key):
        while True:
            val = self.data.get(data_key).strftime('%d-%m-%Y %H:%M') if self.data.get(data_key) else ''
            p = prompt + (f"\n(Current: `{val}`)" if self.event_id and val else "")
            await self.user.send(p)
            try:
                msg = await self._wait_for_message()
                if msg.content.lower() == 'cancel': return False
                try: self.data[data_key] = pytz.timezone(self.data.get('timezone', 'UTC')).localize(datetime.datetime.strptime(msg.content, "%d-%m-%Y %H:%M")); return True
                except ValueError: await self.user.send("Invalid date format. Use `DD-MM-YYYY HH:MM`.")
            except asyncio.TimeoutError: await self.user.send("Conversation timed out."); return False

    async def process_end_time(self, prompt, data_key):
        while True:
            val = self.data.get(data_key).strftime('%d-%m-%Y %H:%M') if self.data.get(data_key) else ''
            p = prompt + (f"\n(Current: `{val}`)" if self.event_id and val else "")
            await self.user.send(p)
            try:
                msg = await self._wait_for_message()
                if msg.content.lower() == 'cancel': return False
                try:
                    self.data[data_key] = pytz.timezone(self.data.get('timezone', 'UTC')).localize(datetime.datetime.strptime(msg.content, "%d-%m-%Y %H:%M"))
                    return True # Success
                except ValueError: await self.user.send("Invalid date format. Please use `DD-MM-YYYY HH:MM`.")
            except asyncio.TimeoutError: await self.user.send("Conversation timed out."); return False

    async def ask_is_recurring(self, prompt, data_key):
        view, msg = ConfirmationView(), await self.user.send("Is this a recurring event?", view=view)
        await view.wait()
        if view.value is None: await msg.delete(); await self.user.send("Timed out."); return False
        await msg.delete(); self.data['is_recurring'] = view.value
        if view.value: return await self.process_recurrence_rule(None, 'recurrence_rule')
        self.data['recurrence_rule'], self.data['recreation_hours'] = None, None; return True

    async def process_recurrence_rule(self, prompt, data_key):
        p = "How often should it recur? (`daily`, `weekly`, `monthly`)"
        await self.user.send(p)
        try:
            msg = await self._wait_for_message()
            if msg.content.lower() == 'cancel': return False
            rule = msg.content.lower()
            if rule not in ['daily', 'weekly', 'monthly']: await self.user.send("Invalid input."); return await self.process_recurrence_rule(prompt, data_key)
            self.data[data_key] = rule; return await self.process_recreation_hours(None, 'recreation_hours')
        except asyncio.TimeoutError: await self.user.send("Conversation timed out."); return False

    async def process_recreation_hours(self, prompt, data_key):
        p = "How many hours before the event should the new embed be created? (e.g., `168` for 7 days)"
        await self.user.send(p)
        try:
            msg = await self._wait_for_message()
            if msg.content.lower() == 'cancel': return False
            try: self.data[data_key] = int(msg.content); return True
            except ValueError: await self.user.send("Please enter a valid number."); return await self.process_recreation_hours(prompt, data_key)
        except asyncio.TimeoutError: await self.user.send("Conversation timed out."); return False

    async def _ask_roles(self, prompt, data_key, question):
        view, msg = ConfirmationView(), await self.user.send(question, view=view)
        await view.wait()
        if view.value is None: await msg.delete(); return False
        await msg.delete()
        if view.value:
            select_view, m = MultiRoleSelectView(f"Select roles for: {data_key}"), await self.user.send("Please select roles below.", view=select_view)
            await select_view.wait(); await m.delete(); self.data[data_key] = select_view.selection or []
        else: self.data[data_key] = []
        return True

    async def ask_mention_roles(self, p, dk): return await self._ask_roles(p, dk, "Mention roles in the announcement?")
    async def ask_restrict_roles(self, p, dk): return await self._ask_roles(p, dk, "Restrict sign-ups to specific roles?")
        
    async def finish(self):
        if self.is_finished: return
        self.is_finished = True
        if self.user.id in self.cog.active_conversations: del self.cog.active_conversations[self.user.id]
        event_id = self.event_id
        try:
            if self.event_id:
                await self.db.update_event(self.event_id, self.data)
                await self.user.send("Event updated successfully!")
            else:
                event_id = await self.db.create_event(self.interaction.guild.id, self.interaction.channel.id, self.user.id, self.data)
                await self.user.send(f"Event created successfully! (ID: {event_id}). Posting it now...")
            
            target_channel = self.bot.get_channel(self.data.get('channel_id') or self.interaction.channel.id)
            if not target_channel: return await self.user.send("Error: Could not find channel to post event.")
            
            view = PersistentEventView(self.db)
            embed = await create_event_embed(self.bot, event_id, self.db)
            content = " ".join([f"<@&{rid}>" for rid in self.data.get('mention_role_ids', [])])
            msg = await target_channel.send(content=content, embed=embed, view=view)
            await self.db.update_event_message_id(event_id, msg.id)
        except Exception as e: print(f"Error finishing conversation: {e}"); traceback.print_exc()

    async def cancel(self):
        if self.is_finished: return
        self.is_finished = True
        if self.user.id in self.cog.active_conversations: del self.cog.active_conversations[self.user.id]
        await self.user.send("Event creation/editing cancelled")

class EventManagement(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        self.active_conversations = {}

    event_group = app_commands.Group(name="event", description="Commands for creating and managing events.")

    @event_group.command(name="create", description="Create a new event via DM.")
    async def create(self, interaction: discord.Interaction):
        await self.start_conversation(interaction)

    @event_group.command(name="edit", description="Edit an existing event via DM.")
    @app_commands.describe(event_id="The ID of the event to edit.")
    async def edit(self, interaction: discord.Interaction, event_id: int):
        if not (event := await self.db.get_event_by_id(event_id)) or event['guild_id'] != interaction.guild_id:
            return await interaction.response.send_message("Event not found.", ephemeral=True)
        await self.start_conversation(interaction, event_id)

    @event_group.command(name="delete", description="Delete an existing event by its ID.")
    @app_commands.describe(event_id="The ID of the event to delete.")
    async def delete(self, interaction: discord.Interaction, event_id: int):
        await interaction.response.send_message("Delete functionality placeholder.", ephemeral=True)

    async def start_conversation(self, interaction: discord.Interaction, event_id: int = None):
        if interaction.user.id in self.active_conversations:
            return await interaction.response.send_message("You are already creating an event.", ephemeral=True)
        try:
            await interaction.response.send_message("I've sent you a DM to start the process!", ephemeral=True)
            conv = Conversation(self, interaction, self.db, event_id)
            self.active_conversations[interaction.user.id] = conv
            asyncio.create_task(conv.start())
        except discord.Forbidden:
            await interaction.followup.send("I couldn't send you a DM. Please check your privacy settings.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(EventManagement(bot, bot.db))
    bot.add_view(PersistentEventView(bot.db))
    
