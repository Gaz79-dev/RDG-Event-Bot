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
import uuid

# Use relative import to go up one level to the 'bot' package root
from ..utils.database import Database, RsvpStatus, ROLES, SUBCLASSES, RESTRICTED_ROLES

# --- Constants & Helpers ---
EMOJI_MAPPING = {
    "Commander": os.getenv("EMOJI_COMMANDER", "⭐"),
    "Infantry": os.getenv("EMOJI_INFANTRY", "💂"),
    "Armour": os.getenv("EMOJI_ARMOUR", "🛡️"),
    "Recon": os.getenv("EMOJI_RECON", "👁️"),
    "Pathfinders": os.getenv("EMOJI_PATHFINDERS", "🧭"),
    "Artillery": os.getenv("EMOJI_ARTILLERY", "💣"),
    "Anti-Tank": os.getenv("EMOJI_ANTI_TANK", "🚀"),
    "Assault": os.getenv("EMOJI_ASSAULT", "💥"),
    "Automatic Rifleman": os.getenv("EMOJI_AUTOMATIC_RIFLEMAN", "🔥"),
    "Engineer": os.getenv("EMOJI_ENGINEER", "🛠️"),
    "Machine Gunner": os.getenv("EMOJI_MACHINE_GUNNER", "💥"),
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

CURATED_TIMEZONES = {
    "USA / Canada": [
        "US/Pacific", "US/Mountain", "US/Central", "US/Eastern",
        "Canada/Atlantic", "US/Alaska", "US/Hawaii"
    ],
    "UK / Europe": [
        "Europe/London", "Europe/Paris", "Europe/Berlin", 
        "Europe/Helsinki", "Europe/Moscow"
    ],
    "Other": ["UTC"]
}

async def create_event_embed(bot: commands.Bot, event_id: int, db: Database) -> discord.Embed:
    event = await db.get_event_by_id(event_id)
    if not event: return discord.Embed(title="Error", description="Event not found.", color=discord.Color.red())
    
    guild = bot.get_guild(event['guild_id'])
    if not guild: return discord.Embed(title="Error", description="Could not find the server for this event.", color=discord.Color.red())
    
    signups = await db.get_signups_for_event(event_id)
    
    specialty_roles = {
        "arty": os.getenv("ROLE_ID_ARTY"), "armour": os.getenv("ROLE_ID_ARMOUR"),
        "attack": os.getenv("ROLE_ID_ATTACK"), "defence": os.getenv("ROLE_ID_DEFENCE"),
    }
    specialty_roles = {k: int(v) for k, v in specialty_roles.items() if v and v.isdigit()}

    description = event.get('description', '')
    if restricted_ids := event.get('restrict_to_role_ids'):
        role_mentions = []
        for role_id in restricted_ids:
            role = guild.get_role(role_id)
            if role:
                role_mentions.append(role.mention)
        
        if role_mentions:
            roles_text = ", ".join(role_mentions)
            restriction_notice = (
                f"**This is a restricted sign-up event.**\n"
                f"Only members of the following role(s) are permitted to sign-up: {roles_text}\n\n---\n\n"
            )
            description = restriction_notice + description

    embed = discord.Embed(title=f"📅 {event['title']}", description=description, color=discord.Color.blue())
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
            attack_role = specialty_roles.get('attack')
            defence_role = specialty_roles.get('defence')

            if specialty_roles.get('arty') in user_role_ids: specialty = " (Arty)"
            elif specialty_roles.get('armour') in user_role_ids: specialty = " (Armour)"
            elif attack_role and defence_role and attack_role in user_role_ids and defence_role in user_role_ids: specialty = " (Flex)"
            elif attack_role in user_role_ids: specialty = " (Attack)"
            elif defence_role in user_role_ids: specialty = " (Defence)"
            
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
    def __init__(self, db: Database, event_id: int, available_roles: List[str]):
        self.db, self.event_id = db, event_id
        options = [discord.SelectOption(label=r, emoji=EMOJI_MAPPING.get(r, "❔")) for r in available_roles]
        if not options:
            options.append(discord.SelectOption(label="No roles available for you", value="unassigned"))

        super().__init__(placeholder="1. Choose your primary role...", options=options)
    
    async def callback(self, i: discord.Interaction):
        selected_role = self.values[0]
        if selected_role == "unassigned":
            await self.db.update_signup_role(self.event_id, i.user.id, "Unassigned", None)
            await i.response.edit_message(content=f"Your role is set to **Unassigned** as no other roles were available.", view=None)
            asyncio.create_task(self.view.update_original_embed())
            self.view.stop()
            return
            
        self.view.role = selected_role
        subclass_select = self.view.subclass_select
        
        all_subclasses = SUBCLASSES.get(self.view.role, [])
        if not all_subclasses:
            await self.db.update_signup_role(self.event_id, i.user.id, self.view.role, None)
            for item in self.view.children: item.disabled = True
            await i.response.edit_message(content=f"Your role is confirmed as **{self.view.role}**!", view=self.view)
            self.view.stop()
            asyncio.create_task(self.view.update_original_embed())
            return

        event = await self.db.get_event_by_id(self.event_id)
        if not event:
            return await i.response.edit_message(content="Error: The event could not be found.", view=None)

        guild = self.view.bot.get_guild(event['guild_id'])
        if not guild:
            return await i.response.edit_message(content="Error: Bot is not in the event's server.", view=None)
        
        member = guild.get_member(i.user.id) or await guild.fetch_member(i.user.id)
        if not member:
            return await i.response.edit_message(content="Error: Could not find you in the event's server.", view=None)
        
        user_role_ids = {r.id for r in member.roles}

        restricted_roles_config = {
            "Officer": os.getenv("ROLE_ID_OFFICER"),
            "Tank Commander": os.getenv("ROLE_ID_TANK_COMMANDER"),
        }
        restricted_roles_config = {k: int(v) for k, v in restricted_roles_config.items() if v and v.isdigit()}
        
        available_subclasses = []
        for subclass in all_subclasses:
            if subclass not in RESTRICTED_ROLES:
                available_subclasses.append(subclass)
                continue
            
            required_role_id = restricted_roles_config.get(subclass)
            if not required_role_id or required_role_id in user_role_ids:
                available_subclasses.append(subclass)

        subclass_select.disabled = False
        subclass_select.placeholder = "2. Choose your subclass..."
        if available_subclasses:
            subclass_select.options = [discord.SelectOption(label=s, emoji=EMOJI_MAPPING.get(s, "❔")) for s in available_subclasses]
        else:
            subclass_select.options = [discord.SelectOption(label="No subclasses available", value="no_subclass_available")]
            subclass_select.placeholder = "No subclasses available for you"

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
    def __init__(self, bot: commands.Bot, db: Database, event_id: int, message_id: int, user: discord.User, available_roles: List[str]):
        super().__init__(timeout=300)
        self.bot, self.db, self.event_id, self.message_id, self.user, self.role = bot, db, event_id, message_id, user, None
        self.subclass_select = SubclassSelect(db, event_id)
        self.add_item(RoleSelect(db, event_id, available_roles))
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
        event = await self.db.get_event_by_message_id(i.message.id)
        if not event: return await i.followup.send("Event not found.", ephemeral=True)
        
        restricted_roles_config = {
            "Commander": os.getenv("ROLE_ID_COMMANDER"), "Officer": os.getenv("ROLE_ID_OFFICER"),
            "Recon": os.getenv("ROLE_ID_RECON"), "Tank Commander": os.getenv("ROLE_ID_TANK_COMMANDER"),
            "Pathfinders": os.getenv("ROLE_ID_PATHFINDER"), "Artillery": os.getenv("ROLE_ID_ARTY"),
        }
        restricted_roles_config = {k: int(v) for k, v in restricted_roles_config.items() if v and v.isdigit()}

        user_role_ids = {r.id for r in i.user.roles}
        available_roles = []

        for role in ROLES:
            if role not in RESTRICTED_ROLES:
                available_roles.append(role)
                continue
            
            required_role_id = restricted_roles_config.get(role)
            if not required_role_id or required_role_id in user_role_ids:
                available_roles.append(role)

        await self.db.set_rsvp(event['event_id'], i.user.id, RsvpStatus.ACCEPTED)
        
        try:
            if not available_roles:
                await self.db.update_signup_role(event['event_id'], i.user.id, "Unassigned", None)
                await i.followup.send("Accepted! There were no specific roles available for you, so you have been marked as 'Unassigned'.", ephemeral=True)
            else:
                view = RoleSelectionView(i.client, self.db, event['event_id'], i.message.id, i.user, available_roles)
                await i.user.send(f"You accepted **{event['title']}**. Select your role:", view=view)
                await i.followup.send("Check your DMs to select your role!", ephemeral=True)
        except discord.Forbidden:
            await self.db.update_signup_role(event['event_id'], i.user.id, "Unassigned", None)
            await i.followup.send("Accepted, but I couldn't DM you. Role set to 'Unassigned'.", ephemeral=True)
            
        await self.update_embed(i, event['event_id'])

    @ui.button(label="Tentative", style=discord.ButtonStyle.secondary, custom_id="persistent_view:tentative")
    async def tentative(self, i: discord.Interaction, button: ui.Button):
        await i.response.defer(ephemeral=True)
        try:
            if event := await self.db.get_event_by_message_id(i.message.id):
                await self.db.set_rsvp(event['event_id'], i.user.id, RsvpStatus.TENTATIVE)
                await self.db.update_signup_role(event['event_id'], i.user.id, None, None)
                await self.update_embed(i, event['event_id'])
                await i.followup.send("Your RSVP has been set to Tentative.", ephemeral=True)
        except Exception as e:
            print(f"Error in 'tentative' button: {e}")
            traceback.print_exc()
            try:
                await i.followup.send("An error occurred while processing your RSVP. Please try again.", ephemeral=True)
            except:
                pass
            
    @ui.button(label="Decline", style=discord.ButtonStyle.danger, custom_id="persistent_view:decline")
    async def decline(self, i: discord.Interaction, button: ui.Button):
        await i.response.defer(ephemeral=True)
        try:
            if event := await self.db.get_event_by_message_id(i.message.id):
                await self.db.set_rsvp(event['event_id'], i.user.id, RsvpStatus.DECLINED)
                await self.db.update_signup_role(event['event_id'], i.user.id, None, None)
                await self.update_embed(i, event['event_id'])
                await i.followup.send("Your RSVP has been set to Declined.", ephemeral=True)
        except Exception as e:
            print(f"Error in 'decline' button: {e}")
            traceback.print_exc()
            try:
                await i.followup.send("An error occurred while processing your RSVP. Please try again.", ephemeral=True)
            except:
                pass

# --- FIX: Renamed this view to be specific to Reminders ---
class ReminderConfirmationView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.value = None

    @ui.button(label="Yes, Send Reminder", style=discord.ButtonStyle.green)
    async def confirm(self, i: discord.Interaction, button: ui.Button):
        await i.response.defer()
        self.value = True
        self.stop()

    @ui.button(label="No, Cancel", style=discord.ButtonStyle.red)
    async def reject(self, i: discord.Interaction, button: ui.Button):
        await i.response.defer()
        self.value = False
        self.stop()

# --- FIX: Re-created the generic ConfirmationView ---
class ConfirmationView(ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.value = None
        
    @ui.button(label="Yes", style=discord.ButtonStyle.green)
    async def confirm(self, i: discord.Interaction, button: ui.Button):
        await i.response.defer()
        self.value = True
        self.stop()
    
    @ui.button(label="No/Skip", style=discord.ButtonStyle.red)
    async def reject(self, i: discord.Interaction, button: ui.Button):
        await i.response.defer()
        self.value = False
        self.stop()

class ReminderConversation:
    def __init__(self, cog: 'EventManagement', interaction: discord.Interaction, target_role: discord.Role, member_ids: list[int]):
        self.cog = cog
        self.bot = cog.bot
        self.db = cog.db
        self.user = interaction.user
        self.guild = interaction.guild
        self.target_role = target_role
        self.member_ids = member_ids
        self.is_finished = False

    async def _wait_for_message(self):
        return await self.bot.wait_for('message', check=lambda m: m.author == self.user and isinstance(m.channel, discord.DMChannel), timeout=300.0)

    async def start(self):
        try:
            if not await self.ask_for_confirmation():
                await self.user.send("Reminder cancelled.")
                return
            
            message_content = await self.ask_for_message()
            if not message_content:
                return 

            await self.send_reminders(message_content)

        except asyncio.TimeoutError:
            await self.user.send("Your reminder request has timed out.")
        except Exception as e:
            print(f"Error in reminder conversation: {e}")
            traceback.print_exc()
            await self.user.send("An unexpected error occurred. The reminder has been cancelled.")
        finally:
            self.finish()

    async def ask_for_confirmation(self) -> bool:
        # --- FIX: Use the specific ReminderConfirmationView ---
        view = ReminderConfirmationView()
        msg = await self.user.send(
            f"You are about to send a reminder to **{len(self.member_ids)}** members of the '{self.target_role.name}' role. Do you wish to proceed?",
            view=view
        )
        await view.wait()
        if view.value is None:
            await msg.edit(content="Confirmation timed out.", view=None)
            return False
        
        await msg.delete()
        return view.value

    async def ask_for_message(self) -> Optional[str]:
        await self.user.send("Please type the reminder message you would like to send. Type `cancel` to stop.")
        try:
            message = await self._wait_for_message()
            if message.content.lower() == 'cancel':
                await self.user.send("Reminder cancelled.")
                return None
            return message.content
        except asyncio.TimeoutError:
            await self.user.send("Message input timed out. Reminder cancelled.")
            return None

    async def send_reminders(self, message_content: str):
        await self.user.send(f"Sending reminders to {len(self.member_ids)} members... This may take a moment.")
        
        success_count = 0
        fail_count = 0

        for member_id in self.member_ids:
            try:
                member = await self.guild.fetch_member(member_id)
                await member.send(message_content)
                success_count += 1
                await asyncio.sleep(0.5)
            except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                fail_count += 1
        
        await self.user.send(
            f"Reminder process complete!\n"
            f"✅ Successfully sent to {success_count} member(s).\n"
            f"❌ Failed to send to {fail_count} member(s) (they may have DMs disabled or have left the server)."
        )

    def finish(self):
        self.is_finished = True
        if self.user.id in self.cog.active_conversations:
            del self.cog.active_conversations[self.user.id]

class Conversation:
    def __init__(self, cog: 'EventManagement', interaction: discord.Interaction, db: Database, event_id: int = None):
        self.cog, self.bot, self.interaction, self.user, self.db, self.event_id = cog, cog.bot, interaction, interaction.user, db, event_id
        self.data, self.is_finished = {}, False

    async def start(self):
        try:
            if self.event_id and (event_data := await self.db.get_event_by_id(self.event_id)):
                self.data = dict(event_data)
            await self.user.send(f"Starting event {'editing' if self.event_id else 'creation'}. Type `cancel` at any time to stop.")
            await self.run_conversation()
        except Exception as e:
            print(f"Error starting conversation: {e}")
            traceback.print_exc()
            await self.cancel()
    
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
            if not await processor(prompt, data_key):
                await self.cancel()
                return
        await self.finish()

    async def _wait_for_message(self):
        return await self.bot.wait_for('message', check=lambda m: m.author == self.user and isinstance(m.channel, discord.DMChannel), timeout=300.0)

    async def process_text(self, prompt, data_key):
        if self.event_id and self.data.get(data_key): prompt += f"\n(Current: `{self.data.get(data_key)}`)"
        await self.user.send(prompt)
        try:
            msg = await self._wait_for_message()
            if msg.content.lower() == 'cancel': return False
            self.data[data_key] = msg.content
            return True
        except asyncio.TimeoutError:
            await self.user.send("Conversation timed out.")
            return False

    async def process_timezone(self, prompt, data_key):
        flat_tz_list = [tz for region in CURATED_TIMEZONES.values() for tz in region]
        
        description_lines = []
        count = 1
        for region, timezones in CURATED_TIMEZONES.items():
            description_lines.append(f"\n**__{region}__**")
            for tz in timezones:
                description_lines.append(f"`{count}` {tz}")
                count += 1
        
        embed = discord.Embed(title="Please Select a Timezone", description="\n".join(description_lines), color=discord.Color.blue())
        prompt_msg = "Please reply with the number for your desired timezone."
        if self.event_id and self.data.get(data_key): prompt_msg += f"\n(Current: `{self.data.get(data_key)}`)"
        
        await self.user.send(prompt_msg, embed=embed)
        
        try:
            msg = await self._wait_for_message()
            if msg.content.lower() == 'cancel': return False
            
            choice = int(msg.content)
            if 1 <= choice <= len(flat_tz_list):
                self.data[data_key] = flat_tz_list[choice - 1]
                await self.user.send(f"Timezone set to **{self.data[data_key]}**.")
                return True
            else:
                await self.user.send("Invalid number. Please try again.")
                return await self.process_timezone(prompt, data_key)
        except (ValueError, asyncio.TimeoutError):
            await self.user.send("Invalid input or conversation timed out.")
            return False

    async def process_start_time(self, prompt, data_key):
        while True:
            val = self.data.get(data_key).strftime('%d-%m-%Y %H:%M') if self.data.get(data_key) else ''
            p = prompt + (f"\n(Current: `{val}`)" if self.event_id and val else "")
            await self.user.send(p)
            try:
                msg = await self._wait_for_message()
                if msg.content.lower() == 'cancel': return False
                try:
                    naive_dt = datetime.datetime.strptime(msg.content, "%d-%m-%Y %H:%M")
                    selected_tz_str = self.data.get('timezone', 'UTC')
                    selected_tz = pytz.timezone(selected_tz_str)
                    self.data[data_key] = selected_tz.localize(naive_dt)
                    return True
                except ValueError:
                    await self.user.send("Invalid date format. Use `DD-MM-YYYY HH:MM`.")
            except asyncio.TimeoutError:
                await self.user.send("Conversation timed out.")
                return False

    async def process_end_time(self, prompt, data_key):
        while True:
            val = self.data.get(data_key).strftime('%d-%m-%Y %H:%M') if self.data.get(data_key) else ''
            p = prompt + (f"\n(Current: `{val}`)" if self.event_id and val else "")
            await self.user.send(p)
            try:
                msg = await self._wait_for_message()
                if msg.content.lower() == 'cancel': return False
                try:
                    naive_dt = datetime.datetime.strptime(msg.content, "%d-%m-%Y %H:%M")
                    selected_tz_str = self.data.get('timezone', 'UTC')
                    selected_tz = pytz.timezone(selected_tz_str)
                    self.data[data_key] = selected_tz.localize(naive_dt)
                    return True
                except ValueError:
                    await self.user.send("Invalid date format. Use `DD-MM-YYYY HH:MM`.")
            except asyncio.TimeoutError:
                await self.user.send("Conversation timed out.")
                return False

    async def ask_is_recurring(self, prompt, data_key):
        view = ConfirmationView()
        msg = await self.user.send("Is this a recurring event?", view=view)
        await view.wait()
        if view.value is None:
            await msg.delete()
            await self.user.send("Timed out.")
            return False
        await msg.delete()
        self.data['is_recurring'] = view.value
        if view.value:
            return await self.process_recurrence_rule(None, 'recurrence_rule')
        self.data['recurrence_rule'], self.data['recreation_hours'] = None, None
        return True

    async def process_recurrence_rule(self, prompt, data_key):
        p = "How often should it recur? (`daily`, `weekly`, `monthly`)"
        await self.user.send(p)
        try:
            msg = await self._wait_for_message()
            if msg.content.lower() == 'cancel': return False
            rule = msg.content.lower()
            if rule not in ['daily', 'weekly', 'monthly']:
                await self.user.send("Invalid input.")
                return await self.process_recurrence_rule(prompt, data_key)
            self.data[data_key] = rule
            return await self.process_recreation_hours(None, 'recreation_hours')
        except asyncio.TimeoutError:
            await self.user.send("Conversation timed out.")
            return False

    async def process_recreation_hours(self, prompt, data_key):
        p = "How many hours before the event should the new embed be created? (e.g., `168` for 7 days)"
        await self.user.send(p)
        try:
            msg = await self._wait_for_message()
            if msg.content.lower() == 'cancel': return False
            try:
                self.data[data_key] = int(msg.content)
                return True
            except ValueError:
                await self.user.send("Please enter a valid number.")
                return await self.process_recreation_hours(prompt, data_key)
        except asyncio.TimeoutError:
            await self.user.send("Conversation timed out.")
            return False

    async def _ask_roles(self, prompt, data_key, question):
        view = ConfirmationView()
        conf_msg = await self.user.send(question, view=view)
        await view.wait()
        if view.value is None: await conf_msg.delete(); return False
        await conf_msg.delete()

        if view.value:
            guild_roles = sorted([r for r in self.interaction.guild.roles if r.name != "@everyone" and not r.managed], key=lambda r: r.position, reverse=True)
            
            description_lines = [f"`{i+1}` {role.name}" for i, role in enumerate(guild_roles)]
            
            embed = discord.Embed(title="Please Select Role(s)", description="\n".join(description_lines), color=discord.Color.blue())
            prompt_msg = "Please reply with the number(s) for your desired roles, separated by commas (e.g., `1, 5, 12`)."
            await self.user.send(prompt_msg, embed=embed)

            try:
                msg = await self._wait_for_message()
                if msg.content.lower() == 'cancel': return False
                
                selected_indices = [int(i.strip()) - 1 for i in msg.content.split(',')]
                selected_role_ids = [guild_roles[i].id for i in selected_indices if 0 <= i < len(guild_roles)]
                
                self.data[data_key] = selected_role_ids
                if not selected_role_ids:
                     await self.user.send("No valid roles selected.")
                else:
                    names = [guild_roles[i].name for i in selected_indices if 0 <= i < len(guild_roles)]
                    await self.user.send(f"Roles set to: **{', '.join(names)}**")
                return True
            except (ValueError, asyncio.TimeoutError, IndexError):
                await self.user.send("Invalid input or conversation timed out.")
                return False
        else:
            self.data[data_key] = []
            return True

    async def ask_mention_roles(self, p, dk): return await self._ask_roles(p, dk, "Mention roles in the announcement?")
    async def ask_restrict_roles(self, p, dk): return await self._ask_roles(p, dk, "Restrict sign-ups to specific roles?")
        
    async def finish(self):
        if self.is_finished: return
        self.is_finished = True
        if self.user.id in self.cog.active_conversations:
            del self.cog.active_conversations[self.user.id]

        try:
            view = PersistentEventView(self.db)
            content = " ".join([f"<@&{rid}>" for rid in self.data.get('mention_role_ids', [])])

            if self.event_id:
                old_event_data = await self.db.get_event_by_id(self.event_id)
                old_thread_id = old_event_data.get('thread_id') if old_event_data else None
                
                await self.db.update_event(self.event_id, self.data)
                embed = await create_event_embed(self.bot, self.event_id, self.db)
                
                try:
                    channel = self.bot.get_channel(self.data['channel_id']) or await self.bot.fetch_channel(self.data['channel_id'])
                    message = await channel.fetch_message(self.data['message_id'])
                    await message.edit(content=content, embed=embed, view=view)
                    await self.user.send("Event updated successfully! The scheduler will create a new discussion channel shortly.")

                    if old_thread_id:
                        try:
                            old_channel = self.bot.get_channel(old_thread_id) or await self.bot.fetch_channel(old_thread_id)
                            if old_channel:
                                await old_channel.delete(reason="Event was edited.")
                                await self.user.send("The old discussion channel has been deleted.")
                        except discord.NotFound:
                            pass
                        except Exception as e:
                            print(f"Could not delete old discussion channel {old_thread_id}: {e}")
                            await self.user.send("Note: I couldn't delete the old discussion channel.")

                except (discord.NotFound, discord.Forbidden):
                    await self.user.send("Event details were updated, but I couldn't find or edit the original event message. It may have been deleted.")

            else:
                event_id = await self.db.create_event(self.interaction.guild.id, self.interaction.channel.id, self.user.id, self.data)
                embed = await create_event_embed(self.bot, event_id, self.db)
                target_channel = self.bot.get_channel(self.interaction.channel.id)

                if target_channel:
                    msg = await target_channel.send(content=content, embed=embed, view=view)
                    await self.db.update_event_message_id(event_id, msg.id)
                    await self.user.send(f"Event created successfully! (ID: {event_id}). Posting it now...")
                else:
                    await self.user.send("Event created, but I could not find the channel to post it in.")

        except Exception as e:
            print(f"Error finishing conversation: {e}")
            traceback.print_exc()
            await self.user.send("An unexpected error occurred while saving the event.")

    async def cancel(self):
        if self.is_finished: return
        self.is_finished = True
        if self.user.id in self.cog.active_conversations: del self.cog.active_conversations[self.user.id]
        await self.user.send("Event creation/editing cancelled")

class DeleteConfirmationView(ui.View):
    def __init__(self, event_management_cog, event_id: int):
        super().__init__(timeout=120)
        self.cog = event_management_cog
        self.event_id = event_id

    @ui.button(label="Yes, Delete Event", style=discord.ButtonStyle.danger)
    async def confirm_delete(self, interaction: discord.Interaction, button: ui.Button):
        event = await self.cog.db.get_event_by_id(self.event_id)
        if not event:
            return await interaction.response.edit_message(content="This event no longer exists.", view=None)

        for item in self.children: item.disabled = True
        await interaction.response.edit_message(content="Deleting event and notifying attendees...", view=self)

        if event.get('message_id') and event.get('channel_id'):
            try:
                channel = self.cog.bot.get_channel(event['channel_id']) or await self.cog.bot.fetch_channel(event['channel_id'])
                message = await channel.fetch_message(event['message_id'])
                await message.delete()
            except Exception as e: print(f"Could not delete event message: {e}")
        
        if event.get('thread_id'):
            try:
                thread = self.cog.bot.get_channel(event['thread_id']) or await self.cog.bot.fetch_channel(event['thread_id'])
                await thread.delete()
            except Exception as e: print(f"Could not delete event thread: {e}")

        await self.cog.db.soft_delete_event(self.event_id)

        signups = await self.cog.db.get_signups_for_event(self.event_id)
        accepted_users = [s['user_id'] for s in signups if s['rsvp_status'] == RsvpStatus.ACCEPTED]
        for user_id in accepted_users:
            try:
                user = self.cog.bot.get_user(user_id) or await self.cog.bot.fetch_user(user_id)
                await user.send(f"The event **{event['title']}** has been cancelled by an administrator.")
            except Exception as e: print(f"Could not DM user {user_id} about cancellation: {e}")
        
        await interaction.edit_original_response(content=f"Event '{event['title']}' has been deleted and attendees notified.", view=None)

    @ui.button(label="No, Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_delete(self, interaction: discord.Interaction, button: ui.Button):
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(content="Deletion cancelled.", view=self)

class EventManagement(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        self.active_conversations = {}

    event_group = app_commands.Group(name="event", description="Commands for creating and managing events.")

    async def role_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        roles = interaction.guild.roles
        return [
            app_commands.Choice(name=role.name, value=str(role.id))
            for role in roles if current.lower() in role.name.lower() and not role.is_default()
        ][:25]

    @event_group.command(name="create", description="Create a new event via DM.")
    async def create(self, interaction: discord.Interaction):
        await self.start_conversation(interaction)

    @event_group.command(name="edit", description="Edit an existing event via DM.")
    @app_commands.describe(event_id="The ID of the event to edit.")
    async def edit(self, interaction: discord.Interaction, event_id: int):
        if not (event := await self.db.get_event_by_id(event_id)) or event['guild_id'] != interaction.guild_id:
            return await interaction.response.send_message("Event not found.", ephemeral=True)
        await self.start_conversation(interaction, event_id)

    @event_group.command(name="delete", description="Marks an event for deletion and notifies attendees.")
    @app_commands.describe(event_id="The ID of the event to delete.")
    async def delete(self, interaction: discord.Interaction, event_id: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("You must be an administrator to delete events.", ephemeral=True)
        
        event = await self.db.get_event_by_id(event_id)
        if not event or event['guild_id'] != interaction.guild_id:
            return await interaction.response.send_message("Event not found or it does not belong to this server.", ephemeral=True)

        if event.get('deleted_at'):
            return await interaction.response.send_message("This event has already been deleted.", ephemeral=True)

        view = DeleteConfirmationView(self, event_id)
        await interaction.response.send_message(
            f"Are you sure you want to delete the event **{event['title']}**? This will notify all accepted attendees.",
            view=view,
            ephemeral=True
        )

    @event_group.command(name="restore", description="Restores a previously deleted event.")
    @app_commands.describe(event_id="The ID of the event to restore.")
    async def restore(self, interaction: discord.Interaction, event_id: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("You must be an administrator to restore events.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        
        event = await self.db.get_event_by_id(event_id, include_deleted=True)
        if not event or event['guild_id'] != interaction.guild_id:
            return await interaction.followup.send("Event not found.", ephemeral=True)
        
        if not event.get('deleted_at'):
            return await interaction.followup.send("This event is already active.", ephemeral=True)

        await self.db.restore_event(event_id)
        
        try:
            channel = self.bot.get_channel(event['channel_id']) or await self.bot.fetch_channel(event['channel_id'])
            embed = await create_event_embed(self.bot, event_id, self.db)
            view = PersistentEventView(self.db)
            content = " ".join([f"<@&{rid}>" for rid in event.get('mention_role_ids', [])])
            
            new_message = await channel.send(content=content, embed=embed, view=view)
            await self.db.update_event_message_id(event_id, new_message.id)
            await interaction.followup.send(f"Event '{event['title']}' has been restored and re-posted.")
        except Exception as e:
            await interaction.followup.send(f"Event data was restored, but failed to re-post the embed: {e}")

    @event_group.command(name="remind", description="Send a DM reminder to members of a role who have not RSVP'd.")
    @app_commands.describe(
        event_id="The ID of the event to send reminders for.",
        role="The role to target for reminders."
    )
    @app_commands.autocomplete(role=role_autocomplete)
    @app_commands.default_permissions(administrator=True)
    async def remind(self, interaction: discord.Interaction, event_id: int, role: str):
        await interaction.response.send_message("Preparing your reminder, please check your DMs...", ephemeral=True)
        
        if interaction.user.id in self.active_conversations:
            return await interaction.followup.send("You are already in an active conversation with me. Please finish or cancel it first.", ephemeral=True)

        try:
            role_id = int(role)
            target_role = interaction.guild.get_role(role_id)
            if not target_role:
                return await interaction.followup.send("The selected role could not be found.", ephemeral=True)
        except ValueError:
            return await interaction.followup.send("Invalid role selected.", ephemeral=True)

        event = await self.db.get_event_by_id(event_id)
        if not event or event['guild_id'] != interaction.guild_id:
            return await interaction.followup.send("Event not found in this server.", ephemeral=True)

        rsvpd_user_ids = await self.db.get_all_rsvpd_user_ids_for_event(event_id)
        
        member_ids_to_remind = []
        for member in target_role.members:
            if not member.bot and member.id not in rsvpd_user_ids:
                member_ids_to_remind.append(member.id)

        if not member_ids_to_remind:
            return await interaction.followup.send(
                f"No members of the '{target_role.name}' role need a reminder for this event. They have all RSVP'd.",
                ephemeral=True
            )
        
        conv = ReminderConversation(self, interaction, target_role, member_ids_to_remind)
        self.active_conversations[interaction.user.id] = conv
        asyncio.create_task(conv.start())

    async def start_conversation(self, interaction: discord.Interaction, event_id: int = None):
        if interaction.user.id in self.active_conversations:
            return await interaction.response.send_message("You are already in an active conversation with me. Please finish or cancel it first.", ephemeral=True)
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
