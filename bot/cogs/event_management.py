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
            channel = self.bot.get_channel(event['channel_id']) or await self
