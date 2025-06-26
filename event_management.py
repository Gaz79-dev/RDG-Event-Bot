import discord
from discord.ext import commands
from discord import app_commands, ui
import datetime
import traceback
import os
import pytz
from urllib.parse import urlencode
import asyncio

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

# --- Conversation and UI Components ---
class RoleMultiSelect(ui.RoleSelect):
    def __init__(self, placeholder: str):
        super().__init__(placeholder=placeholder, min_values=0, max_values=25)

    async def callback(self, interaction: discord.Interaction):
        self.view.selection = [role.id for role in self.values]
        await interaction.response.send_message(f"Selected {len(self.values)} role(s).", ephemeral=True)
        self.view.stop()

class RoleMultiSelectView(ui.View):
    def __init__(self, placeholder: str):
        super().__init__(timeout=180)
        self.selection = None
        self.add_item(RoleMultiSelect(placeholder))

class ConfirmationView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.value = None

    @ui.button(label="Yes", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        self.value = True
        self.stop()
        await interaction.response.defer()

    @ui.button(label="No/Skip", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        self.value = False
        self.stop()
        await interaction.response.defer()

# ... (Previous RoleSelect, SubclassSelect, etc. for RSVP flow remain the same)

class EventManagement(commands.Cog):
    # ... (listener, create, and edit commands are the same)

async def setup(bot: commands.Bot, db: Database):
    # ... (setup remains the same)

# --- The Conversation Class (nested to simplify file structure) ---
class Conversation:
    # ... (__init__ is the same)

    async def start(self):
        # ... (start logic is the same)
        
    # --- New Interactive Prompts ---
    async def ask_mention_roles(self):
        view = ConfirmationView()
        msg = await self.user.send("Do you want to mention any roles in the event announcement?", view=view)
        await view.wait()
        await msg.delete()
        if view.value:
            select_view = RoleMultiSelectView("Select roles to mention...")
            await self.user.send("Please select the roles to mention below.", view=select_view)
            await select_view.wait()
            self.data['mention_role_ids'] = select_view.selection
        else:
            self.data['mention_role_ids'] = None
        return True
        
    async def ask_restrict_roles(self):
        view = ConfirmationView()
        msg = await self.user.send("Do you want to restrict sign-ups to specific roles?", view=view)
        await view.wait()
        await msg.delete()
        if view.value:
            select_view = RoleMultiSelectView("Select roles to restrict sign-ups to...")
            await self.user.send("Please select the roles to restrict sign-ups to below.", view=select_view)
            await select_view.wait()
            self.data['restrict_to_role_ids'] = select_view.selection
        else:
            self.data['restrict_to_role_ids'] = None
        return True

    # --- Refactored Conversation Flow ---
    async def run_conversation(self):
        steps = [
            ("What is the title of the event?", self.process_title, True),
            ("What timezone should this event use? (e.g., `UTC`, `EST`, `Europe/London`).", self.process_timezone, True),
            ("What is the start date and time? Please use `DD-MM-YYYY HH:MM` format.", self.process_start_time, True),
            ("What is the end date and time? (Optional, press Enter to skip). Format: `DD-MM-YYYY HH:MM`.", self.process_end_time, True),
            ("Please provide a detailed description for the event.", self.process_description, True),
            (None, self.ask_mention_roles, False),
            (None, self.ask_restrict_roles, False),
        ]
        
        for prompt, processor, is_text_prompt in steps:
            if self.event_id and prompt and self.data.get(processor.__name__.replace('process_', '')):
                # Simple way to show current value when editing, can be enhanced
                prompt += f"\n(Current: `{self.data.get(processor.__name__.replace('process_', ''))}`)"

            if is_text_prompt:
                await self.user.send(prompt)
                try:
                    msg = await self.bot.wait_for('message', check=lambda m: m.author == self.user and isinstance(m.channel, discord.DMChannel), timeout=300.0)
                    if msg.content.lower() == 'cancel': await self.cancel(); return
                    if not await processor(msg):
                        # Processor failed validation, end conversation
                        return
                except asyncio.TimeoutError:
                    await self.user.send("You took too long to respond. Conversation cancelled."); await self.cancel(); return
            else: # UI based prompt
                if not await processor():
                    # User cancelled or other issue
                    return
        await self.finish()

    # ... (other processor methods remain largely the same, but no longer need to manage flow)

    async def finish(self):
        del self.cog.active_conversations[self.user.id]
        guild = self.interaction.guild
        if self.event_id:
            await self.db.update_event(self.event_id, self.data)
            await self.user.send("Event updated successfully!")
            # ... (rest of finish logic is the same)
        else:
            event_id = await self.db.create_event(guild.id, self.interaction.channel.id, self.user.id, self.data)
            await self.user.send("Event created successfully! Posting it now.")
            # ... (rest of finish logic is the same)
            content = ""
            if self.data.get('mention_role_ids'):
                mentions = [f"<@&{role_id}>" for role_id in self.data['mention_role_ids']]
                content = " ".join(mentions)

            # ... (send message with new content)

