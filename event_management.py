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

# --- Google Sheets Integration ---
class GSheetsClient:
    def __init__(self):
        try:
            scopes = ["https://www.googleapis.com/auth/spreadsheets"]
            creds = Credentials.from_service_account_file("google-credentials.json", scopes=scopes)
            self.client = gspread.authorize(creds)
        except FileNotFoundError:
            print("!!! google-credentials.json not found. Google Sheets integration will be disabled.")
            self.client = None
        except Exception as e:
            print(f"!!! Error initializing Google Sheets client: {e}")
            self.client = None

    def export_roster(self, sheet_url: str, event_title: str, signups: list):
        if not self.client:
            raise Exception("Google Sheets client is not configured. Check logs for details.")
        
        spreadsheet = self.client.open_by_url(sheet_url)
        
        # Create a new worksheet with the event title, handling potential duplicates
        worksheet_title = event_title[:100] # Google sheets have a 100 char limit for sheet titles
        try:
            worksheet = spreadsheet.add_worksheet(title=worksheet_title, rows="100", cols="20")
        except gspread.exceptions.APIError:
            # If sheet already exists, append a timestamp
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H%M%S")
            worksheet = spreadsheet.add_worksheet(title=f"{worksheet_title}_{timestamp}", rows="100", cols="20")

        # Prepare data for upload
        header = ["Player Name", "Primary Role", "Subclass"]
        rows_to_upload = [header]
        
        for signup in signups:
            if signup['rsvp_status'] == RsvpStatus.ACCEPTED:
                rows_to_upload.append([
                    signup.get('user_display_name', 'Unknown User'),
                    signup.get('role_name', 'N/A'),
                    signup.get('subclass_name', 'N/A')
                ])
        
        worksheet.update('A1', rows_to_upload)
        return worksheet.url

# --- HLL Emoji Mapping (Loaded from Environment) ---
EMOJI_MAPPING = {
    # ... (Emoji mapping remains the same)
}

# --- Helper function to generate the event embed ---
async def create_event_embed(bot: commands.Bot, event_id: int, db: Database) -> discord.Embed:
    # ... (This function remains the same)
    pass # Placeholder to keep structure

# --- All other UI Components and the Conversation class remain the same ---
# ...

class EventManagement(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        self.active_conversations = {}
        self.gsheets_client = GSheetsClient()

    # ... (on_message, start_conversation, create, edit, delete methods remain the same)
    
    @app_commands.command(name="export", description="Export the event roster to a Google Sheet.")
    @app_commands.describe(
        event_id="The ID of the event to export.",
        sheet_url="The URL of the Google Sheet to export to."
    )
    async def export(self, interaction: discord.Interaction, event_id: int, sheet_url: str):
        if not self.gsheets_client.client:
            await interaction.response.send_message("Google Sheets integration is not configured correctly. Please check the bot's logs.", ephemeral=True)
            return
            
        # Permission Check
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
            
            # Enrich signups with display names
            signups = []
            for signup in signups_raw:
                user = interaction.guild.get_member(signup['user_id']) or (await self.bot.fetch_user(signup['user_id']))
                signup_data = dict(signup)
                signup_data['user_display_name'] = user.display_name if user else f"Unknown User (ID: {signup['user_id']})"
                signups.append(signup_data)

            worksheet_url = self.gsheets_client.export_roster(sheet_url, event['title'], signups)
            await interaction.followup.send(f"✅ Roster for **{event['title']}** has been successfully exported!\n[Click here to view the sheet]({worksheet_url})", ephemeral=True)

        except gspread.exceptions.SpreadsheetNotFound:
            await interaction.followup.send("I couldn't find that Google Sheet. Please check the URL and make sure you have shared it with the bot's service account email.", ephemeral=True)
        except Exception as e:
            print(f"--- An error occurred during Google Sheets export ---")
            traceback.print_exc()
            await interaction.followup.send(f"An unexpected error occurred during the export. Error: {e}", ephemeral=True)


    # --- Setup Command Group ---
    setup = app_commands.Group(name="setup", description="Commands for setting up the bot.")

    # ... (set_manager_role, set_restricted_role, set_thread_schedule methods remain the same)


async def setup(bot: commands.Bot, db: Database):
    # ... (setup remains the same)
    pass # Placeholder

# ... (Conversation class and other UI views remain the same)
