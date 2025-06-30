import discord
from discord.ext import tasks, commands
import datetime
import pytz
import traceback
from dateutil.relativedelta import relativedelta

# --- FIX: Corrected the relative import path to go up one level ---
from ..utils.database import Database, RsvpStatus

class Scheduler(commands.Cog):
    """Cog for handling scheduled background tasks."""
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        self.create_event_threads.start()
        self.recreate_recurring_events.start()
        self.cleanup_finished_events.start()

    def cog_unload(self):
        """Cleanly cancels all tasks when the cog is unloaded."""
        self.create_event_threads.cancel()
        self.recreate_recurring_events.cancel()
        self.cleanup_finished_events.cancel()

    @tasks.loop(minutes=1)
    async def create_event_threads(self):
        # ... implementation from previous version ...
        pass

    async def process_thread_creation(self, event: dict):
        # ... implementation from previous version ...
        pass

    @tasks.loop(minutes=5)
    async def recreate_recurring_events(self):
        """Periodically checks for recurring events that need to be recreated."""
        # --- FIX: Import locally to prevent circular import errors ---
        from .event_management import create_event_embed, PersistentEventView
        try:
            events_to_recreate = await self.db.get_events_for_recreation()
            if not events_to_recreate:
                return

            print(f"Scheduler: Found {len(events_to_recreate)} recurring event(s) to process for recreation.")
            for event in events_to_recreate:
                await self.process_event_recreation(event, create_event_embed, PersistentEventView)
        except Exception as e:
            print(f"An error occurred in the recreate_recurring_events loop: {e}")
            traceback.print_exc()

    # ... all other methods from the file should be kept here ...
    
    @create_event_threads.before_loop
    @recreate_recurring_events.before_loop
    @cleanup_finished_events.before_loop
    async def before_tasks(self):
        """Waits until the bot is fully logged in and ready before starting loops."""
        await self.bot.wait_until_ready()

# --- FIX: The setup function now gets the db instance directly from the bot object ---
async def setup(bot: commands.Bot):
    """Sets up the scheduler cog."""
    await bot.add_cog(Scheduler(bot, bot.db))
