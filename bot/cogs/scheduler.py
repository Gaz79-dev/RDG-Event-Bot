import discord
from discord.ext import tasks, commands
import datetime
import pytz
import traceback
from dateutil.relativedelta import relativedelta

# Corrected relative import
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
        """Periodically checks for events that need a discussion thread created."""
        # ... implementation from previous version ...
        pass

    async def process_thread_creation(self, event: dict):
        # ... implementation from previous version ...
        pass

    @tasks.loop(minutes=5)
    async def recreate_recurring_events(self):
        """Periodically checks for recurring events that need to be recreated."""
        # Import locally to prevent circular import errors
        from .event_management import create_event_embed, PersistentEventView
        # ... rest of implementation from previous version ...
        pass

    def calculate_next_occurrence(self, last_event_time: datetime.datetime, rule: str) -> datetime.datetime:
        # ... implementation from previous version ...
        pass

    async def process_event_recreation(self, event: dict, create_event_embed_func, persistent_view_class):
        # ... implementation from previous version ...
        pass

    @tasks.loop(time=datetime.time(hour=0, minute=1, tzinfo=pytz.utc))
    async def cleanup_finished_events(self):
        """Runs once daily to delete old, non-recurring events and their threads."""
        # ... implementation from previous version ...
        pass

    # --- FIX: Moved the before_loop decorators to the END of the class ---
    @create_event_threads.before_loop
    @recreate_recurring_events.before_loop
    @cleanup_finished_events.before_loop
    async def before_tasks(self):
        """Waits until the bot is fully logged in and ready before starting loops."""
        await self.bot.wait_until_ready()

async def setup(bot: commands.Bot):
    """Sets up the scheduler cog."""
    await bot.add_cog(Scheduler(bot, bot.db))
