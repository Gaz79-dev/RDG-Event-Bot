import discord
from discord.ext import commands
from discord import app_commands, ui
from typing import Optional, List
from datetime import datetime
import pytz

from bot.utils.database import Database

# --- Modal Definitions ---

class TitleModal(ui.Modal, title="Event Title"):
    title = ui.TextInput(label="Event Title", placeholder="e.g., Operation Thunder", required=True)

    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard

    async def on_submit(self, interaction: discord.Interaction):
        await self.wizard.advance(interaction, 'title', self.title.value)

class TimezoneModal(ui.Modal, title="Timezone"):
    timezone = ui.TextInput(label="Timezone", placeholder="e.g., UTC, Europe/London, US/Eastern", required=True)

    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard

    async def on_submit(self, interaction: discord.Interaction):
        tz_value = self.timezone.value.strip()
        try:
            pytz.timezone(tz_value)
        except Exception:
            await interaction.response.send_message("Invalid timezone. Please try again.", ephemeral=True)
            return
        await self.wizard.advance(interaction, 'timezone', tz_value)

class DateTimeModal(ui.Modal):
    datetime_str = ui.TextInput(label="", placeholder="YYYY-MM-DD HH:MM (24h)", required=True)

    def __init__(self, wizard, label, key):
        super().__init__(title=label)
        self.wizard = wizard
        self.key = key
        self.datetime_str.label = label

    async def on_submit(self, interaction: discord.Interaction):
        tzname = self.wizard.data.get('timezone', 'UTC')
        try:
            dt = datetime.strptime(self.datetime_str.value, "%Y-%m-%d %H:%M")
            dt = pytz.timezone(tzname).localize(dt)
        except Exception:
            await interaction.response.send_message("Invalid datetime format. Please use YYYY-MM-DD HH:MM.", ephemeral=True)
            return
        await self.wizard.advance(interaction, self.key, dt.isoformat())

class DescriptionModal(ui.Modal, title="Event Description"):
    description = ui.TextInput(label="Description", style=discord.TextStyle.paragraph, placeholder="Enter event details...", required=True)

    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard

    async def on_submit(self, interaction: discord.Interaction):
        await self.wizard.advance(interaction, 'description', self.description.value)

# --- Views for Button and Role Select ---

class YesNoView(ui.View):
    def __init__(self, wizard, key):
        super().__init__()
        self.wizard = wizard
        self.key = key
        self.message = None

    @ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        await self.wizard.advance(interaction, self.key, True)
        if self.message: await self.message.delete()

    @ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        await self.wizard.advance(interaction, self.key, False)
        if self.message: await self.message.delete()

class RoleMultiSelectView(ui.View):
    def __init__(self, wizard, key, guild: discord.Guild):
        super().__init__()
        self.wizard = wizard
        self.key = key
        self.message = None
        options = [
            discord.SelectOption(label=role.name, value=str(role.id))
            for role in guild.roles if not role.is_default()
        ]
        self.add_item(RoleMultiSelect(self, options, key))

class RoleMultiSelect(ui.Select):
    def __init__(self, parent_view, options, key):
        super().__init__(placeholder="Select roles (or skip)", min_values=0, max_values=len(options), options=options)
        self.parent_view = parent_view
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        role_ids = [int(val) for val in self.values]
        await self.parent_view.wizard.advance(interaction, self.key, role_ids)
        if self.parent_view.message: await self.parent_view.message.delete()

# --- Wizard State Handler ---

class EventWizard:
    """Handles the event creation flow and state."""
    def __init__(self, db: Database, user: discord.Member, channel: discord.abc.Messageable, guild: discord.Guild):
        self.db = db
        self.user = user
        self.channel = channel
        self.guild = guild
        self.data = {}
        self.step = 0

    async def start(self, interaction: discord.Interaction):
        self.step = 0
        await interaction.response.send_modal(TitleModal(self))

    async def advance(self, interaction: discord.Interaction, key, value):
        self.data[key] = value
        self.step += 1

        # Step logic
        if self.step == 1:
            await interaction.response.send_modal(TimezoneModal(self))
        elif self.step == 2:
            modal = DateTimeModal(self, label="Start Date and Time", key="start_datetime")
            await interaction.response.send_modal(modal)
        elif self.step == 3:
            modal = DateTimeModal(self, label="Finish Date and Time", key="finish_datetime")
            await interaction.response.send_modal(modal)
        elif self.step == 4:
            await interaction.response.send_modal(DescriptionModal(self))
        elif self.step == 5:
            view = YesNoView(self, "recurring")
            m = await interaction.response.send_message("Is the event recurring?", view=view, ephemeral=True)
            view.message = m
        elif self.step == 6:
            view = RoleMultiSelectView(self, "mention_role_ids", self.guild)
            m = await interaction.response.send_message("Do you want to mention any roles? (select one or more, or skip)", view=view, ephemeral=True)
            view.message = m
        elif self.step == 7:
            view = RoleMultiSelectView(self, "restrict_role_ids", self.guild)
            m = await interaction.response.send_message("Do you want to restrict RSVP to any roles? (select one or more, or skip)", view=view, ephemeral=True)
            view.message = m
        else:
            await self.finish(interaction)

    async def finish(self, interaction: discord.Interaction):
        event_id = await self.db.create_event(
            self.guild.id,
            self.channel.id,
            self.user.id,
            self.data
        )
        await interaction.response.send_message(f"✅ Event created with ID `{event_id}`!", ephemeral=True)

# --- Cog and Command Registration ---

class EventManagement(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db

    @app_commands.command(name="event_create", description="Create a new event with guided prompts.")
    async def event_create(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("You need to be an administrator to create events.", ephemeral=True)
        wizard = EventWizard(
            db=self.db,
            user=interaction.user,
            channel=interaction.channel,
            guild=interaction.guild
        )
        await wizard.start(interaction)

async def setup(bot: commands.Bot):
    await bot.add_cog(EventManagement(bot, bot.db))
