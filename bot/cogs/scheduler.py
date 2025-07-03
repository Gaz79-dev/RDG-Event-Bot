import discord
from discord.ext import tasks, commands
import datetime
import pytz
import traceback
from dateutil.relativedelta import relativedelta

# Use relative import to go up one level to the 'bot' package root
from ..utils.database import Database

class Scheduler(commands.Cog):
    """Cog for handling scheduled background tasks."""
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        self.create_event_threads.start()
        self.recreate_recurring_events.start()
        self.cleanup_finished_events.start()
        self.purge_deleted_events.start()

    def cog_unload(self):
        """Cleanly cancels all tasks when the cog is unloaded."""
        self.create_event_threads.cancel()
        self.recreate_recurring_events.cancel()
        self.cleanup_finished_events.cancel()
        self.purge_deleted_events.cancel()

    @tasks.loop(minutes=1)
    async def create_event_threads(self):
        """Periodically checks for events that need a discussion thread created."""
        try:
            events_to_process = await self.db.get_events_for_thread_creation()
            for event in events_to_process:
                await self.process_thread_creation(event)
        except Exception as e:
            print(f"Error in create_event_threads loop: {e}")
            traceback.print_exc()

    async def process_thread_creation(self, event: dict):
        """Creates a single event thread."""
        try:
            channel = self.bot.get_channel(event['channel_id']) or await self.bot.fetch_channel(event['channel_id'])
            message = await channel.fetch_message(event['message_id'])
            
            event_time_str = discord.utils.format_dt(event['event_time'], style='f')
            thread_name = f"{event['title']} ({event_time_str})"
            
            thread = await message.create_thread(name=thread_name, auto_archive_duration=1440) # 24 hours
            await self.db.mark_thread_created(event['event_id'], thread.id)
            print(f"Created thread '{thread_name}' for event ID {event['event_id']}.")
        except discord.NotFound:
            print(f"Could not find message {event['message_id']} for event {event['event_id']}. Cannot create thread.")
            await self.db.mark_thread_created(event['event_id'], 0) # Mark as created to prevent retries
        except Exception as e:
            print(f"Failed to process thread creation for event {event['event_id']}: {e}")
            traceback.print_exc()

    @tasks.loop(minutes=5)
    async def recreate_recurring_events(self):
        """Periodically checks for recurring events that need to be recreated."""
        # Import locally to prevent circular import errors at startup
        from .event_management import create_event_embed, PersistentEventView
        
        try:
            parent_events = await self.db.get_events_for_recreation()
            for event in parent_events:
                await self.process_event_recreation(event, create_event_embed, PersistentEventView)
        except Exception as e:
            print(f"Error in recreate_recurring_events loop: {e}")
            traceback.print_exc()

    def calculate_next_occurrence(self, last_event_time: datetime.datetime, rule: str) -> datetime.datetime:
        """Calculates the next occurrence based on a simple rule."""
        now = datetime.datetime.now(last_event_time.tzinfo)
        next_occurrence = last_event_time
        
        # Keep advancing the date until it's in the future
        while next_occurrence <= now:
            if rule == 'daily':
                next_occurrence += relativedelta(days=1)
            elif rule == 'weekly':
                next_occurrence += relativedelta(weeks=1)
            elif rule == 'monthly':
                next_occurrence += relativedelta(months=1)
            else: # Should not happen
                return None
        return next_occurrence

    async def process_event_recreation(self, parent_event: dict, create_embed_func, persistent_view_class):
        """Creates the next occurrence of a recurring event."""
        next_start_time = self.calculate_next_occurrence(parent_event['event_time'], parent_event['recurrence_rule'])
        if not next_start_time: return

        # Only create the next event if it's within the creation window
        recreation_window = next_start_time - datetime.timedelta(hours=parent_event.get('recreation_hours', 24))
        if datetime.datetime.now(next_start_time.tzinfo) < recreation_window:
            return

        print(f"Recreating event for parent ID {parent_event['event_id']}. Next occurrence: {next_start_time}")
        
        # Copy data and update times for the new child event
        child_data = dict(parent_event)
        duration = parent_event['end_time'] - parent_event['event_time']
        child_data['start_time'] = next_start_time
        child_data['end_time'] = next_start_time + duration
        child_data['is_recurring'] = False
        child_data['parent_event_id'] = parent_event['event_id']
        
        try:
            child_id = await self.db.create_event(
                parent_event['guild_id'], parent_event['channel_id'], parent_event['creator_id'], child_data
            )
            
            target_channel = self.bot.get_channel(parent_event['channel_id']) or await self.bot.fetch_channel(parent_event['channel_id'])
            
            view = persistent_view_class(self.db)
            embed = await create_embed_func(self.bot, child_id, self.db)
            content = " ".join([f"<@&{rid}>" for rid in parent_event.get('mention_role_ids', [])])
            
            msg = await target_channel.send(content=content, embed=embed, view=view)
            await self.db.update_event_message_id(child_id, msg.id)
            
            # Mark the parent as having been recreated
            await self.db.update_last_recreated_at(parent_event['event_id'])
            print(f"Successfully recreated event. New child event ID: {child_id}")
            
        except Exception as e:
            print(f"Failed to process recreation for parent event {parent_event['event_id']}: {e}")
            traceback.print_exc()

    @tasks.loop(time=datetime.time(hour=0, minute=5, tzinfo=pytz.utc)) # Run 5 mins past midnight
    async def purge_deleted_events(self):
        """Runs once daily to permanently delete events marked for deletion over 7 days ago."""
        print("Running daily purge of old soft-deleted events...")
        try:
            events_to_purge = await self.db.get_events_for_purging()
            for event in events_to_purge:
                await self.db.delete_event(event['event_id'])
                print(f"Permanently purged event {event['event_id']} from database.")
            if len(events_to_purge) > 0:
                 print(f"Daily purge finished. Permanently removed {len(events_to_purge)} events.")
        except Exception as e:
            print(f"Error in purge_deleted_events loop: {e}")
            traceback.print_exc()

    async def before_tasks(self):
        """Waits until the bot is fully logged in and ready before starting loops."""
        await self.bot.wait_until_ready()
    
    @tasks.loop(time=datetime.time(hour=0, minute=1, tzinfo=pytz.utc))
    async def cleanup_finished_events(self):
        """Runs once daily to delete old, non-recurring events and their threads."""
        print("Running daily cleanup of old events...")
        try:
            events_to_delete = await self.db.get_finished_events_for_cleanup()
            for event in events_to_delete:
                # Delete the discussion thread if it exists
                if event.get('thread_id'):
                    try:
                        thread = self.bot.get_channel(event['thread_id']) or await self.bot.fetch_channel(event['thread_id'])
                        await thread.delete()
                    except discord.NotFound:
                        pass # Thread already gone
                    except Exception as e:
                        print(f"Could not delete thread for event {event['event_id']}: {e}")

                # This deletes the event from the database, which cascades to squads and signups.
                # This is correct for BOTH one-off events and finished child occurrences of recurring events.
                await self.db.delete_event(event['event_id'])
            
            if len(events_to_delete) > 0:
                print(f"Daily cleanup finished. Removed {len(events_to_delete)} old events.")
        except Exception as e:
            print(f"Error in cleanup_finished_events loop: {e}")
            traceback.print_exc()

    @create_event_threads.before_loop
    @recreate_recurring_events.before_loop
    @cleanup_finished_events.before_loop
    @purge_deleted_events.before_loop
    async def before_tasks(self):
        """Waits until the bot is fully logged in and ready before starting loops."""
        await self.bot.wait_until_ready()

async def setup(bot: commands.Bot):
    """Sets up the scheduler cog."""
    await bot.add_cog(Scheduler(bot, bot.db))
