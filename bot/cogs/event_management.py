import discord
from discord.ext import commands
from discord import app_commands, ui
from datetime import datetime
import pytz

from bot.utils.database import Database

class EventWizard:
    def __init__(self, db, user, channel, guild):
        self.db = db
        self.user = user
        self.channel = channel
        self.guild = guild
        self.data = {}

    async def start(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TitleModal(self))

    async def next_step(self, interaction: discord.Interaction, step, value):
        self.data[step] = value

        # Step through the flow
        if step == "title":
            await interaction.response.send_modal(TimezoneModal(self))
        elif step == "timezone":
            await interaction.response.send_modal(DateTimeModal(self, "Start Date and Time", "start_datetime"))
        elif step == "start_datetime":
            await interaction.response.send_modal(DateTimeModal(self, "Finish Date and Time", "finish_datetime"))
        elif step == "finish_datetime":
            await interaction.response.send_modal(DescriptionModal(self))
        elif step == "description":
            view = YesNoView(self)
            msg = await interaction.response.send_message("Is the event recurring?", view=view, ephemeral=True)
            view.message = msg
        elif step == "recurring":
            view = RoleMultiSelectView(self, "mention_role_ids", self.guild)
            msg = await interaction.response.send_message("Do you want to mention any roles? (select or skip)", view=view, ephemeral=True)
            view.message = msg
        elif step == "mention_role_ids":
            view = RoleMultiSelectView(self, "restrict_role_ids", self.guild)
            msg = await interaction.response.send_message("Do you want to restrict RSVP to any roles? (select or skip)", view=view, ephemeral=True)
            view.message = msg
        elif step == "restrict_role_ids":
            await self.finish(interaction)

    async def finish(self, interaction: discord.Interaction):
        event_id = await self.db.create_event(
            self.guild.id,
            self.channel.id,
            self.user.id,
            self.data
        )
        await interaction.response.send_message(f"✅ Event created with ID `{event_id}`!", ephemeral=True)

# --- Modals ---

class TitleModal(ui.Modal, title="Event Title"):
    title = ui.TextInput(label="Event Title", required=True)
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard
    async def on_submit(self, interaction: discord.Interaction):
        await self.wizard.next_step(interaction, "title", self.title.value)

class TimezoneModal(ui.Modal, title="Timezone"):
    timezone = ui.TextInput(label="Timezone", required=True)
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard
    async def on_submit(self, interaction: discord.Interaction):
        value = self.timezone.value.strip()
        try:
            pytz.timezone(value)
        except Exception:
            await interaction.response.send_message("Invalid timezone.", ephemeral=True)
            return
        await self.wizard.next_step(interaction, "timezone", value)

class DateTimeModal(ui.Modal):
    datetime_str = ui.TextInput(label="", placeholder="YYYY-MM-DD HH:MM", required=True)
    def __init__(self, wizard, label, key):
        super().__init__(title=label)
        self.wizard = wizard
        self.label = label
        self.key = key
        self.datetime_str.label = label
    async def on_submit(self, interaction: discord.Interaction):
        tz = self.wizard.data.get("timezone", "UTC")
        try:
            dt = datetime.strptime(self.datetime_str.value, "%Y-%m-%d %H:%M")
            dt = pytz.timezone(tz).localize(dt)
        except Exception:
            await interaction.response.send_message("Invalid datetime format.", ephemeral=True)
            return
        await self.wizard.next_step(interaction, self.key, dt.isoformat())

class DescriptionModal(ui.Modal, title="Event Description"):
    description = ui.TextInput(label="Description", style=discord.TextStyle.paragraph, required=True)
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard
    async def on_submit(self, interaction: discord.Interaction):
        await self.wizard.next_step(interaction, "description", self.description.value)

# --- Views ---

class YesNoView(ui.View):
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard
        self.message = None

    @ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        await self.wizard.next_step(interaction, "recurring", True)
        if self.message: await self.message.delete()

    @ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        await self.wizard.next_step(interaction, "recurring", False)
        if self.message: await self.message.delete()

class RoleMultiSelectView(ui.View):
    def __init__(self, wizard, key, guild):
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
        ids = [int(val) for val in self.values]
        await self.parent_view.wizard.next_step(interaction, self.key, ids)
        if self.parent_view.message: await self.parent_view.message.delete()

# --- Cog ---

class EventManagement(commands.Cog):
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db

    @app_commands.command(name="event_create", description="Create a new event with guided prompts.")
    async def event_create(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You need to be an administrator.", ephemeral=True)
            return
        wizard = EventWizard(
            db=self.db,
            user=interaction.user,
            channel=interaction.channel,
            guild=interaction.guild,
        )
        await wizard.start(interaction)

async def setup(bot):
    await bot.add_cog(EventManagement(bot, bot.db))
