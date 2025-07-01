import discord
from discord.ext import commands
from discord import app_commands, ui
from typing import Optional, List
import asyncio
from datetime import datetime, timezone
import pytz

# Assume your Database class is imported as below
from ..utils.database import Database

class EventCreationView(ui.View):
    def __init__(self, ctx, db: Database):
        super().__init__(timeout=900)
        self.ctx = ctx
        self.db = db
        self.data = {}
        self.step = 0
        self.message: Optional[discord.Message] = None

    async def start(self):
        await self.ask_next()

    async def ask_next(self):
        if self.step == 0:
            await self.ask_title()
        elif self.step == 1:
            await self.ask_timezone()
        elif self.step == 2:
            await self.ask_start_datetime()
        elif self.step == 3:
            await self.ask_end_datetime()
        elif self.step == 4:
            await self.ask_description()
        elif self.step == 5:
            await self.ask_recurring()
        elif self.step == 6:
            await self.ask_mention_roles()
        elif self.step == 7:
            await self.ask_restrict_roles()
        else:
            await self.finish()

    async def ask_title(self):
        modal = TitleModal(self)
        await self.ctx.response.send_modal(modal)

    async def ask_timezone(self):
        modal = TimezoneModal(self)
        await self.ctx.followup.send("Please enter the event timezone (e.g., Europe/London, UTC, US/Eastern):", ephemeral=True, view=None)
        await self.ctx.followup.send_modal(modal)

    async def ask_start_datetime(self):
        modal = DateTimeModal(self, label="Start Date and Time")
        await self.ctx.followup.send_modal(modal)

    async def ask_end_datetime(self):
        modal = DateTimeModal(self, label="Finish Date and Time")
        await self.ctx.followup.send_modal(modal)

    async def ask_description(self):
        modal = DescriptionModal(self)
        await self.ctx.followup.send_modal(modal)

    async def ask_recurring(self):
        view = YesNoView(self, "Is the event recurring?")
        m = await self.ctx.followup.send("Is the event recurring?", view=view, ephemeral=True)
        view.message = m

    async def ask_mention_roles(self):
        guild_roles = [
            discord.SelectOption(label=role.name, value=str(role.id))
            for role in self.ctx.guild.roles if not role.is_default()
        ]
        view = RoleMultiSelectView(self, "Do you want to mention any roles?", guild_roles, "mention_role_ids")
        m = await self.ctx.followup.send("Do you want to mention any roles? (select one or more, or skip)", view=view, ephemeral=True)
        view.message = m

    async def ask_restrict_roles(self):
        guild_roles = [
            discord.SelectOption(label=role.name, value=str(role.id))
            for role in self.ctx.guild.roles if not role.is_default()
        ]
        view = RoleMultiSelectView(self, "Do you want to restrict RSVP to any roles?", guild_roles, "restrict_role_ids")
        m = await self.ctx.followup.send("Do you want to restrict RSVP to any roles? (select one or more, or skip)", view=view, ephemeral=True)
        view.message = m

    async def finish(self):
        # Actually create the event in the database
        event_id = await self.db.create_event(
            self.ctx.guild.id,
            self.ctx.channel.id,
            self.ctx.user.id,
            self.data
        )
        await self.ctx.followup.send(f"✅ Event created with ID `{event_id}`!", ephemeral=True)

    # These methods are called by components/modals/views below:
    async def modal_submit(self, key, value):
        self.data[key] = value
        self.step += 1
        await self.ask_next()

    async def yesno_submit(self, key, value):
        self.data[key] = value
        self.step += 1
        await self.ask_next()

    async def roles_submit(self, key, value):
        self.data[key] = value
        self.step += 1
        await self.ask_next()

# ----- Modal Definitions -----

class TitleModal(ui.Modal, title="Event Title"):
    title = ui.TextInput(label="Event Title", placeholder="e.g., Operation Thunder", required=True)

    def __init__(self, parent: EventCreationView):
        super().__init__()
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction):
        await self.parent.modal_submit('title', self.title.value)
        await interaction.response.defer()

class TimezoneModal(ui.Modal, title="Timezone"):
    timezone = ui.TextInput(label="Timezone", placeholder="e.g., UTC, Europe/London, US/Eastern", required=True)

    def __init__(self, parent: EventCreationView):
        super().__init__()
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction):
        # Validate timezone with pytz
        tz_value = self.timezone.value.strip()
        try:
            pytz.timezone(tz_value)
        except Exception:
            await interaction.response.send_message("Invalid timezone. Please try again.", ephemeral=True)
            return
        await self.parent.modal_submit('timezone', tz_value)
        await interaction.response.defer()

class DateTimeModal(ui.Modal):
    datetime_str = ui.TextInput(label="", placeholder="YYYY-MM-DD HH:MM (24h)", required=True)

    def __init__(self, parent: EventCreationView, label):
        self.label = label
        super().__init__(title=label)
        self.parent = parent
        self.datetime_str.label = label

    async def on_submit(self, interaction: discord.Interaction):
        # Parse with the timezone provided earlier
        tzname = self.parent.data.get('timezone', 'UTC')
        try:
            dt = datetime.strptime(self.datetime_str.value, "%Y-%m-%d %H:%M")
            dt = pytz.timezone(tzname).localize(dt)
        except Exception:
            await interaction.response.send_message("Invalid datetime format. Please use YYYY-MM-DD HH:MM.", ephemeral=True)
            return
        key = 'start_datetime' if "Start" in self.label else 'finish_datetime'
        await self.parent.modal_submit(key, dt.isoformat())
        await interaction.response.defer()

class DescriptionModal(ui.Modal, title="Event Description"):
    description = ui.TextInput(label="Description", style=discord.TextStyle.paragraph, placeholder="Enter event details...", required=True)

    def __init__(self, parent: EventCreationView):
        super().__init__()
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction):
        await self.parent.modal_submit('description', self.description.value)
        await interaction.response.defer()

# ----- Views -----

class YesNoView(ui.View):
    def __init__(self, parent: EventCreationView, prompt: str):
        super().__init__()
        self.parent = parent
        self.prompt = prompt
        self.message = None

    @ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: ui.Button):
        await self.parent.yesno_submit('recurring', True)
        await interaction.response.defer()
        await self.message.delete()

    @ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: ui.Button):
        await self.parent.yesno_submit('recurring', False)
        await interaction.response.defer()
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
        # Store the selected role IDs as a list of ints
        role_ids = [int(val) for val in self.values]
        await self.parent_view.parent.roles_submit(self.key, role_ids)
        await interaction.response.defer()
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
        await view.start()

async def setup(bot: commands.Bot):
    await bot.add_cog(EventManagement(bot, bot.db))
