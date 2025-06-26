import discord
from discord.ext import commands
from discord import app_commands, ui
import datetime
import traceback
import os
import pytz
from urllib.parse import urlencode

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
    
    # Format dates to Google's required format (YYYYMMDDTHHMMSSZ)
    start_time_utc = event['event_time'].astimezone(pytz.utc)
    end_time_utc = (event['end_time'] or (start_time_utc + datetime.timedelta(hours=2))).astimezone(pytz.utc)
    
    params = {
        'text': event['title'],
        'dates': f"{start_time_utc.strftime('%Y%m%dT%H%M%SZ')}/{end_time_utc.strftime('%Y%m%dT%H%M%SZ')}",
        'details': event['description'],
        'ctz': 'UTC'
    }
    return f"{base_url}&{urlencode(params)}"

# --- Helper function to generate the event embed ---
async def create_event_embed(interaction: discord.Interaction, event_id: int, db: Database) -> discord.Embed:
    event = await db.get_event_by_id(event_id)
    if not event:
        return discord.Embed(title="Error", description="Event not found.", color=discord.Color.red())

    signups = await db.get_signups_for_event(event_id)
    
    gcal_link = create_google_calendar_link(event)
    embed_description = f"{event['description']}\n\n[Add to Google Calendar]({gcal_link})"

    embed = discord.Embed(
        title=f"📅 {event['title']}",
        description=embed_description,
        color=discord.Color.blue()
    )
    
    time_str = f"**Starts:** {discord.utils.format_dt(event['event_time'], style='F')} ({discord.utils.format_dt(event['event_time'], style='R')})"
    if event['end_time']:
        time_str += f"\n**Ends:** {discord.utils.format_dt(event['end_time'], style='F')}"
    if event['timezone']:
        time_str += f"\nTimezone: {event['timezone']}"
        
    embed.add_field(name="Time", value=time_str, inline=False)
    
    creator = interaction.guild.get_member(event['creator_id']) or (await interaction.client.fetch_user(event['creator_id']))
    embed.set_footer(text=f"Event ID: {event_id} | Created by: {creator.display_name}")

    accepted_signups, tentative_users, declined_users = {}, [], []
    for r in ROLES: accepted_signups[r] = []

    for signup in signups:
        user = interaction.guild.get_member(signup['user_id']) or (await interaction.client.fetch_user(signup['user_id']))
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
    
    if event['restrict_to_role_id']:
        role = interaction.guild.get_role(event['restrict_to_role_id'])
        embed.add_field(name="🔒 Restricted Event", value=f"Sign-ups are restricted to members with the **{role.name if role else 'Unknown Role'}** role.", inline=False)

    return embed

# --- UI Components for DM Conversations ---

