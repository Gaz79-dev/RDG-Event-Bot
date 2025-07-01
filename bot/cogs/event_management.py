import discord
from discord.ext import commands
from discord import app_commands, ui
from typing import Optional, List
from datetime import datetime
import pytz
import asyncio

from bot.utils.database import Database

class EventCreationView(ui.View):
    def __init__(self, interaction: discord.Interaction, db: Database):
        super().__init__(timeout=900)
        self.interaction = interaction
        self.db = db
        self.data = {}
        self.step = 1  # Start at 1 since title is asked in the command handler
        self.message: Optional[discord.Message] = None

    async def ask_next(self, interaction: discord.Interaction):
        if self.step == 1:
            await self.ask_timezone(interaction)
        elif self.step == 2:
            await self.ask_start_datetime(interaction)
        elif self.step == 3:
            await self.ask_end_datetime(interaction)
        elif self.step == 4:
            await self.ask_description(interaction)
        elif self.step == 5:
            await self.ask_recurring(interaction)
        elif self.step == 6:
            await self.ask_mention_roles(interaction)
        elif self.step == 7:
            await self.ask_restrict_roles(interaction)
        else:
            await self.finish(interaction)

    async def ask_timezone(self, interaction: discord.Interaction):
        modal = TimezoneModal(self)
        await interaction.response.send_modal(modal)

    async def ask_start_datetime(self, interaction: discord.Interaction):
        modal = DateTimeModal(self, label="Start Date and Time")
        await interaction.response.send_modal(modal)

    async def ask_end_datetime(self, interaction: discord.Interaction):
        modal = DateTimeModal(self, label="Finish Date and Time")
        await interaction.response.send_modal(modal)

    async def ask_description(self, interaction: discord.Interaction):
        modal = DescriptionModal(self)
        await interaction.response.send_modal(modal)

    async def ask_recurring(self, interaction: discord.Interaction):
        view = YesNoView(self, "Is the event recurring?")
        m = await interaction.response.send_message("Is the event recurring?", view=view, ephemeral=True)
        view.message = m

    async def ask_mention_roles(self, interaction: discord.Interaction):
        guild_roles = [
            discord.SelectOption(label=role.name, value=str(role.id))
            for role in interaction.guild.roles if not role.is_default()
        ]
        view = RoleMultiSelectView(self, "Do you want to mention any roles?", guild_roles, "mention_role_ids")
        m = await interaction.response.send_message("Do you want to mention any roles? (select one or more, or skip)", view=view, ephemeral=True)
        view.message = m

    async def ask_restrict_roles(self, interaction: discord.Interaction):
        guild_roles = [
            discord.SelectOption(label=role.name, value=str(role.id))
            for role in interaction.guild.roles if not role.is_default()
        ]
        view = RoleMultiSelectView(self, "Do you want to restrict RSVP to any roles?", guild_roles, "restrict_role_ids")
        m = await interaction.response.send_message("Do you want to restrict RSVP to any roles? (select one or more, or skip)", view=view, ephemeral=True)
        view.message = m

    async def finish(self, interaction: discord.Interaction):
        event_id = await self.db.create_event(
            interaction.guild.id,
            interaction.channel.id,
            interaction.user.id,
            self.data
        )
        await interaction.response.send_message(f"✅ Event created with ID `{event_id}`!", ephemeral=True)

    # These methods are called by components/modals/views below:
    async def modal_submit(self, interaction: discord.Interaction, key, value):
        self.data[key] = value
        self.step += 1
        await self.ask_next(interaction)

    async def yesno_submit(self, interaction: discord.Interaction, key, value):
        self.data[key] = value
        self.step += 1
        await self.ask_next(interaction)

    async def roles_submit(self, interaction: discord.Interaction, key, value):
        self.data[key] = value
        self.step += 1
        await self.ask_next(interaction)

# ----- Modal Definitions -----

class TitleModal(ui.Modal, title="Event Title"):
    title = ui.TextInput(label="Event Title", placeholder="e.g., Operation Thunder", required=True)

    def __init__(self, view: EventCreationView):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        self.view.data['title'] = self.title.value
        await self.view.ask_next(interaction)

class TimezoneModal(ui.Modal, title="Timezone"):
    timezone = ui.TextInput(label="Timezone", placeholder="e.g., UTC, Europe/London, US/Eastern", required=True)

    def __init__(self, view: EventCreationView):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        tz_value = self.timezone.value.strip()
        try:
            pytz.timezone(tz_value)
        except Exception:
            await interaction.response.send_message("Invalid timezone. Please try again.", ephemeral=True)
            return
        await self.view.modal_submit(interaction, 'timezone', tz_value)

class DateTimeModal(ui.Modal):
    datetime_str = ui.TextInput(label="", placeholder="YYYY-MM-DD HH:MM (24h)", required=True)

    def __init__(self, view: EventCreationView, label):
        super().__init__(title=label)
        self.view = view
        self.label = label
        self.datetime_str.label = label

    async def on_submit(self, interaction: discord.Interaction):
        tzname = self.view.data.get('timezone', 'UTC')
        try:
            dt = datetime.strptime(self.datetime_str.value, "%Y-%m-%d %H:%M")
            dt = pytz.timezone(tzname).localize(dt)
        except Exception:
            await interaction.response.send_message("Invalid datetime format. Please use YYYY-MM-DD HH:MM.", ephemeral=True)
            return
        key = 'start_datetime' if "Start" in self.label else 'finish_datetime'
        await self.view.modal_submit(interaction, key, dt.isoformat())

class DescriptionModal(ui.Modal, title="Event Description"):
    description = ui.TextInput(label="Description", style=discord.TextStyle.paragraph, placeholder="Enter event details...", required=True)

    def __init__(self, view: EventCreationView):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        await self.view.modal_submit(interaction, 'description', self.description.value)

# ----- Views -----

class YesNoView(ui.View):
    def __init__(self, parent: EventCreationView, prompt: str):
        super().__init__()
        self.parent = parent
        self.prompt = prompt
        self.message = None

    @ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        await self.parent.yesno_submit(interaction, 'recurring', True)
        if self.message:
            await self.message.delete()

    @ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        await self.parent.yesno_submit(interaction, 'recurring', False)
        if self.message:
            await self.message.delete()

class RoleMultiSelectView(ui.View):
    def __init__(self, parent: EventCreationView, prompt, options, key):
        super().__init__()
        self.parent = parent
        self.prompt = prompt
        self.key = key
        self.message = None
        self.add_item(RoleMultiSelect(self, options, key))

class RoleMultiSelect(ui.Select):
    def __init__(self, parent_view, options, key):
        super().__init__(placeholder="Select roles (or skip)", min_values=0, max_values=len(options), options=options)
        self.parent_view = parent_view
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        role_ids = [int(val) for val in self.values]
        await interaction.response.defer()
        await self.parent_view.parent.roles_submit(interaction, self.key, role_ids)
        if self.parent_view.message:
            await self.parent_view.message.delete()

# ----- Command -----

class EventManagement(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db

    @app_commands.command(name="event_create", description="Create a new event with guided prompts.")
    async def event_create(self, interaction: discord.Interaction):
        """Start the event creation wizard."""
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("You need to be an administrator to create events.", ephemeral=True)
        view = EventCreationView(interaction, self.db)
        modal = TitleModal(view)
        await interaction.response.send_modal(modal)  # <-- Immediate response with modal

async def setup(bot: commands.Bot):
    await bot.add_cog(EventManagement(bot, bot.db))
