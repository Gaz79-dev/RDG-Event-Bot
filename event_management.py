import discord
from discord.ext import commands
from discord import app_commands, ui
import datetime
import traceback
import os
import pytz
from urllib.parse import urlencode
import asyncio
import gspread
from google.oauth2.service_account import Credentials

# Adjust the import path based on your project structure
from utils.database import Database, RsvpStatus, ROLES, SUBCLASSES, RESTRICTED_ROLES

# --- Google Sheets Integration Helper ---
class GSheetsClient:
    def __init__(self):
        try:
            # Path to the credentials file inside the Docker container
            creds_path = "/usr/src/app/google-credentials.json"
            scopes = ["https://www.googleapis.com/auth/spreadsheets"]
            creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
            self.client = gspread.authorize(creds)
            print("Successfully initialized Google Sheets client.")
        except FileNotFoundError:
            print("!!! WARNING: google-credentials.json not found. Google Sheets integration will be disabled.")
            self.client = None
        except Exception as e:
            print(f"!!! ERROR: Failed to initialize Google Sheets client: {e}")
            self.client = None

    def export_roster(self, sheet_url: str, event_title: str, signups: list):
        if not self.client:
            raise Exception("Google Sheets client is not configured or failed to initialize.")
        
        spreadsheet = self.client.open_by_url(sheet_url)
        
        worksheet_title = event_title[:100]
        try:
            worksheet = spreadsheet.add_worksheet(title=worksheet_title, rows="100", cols="3")
        except gspread.exceptions.APIError as e:
            if 'already exists' in str(e):
                timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                worksheet = spreadsheet.add_worksheet(title=f"{worksheet_title}-{timestamp}", rows="100", cols="3")
            else:
                raise

        header = ["Player Name", "Primary Role", "Subclass"]
        rows_to_upload = [header]
        
        for signup in signups:
            if signup['rsvp_status'] == RsvpStatus.ACCEPTED:
                rows_to_upload.append([
                    signup.get('user_display_name', 'Unknown User'),
                    signup.get('role_name', 'N/A'),
                    signup.get('subclass_name', 'N/A')
                ])
        
        worksheet.update('A1', rows_to_upload, value_input_option='USER_ENTERED')
        worksheet.format("A1:C1", {"textFormat": {"bold": True}})
        return worksheet.url

# --- HLL Emoji Mapping (Loaded from Environment) ---
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

# --- Helper function to generate Google Calendar Link ---
def create_google_calendar_link(event: dict) -> str:
    # ... (This function remains the same)
    pass

# --- Helper function to generate the event embed ---
async def create_event_embed(bot: commands.Bot, event_id: int, db: Database) -> discord.Embed:
    # ... (This function remains the same)
    pass

# --- UI Components and Conversation Logic ---
# ... (All other classes like MultiRoleSelect, ConfirmationView, RoleSelect, PersistentEventView, Conversation, etc. remain the same)

class EventManagement(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        self.active_conversations = {}
        self.gsheets_client = GSheetsClient()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not isinstance(message.channel, discord.DMChannel): return
        if message.author.id in self.active_conversations:
            await self.active_conversations[message.author.id].handle_response(message)

    async def start_conversation(self, interaction: discord.Interaction, event_id: int = None):
        # ... (This method remains the same)
        pass

    @app_commands.command(name="create", description="Create a new event via DM.")
    async def create(self, interaction: discord.Interaction):
        await self.start_conversation(interaction)

    @app_commands.command(name="edit", description="Edit an existing event via DM.")
    @app_commands.describe(event_id="The ID of the event to edit.")
    async def edit(self, interaction: discord.Interaction, event_id: int):
        # ... (This command remains the same)
        pass

    @app_commands.command(name="delete", description="Delete an existing event by its ID.")
    @app_commands.describe(event_id="The ID of the event to delete.")
    async def delete(self, interaction: discord.Interaction, event_id: int):
        # ... (This command remains the same)
        pass

    @app_commands.command(name="export", description="Export the event roster to a Google Sheet.")
    @app_commands.describe(event_id="The ID of the event to export.", sheet_url="The URL of the Google Sheet to export to.")
    async def export(self, interaction: discord.Interaction, event_id: int, sheet_url: str):
        if not self.gsheets_client.client:
            await interaction.response.send_message("Google Sheets integration is not configured correctly. Please check the bot's logs.", ephemeral=True)
            return
            
        event = await self.db.get_event_by_id(event_id)
        if not event or event['guild_id'] != interaction.guild_id:
            await interaction.response.send_message("Event not found.", ephemeral=True)
            return
            
        member = await interaction.guild.fetch_member(interaction.user.id)
        manager_role_id = await self.db.get_manager_role_id(interaction.guild.id)
        is_creator = interaction.user.id == event['creator_id']
        is_manager = manager_role_id and manager_role_id in [r.id for r in member.roles]
        is_admin = member.guild_permissions.administrator
        
        if not (is_creator or is_manager or is_admin):
            await interaction.response.send_message("You don't have permission to export this event's roster.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        
        try:
            signups_raw = await self.db.get_signups_for_event(event_id)
            
            signups = []
            for signup in signups_raw:
                user = interaction.guild.get_member(signup['user_id']) or (await self.bot.fetch_user(signup['user_id']))
                signup_data = dict(signup)
                signup_data['user_display_name'] = user.display_name if user else f"Unknown User (ID: {signup['user_id']})"
                signups.append(signup_data)

            worksheet_url = self.gsheets_client.export_roster(sheet_url, event['title'], signups)
            await interaction.followup.send(f"✅ Roster for **{event['title']}** has been successfully exported!\n[Click here to view the sheet]({worksheet_url})", ephemeral=True)

        except gspread.exceptions.SpreadsheetNotFound:
            await interaction.followup.send("I couldn't find that Google Sheet. Please check the URL and make sure you have shared it with me.", ephemeral=True)
        except Exception as e:
            print(f"--- An error occurred during Google Sheets export ---")
            traceback.print_exc()
            await interaction.followup.send(f"An unexpected error occurred during the export. Error: {e}", ephemeral=True)

    # --- Setup Command Group ---
    setup = app_commands.Group(name="setup", description="Commands for setting up the bot.")

    @setup.command(name="manager_role", description="Set the role that can manage events.")
    @app_commands.describe(role="The role to designate as Event Manager")
    async def set_manager_role(self, interaction: discord.Interaction, role: discord.Role):
        # ... (This command remains the same)
        pass

    @setup.command(name="restricted_role", description="Set the required Discord role for an in-game role.")
    @app_commands.describe(ingame_role="The in-game role to restrict", discord_role="The Discord role required")
    @app_commands.choices(ingame_role=[app_commands.Choice(name=r, value=r) for r in RESTRICTED_ROLES])
    async def set_restricted_role(self, interaction: discord.Interaction, ingame_role: app_commands.Choice[str], discord_role: discord.Role):
        # ... (This command remains the same)
        pass
    
    @setup.command(name="thread_schedule", description="Set how many hours before an event its discussion thread is created.")
    @app_commands.describe(hours="Number of hours before the event (e.g., 24)")
    async def set_thread_schedule(self, interaction: discord.Interaction, hours: app_commands.Range[int, 1, 168]):
        # ... (This command remains the same)
        pass

async def setup(bot: commands.Bot, db: Database):
    # ... (This function remains the same)
    pass
    
# ... (The Conversation class and other UI components are still here, but are omitted for brevity as they are unchanged)