class RoleSelect(ui.Select):
    """Dropdown for selecting a primary role in a DM."""
    def __init__(self, db: Database, event_id: int):
        self.db = db
        self.event_id = event_id
        options = [discord.SelectOption(label=role, emoji=EMOJI_MAPPING.get(role)) for role in ROLES]
        super().__init__(placeholder="Choose your primary role...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        selected_role = self.values[0]

        # Since this is in a DM, we need to fetch the guild from the bot to check roles
        event_record = await self.db.get_event_by_id(self.event_id)
        guild = interaction.client.get_guild(event_record['guild_id'])
        member = await guild.fetch_member(interaction.user.id)

        required_role_id = await self.db.get_required_role_id(guild.id, selected_role)
        if required_role_id and required_role_id not in [r.id for r in member.roles]:
            await interaction.followup.send(f"You don't have the required Discord role to sign up as {selected_role}.", ephemeral=True)
            return

        if selected_role in SUBCLASSES:
            await interaction.followup.send("Now, select your subclass.", view=SubclassSelectView(self.db, selected_role, self.event_id), ephemeral=True)
        else:
            await self.db.update_signup_role(self.event_id, interaction.user.id, selected_role)
            await interaction.followup.send(f"You have signed up as **{selected_role}**! The event in the server has been updated.", ephemeral=True)
            # Update the original event embed
            original_channel = guild.get_channel(event_record['channel_id'])
            original_message = await original_channel.fetch_message(event_record['message_id'])
            new_embed = await create_event_embed(interaction, self.event_id, self.db)
            await original_message.edit(embed=new_embed)
        
        await interaction.message.delete()

class SubclassSelect(ui.Select):
    """Dropdown for selecting a subclass in a DM."""
    def __init__(self, db: Database, parent_role: str, event_id: int):
        self.db = db
        self.parent_role = parent_role
        self.event_id = event_id
        options = [discord.SelectOption(label=subclass, emoji=EMOJI_MAPPING.get(subclass)) for subclass in SUBCLASSES.get(parent_role, [])]
        super().__init__(placeholder=f"Choose your {parent_role} subclass...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        selected_subclass = self.values[0]

        event_record = await self.db.get_event_by_id(self.event_id)
        guild = interaction.client.get_guild(event_record['guild_id'])
        member = await guild.fetch_member(interaction.user.id)

        required_role_id = await self.db.get_required_role_id(guild.id, selected_subclass)
        if required_role_id and required_role_id not in [r.id for r in member.roles]:
            await interaction.followup.send(f"You don't have the required Discord role to sign up as {selected_subclass}.", ephemeral=True)
            return

        await self.db.update_signup_role(self.event_id, interaction.user.id, self.parent_role, selected_subclass)
        await interaction.followup.send(f"You have signed up as **{self.parent_role} ({selected_subclass})**! The event in the server has been updated.", ephemeral=True)

        original_channel = guild.get_channel(event_record['channel_id'])
        original_message = await original_channel.fetch_message(event_record['message_id'])
        new_embed = await create_event_embed(interaction, self.event_id, self.db)
        await original_message.edit(embed=new_embed)
        
        await interaction.message.delete()


class RoleSelectView(ui.View):
    def __init__(self, db: Database, event_id: int):
        super().__init__(timeout=180)
        self.add_item(RoleSelect(db, event_id))

class SubclassSelectView(ui.View):
    def __init__(self, db: Database, parent_role: str, event_id: int):
        super().__init__(timeout=180)
        self.add_item(SubclassSelect(db, parent_role, event_id))


# --- Main Persistent View for the Event Embed ---
class PersistentEventView(ui.View):
    def __init__(self, db: Database):
        super().__init__(timeout=None)
        self.db = db

    async def check_restrictions(self, interaction: discord.Interaction, event: dict) -> bool:
        if event['restrict_to_role_id']:
            role = interaction.guild.get_role(event['restrict_to_role_id'])
            if role and role not in interaction.user.roles:
                await interaction.response.send_message(f"Sorry, this event is restricted to members with the **{role.name}** role.", ephemeral=True)
                return False
        return True

    @ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="persistent_view:accept")
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        try:
            event = await self.db.get_event_by_message_id(interaction.message.id)
            if not event:
                await interaction.response.send_message("This event could not be found.", ephemeral=True)
                return
            
            if not await self.check_restrictions(interaction, event): return

            await interaction.user.send(f"To complete your signup for **{event['title']}**, please select your role below.", view=RoleSelectView(self.db, event['event_id']))
            await interaction.response.send_message("I've sent you a DM to complete your signup!", ephemeral=True)
            
            await self.db.set_rsvp(event['event_id'], interaction.user.id, RsvpStatus.ACCEPTED)
            new_embed = await create_event_embed(interaction, event['event_id'], self.db)
            await interaction.message.edit(embed=new_embed)

        except discord.Forbidden:
            await interaction.response.send_message("I couldn't send you a DM. Please check your privacy settings to allow DMs from server members.", ephemeral=True)
        except Exception as e:
            print(f"--- An error occurred in the 'Accept' button callback ---")
            traceback.print_exc()
            print("--- End of error ---")
            if not interaction.response.is_done():
                await interaction.response.send_message("An unexpected error occurred. Please check the bot's logs.", ephemeral=True)

    @ui.button(label="Tentative", style=discord.ButtonStyle.secondary, custom_id="persistent_view:tentative")
    async def tentative(self, interaction: discord.Interaction, button: ui.Button):
        event = await self.db.get_event_by_message_id(interaction.message.id)
        if not event or not await self.check_restrictions(interaction, event): return
        await self.db.set_rsvp(event['event_id'], interaction.user.id, RsvpStatus.TENTATIVE)
        await interaction.response.defer()
        new_embed = await create_event_embed(interaction, event['event_id'], self.db)
        await interaction.message.edit(embed=new_embed)

    @ui.button(label="Decline", style=discord.ButtonStyle.danger, custom_id="persistent_view:decline")
    async def decline(self, interaction: discord.Interaction, button: ui.Button):
        event = await self.db.get_event_by_message_id(interaction.message.id)
        if not event: return
        await self.db.set_rsvp(event['event_id'], interaction.user.id, RsvpStatus.DECLINED)
        await interaction.response.defer()
        new_embed = await create_event_embed(interaction, event['event_id'], self.db)
        await interaction.message.edit(embed=new_embed)

# --- Main Cog ---
class EventManagement(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        self.active_conversations = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not isinstance(message.channel, discord.DMChannel): return
        if message.author.id in self.active_conversations:
            await self.active_conversations[message.author.id].handle_response(message)

    @app_commands.command(name="create", description="Create a new event via DM.")
    async def create(self, interaction: discord.Interaction):
        if interaction.user.id in self.active_conversations:
            await interaction.response.send_message("You are already in an active event creation process. Please finish or `cancel` it first.", ephemeral=True)
            return
        
        try:
            conversation = Conversation(self, interaction, self.db)
            self.active_conversations[interaction.user.id] = conversation
            await conversation.start()
            await interaction.response.send_message("I've sent you a DM to start creating the event!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I couldn't send you a DM. Please check your privacy settings.", ephemeral=True)

    @app_commands.command(name="edit", description="Edit an existing event via DM.")
    @app_commands.describe(event_id="The ID of the event to edit.")
    async def edit(self, interaction: discord.Interaction, event_id: int):
        if interaction.user.id in self.active_conversations:
            await interaction.response.send_message("You are already in an active event creation process. Please finish or `cancel` it first.", ephemeral=True)
            return

        event = await self.db.get_event_by_id(event_id)
        if not event or event['guild_id'] != interaction.guild_id:
            await interaction.response.send_message("Event not found.", ephemeral=True)
            return
        
        manager_role_id = await self.db.get_manager_role_id(interaction.guild.id)
        is_creator = interaction.user.id == event['creator_id']
        is_manager = manager_role_id and manager_role_id in [r.id for r in interaction.user.roles]
        is_admin = interaction.user.guild_permissions.administrator

        if not (is_creator or is_manager or is_admin):
            await interaction.response.send_message("You don't have permission to edit this event.", ephemeral=True)
            return
            
        try:
            conversation = Conversation(self, interaction, self.db, event_id)
            self.active_conversations[interaction.user.id] = conversation
            await conversation.start()
            await interaction.response.send_message("I've sent you a DM to start editing the event!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("I couldn't send you a DM. Please check your privacy settings.", ephemeral=True)


async def setup(bot: commands.Bot, db: Database):
    """Sets up the cog and adds the persistent view."""
    if not hasattr(db, 'get_event_by_id'):
        async def get_event_by_id(self, event_id: int):
            async with self.pool.acquire() as connection:
                return await connection.fetchrow("SELECT * FROM events WHERE event_id = $1;", event_id)
        Database.get_event_by_id = get_event_by_id
    
    bot.add_view(PersistentEventView(db))
    await bot.add_cog(EventManagement(bot, db))


# --- The Conversation Class (nested to simplify file structure) ---
class Conversation:
    def __init__(self, cog: EventManagement, interaction: discord.Interaction, db: Database, event_id: int = None):
        self.cog = cog
        self.bot = cog.bot
        self.interaction = interaction
        self.user = interaction.user
        self.db = db
        self.event_id = event_id
        self.data = {}
        self.stage = 0
        self.prompts = [
            ("What is the title of the event?", self.process_title),
            ("What timezone should this event use? (e.g., `UTC`, `EST`, `Europe/London`).", self.process_timezone),
            ("What is the start date and time? Please use `DD-MM-YYYY HH:MM` format.", self.process_start_time),
            ("What is the end date and time? (Optional, press Enter to skip). Format: `DD-MM-YYYY HH:MM`.", self.process_end_time),
            ("Please provide a detailed description for the event.", self.process_description),
            ("Is this a recurring event? (yes/no)", self.process_is_recurring)
        ]

    async def start(self):
        if self.event_id:
            event_data = await self.db.get_event_by_id(self.event_id)
            self.data = dict(event_data) if event_data else {}
            await self.user.send(f"Now editing event: **{self.data.get('title', 'Unknown')}**.\nLet's start with the title. What should it be? (Current: `{self.data.get('title', '')}`)")
        else:
            await self.user.send("Let's create a new event! You can type `cancel` at any time to stop.")
            await self.ask_next_question()

    async def ask_next_question(self):
        if self.stage < len(self.prompts):
            prompt_text, _ = self.prompts[self.stage]
            await self.user.send(prompt_text)
        else:
            await self.finish()
            
    async def handle_response(self, message: discord.Message):
        if message.content.lower() == 'cancel':
            await self.cancel()
            return
        
        _, processor = self.prompts[self.stage]
        if await processor(message):
            self.stage += 1
            # Special handling for conditional prompts
            if self.stage == 6 and self.data.get('is_recurring') == False:
                 await self.user.send("Do you want to mention a role in the event announcement? (Type the role name or mention, or `no`)")
                 self.prompts.insert(self.stage, ("Mention role", self.process_mention_role))
            
            await self.ask_next_question()

    async def process_title(self, message): self.data['title'] = message.content; return True
    async def process_description(self, message): self.data['description'] = message.content; return True

    async def process_timezone(self, message):
        try:
            pytz.timezone(message.content)
            self.data['timezone'] = message.content
            return True
        except pytz.UnknownTimeZoneError:
            await self.user.send("That's not a valid timezone. Please try again (e.g., `UTC`, `America/New_York`)."); return False

    async def process_start_time(self, message):
        try:
            tz = pytz.timezone(self.data.get('timezone', 'UTC'))
            self.data['start_time'] = tz.localize(datetime.datetime.strptime(message.content, "%d-%m-%Y %H:%M"))
            return True
        except ValueError:
            await self.user.send("Invalid date format. Please use `DD-MM-YYYY HH:MM`."); return False

    async def process_end_time(self, message):
        if not message.content: self.data['end_time'] = None; return True
        try:
            tz = pytz.timezone(self.data.get('timezone', 'UTC'))
            self.data['end_time'] = tz.localize(datetime.datetime.strptime(message.content, "%d-%m-%Y %H:%M"))
            return True
        except ValueError:
            await self.user.send("Invalid date format. Please use `DD-MM-YYYY HH:MM`."); return False

    async def process_is_recurring(self, message):
        if message.content.lower() in ['yes', 'y']:
            self.data['is_recurring'] = True
            await self.user.send("How often should it recur? (`weekly`, `monthly`, `yearly`)")
            self.prompts.insert(self.stage + 1, ("Recurrence rule", self.process_recurrence_rule))
        else:
            self.data['is_recurring'] = False
        return True

    async def process_recurrence_rule(self, message):
        rule = message.content.lower()
        if rule in ['weekly', 'monthly', 'yearly']:
            self.data['recurrence_rule'] = rule
        else:
            await self.user.send("Invalid recurrence rule. Please enter `weekly`, `monthly`, or `yearly`."); return False
        
        await self.user.send("Do you want to mention a role in the event announcement? (Type the role name or mention, or `no`)")
        self.prompts.insert(self.stage + 1, ("Mention role", self.process_mention_role))
        return True

    async def process_mention_role(self, message):
        if message.content.lower() in ['no', 'n', 'none']: self.data['mention_role_id'] = None
        else:
            try:
                role = await commands.RoleConverter().convert(self.interaction, message.content)
                self.data['mention_role_id'] = role.id
            except commands.RoleNotFound:
                await self.user.send("I couldn't find that role. Please try again."); return False
        
        await self.user.send("Do you want to restrict sign-ups to a specific role? (Type the role name or mention, or `no`)")
        self.prompts.insert(self.stage + 1, ("Restrict role", self.process_restrict_role))
        return True

    async def process_restrict_role(self, message):
        if message.content.lower() in ['no', 'n', 'none']: self.data['restrict_to_role_id'] = None
        else:
            try:
                role = await commands.RoleConverter().convert(self.interaction, message.content)
                self.data['restrict_to_role_id'] = role.id
            except commands.RoleNotFound:
                await self.user.send("I couldn't find that role. Please try again."); return False
        return True

    async def finish(self):
        del self.cog.active_conversations[self.user.id]
        if self.event_id:
            await self.db.update_event(self.event_id, self.data)
            await self.user.send("Event updated successfully!")
            event_record = await self.db.get_event_by_id(self.event_id)
            original_message = await self.interaction.guild.get_channel(event_record['channel_id']).fetch_message(event_record['message_id'])
            new_embed = await create_event_embed(self.interaction, self.event_id, self.db)
            await original_message.edit(embed=new_embed)
        else:
            event_id = await self.db.create_event(self.interaction.guild.id, self.interaction.channel.id, self.user.id, self.data)
            await self.user.send("Event created successfully! Posting it now.")
            view = PersistentEventView(self.db)
            embed = await create_event_embed(self.interaction, event_id, self.db)
            
            content = ""
            if self.data.get('mention_role_id'):
                role = self.interaction.guild.get_role(self.data['mention_role_id'])
                if role: content = role.mention

            msg = await self.interaction.channel.send(content=content, embed=embed, view=view)
            await self.db.update_event_message_id(event_id, msg.id)

    async def cancel(self):
        del self.cog.active_conversations[self.user.id]
        await self.user.send("Event creation/editing cancelled.")
