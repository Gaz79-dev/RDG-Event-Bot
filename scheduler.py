import discord
from discord.ext import tasks, commands
import datetime
import pytz
import traceback
from dateutil.relativedelta import relativedelta

# Adjust the import path based on your project structure
from utils.database import Database, RsvpStatus
# We will import from event_management locally to avoid circular imports

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
        try:
            events_to_process = await self.db.get_events_for_thread_creation()
            if not events_to_process:
                return
            
            print(f"Scheduler: Found {len(events_to_process)} event(s) to process for thread creation.")
            for event in events_to_process:
                await self.process_thread_creation(event)
        except Exception as e:
            print(f"An error occurred in the create_event_threads loop: {e}")
            traceback.print_exc()

    async def process_thread_creation(self, event: dict):
        """Handles the logic for creating a single event thread."""
        print(f"Scheduler: Processing event ID {event['event_id']} ('{event['title']}') for thread creation.")
        guild = self.bot.get_guild(event['guild_id'])
        if not guild:
            print(f"Scheduler: Could not find guild {event['guild_id']}. Skipping event {event['event_id']}.")
            return

        channel = guild.get_channel(event['channel_id'])
        if not isinstance(channel, discord.TextChannel):
            print(f"Scheduler: Could not find text channel {event['channel_id']}. Skipping event {event['event_id']}.")
            return
        
        try:
            message = await channel.fetch_message(event['message_id'])
            
            try:
                event_tz = pytz.timezone(event['timezone'])
                local_event_time = event['event_time'].astimezone(event_tz)
                time_str = local_event_time.strftime("%Y-%m-%d %H:%M")
                thread_name = f"{event['title']} - {time_str} ({event['timezone']})"
            except (pytz.UnknownTimeZoneError, TypeError):
                time_str = event['event_time'].strftime("%Y-%m-%d %H:%M UTC")
                thread_name = f"{event['title']} - {time_str}"

            if len(thread_name) > 100:
                thread_name = thread_name[:97] + "..."

            thread = await channel.create_thread(name=thread_name, message=message, type=discord.ChannelType.private_thread)
            
            await self.db.update_event_thread_id(event['event_id'], thread.id)
            await self.db.mark_thread_as_created(event['event_id'])
            print(f"Scheduler: Successfully created private thread '{thread_name}' for event {event['event_id']}.")

            signups = await self.db.get_signups_for_event(event['event_id'])
            accepted_user_ids = {s['user_id'] for s in signups if s['rsvp_status'] == RsvpStatus.ACCEPTED}
            accepted_user_ids.add(event['creator_id'])
            
            await thread.send(f"Welcome to the private discussion for **{event['title']}**! This thread is for confirmed attendees.")

            for user_id in accepted_user_ids:
                try:
                    member = guild.get_member(user_id) or await guild.fetch_member(user_id)
                    await thread.add_user(member)
                except (discord.NotFound, discord.HTTPException) as e:
                    print(f"Scheduler: Failed to add user {user_id} to thread for event {event['event_id']}. Error: {e}")

        except discord.NotFound:
            print(f"Scheduler: Could not find message {event['message_id']} for event {event['event_id']}. Marking as failed.")
            await self.db.mark_thread_as_created(event['event_id'])
        except discord.Forbidden:
            print(f"Scheduler: PERMISSION ERROR creating thread for event {event['event_id']}. Marking as failed.")
            await self.db.mark_thread_as_created(event['event_id'])
        except Exception as e:
            print(f"Scheduler: An unexpected error occurred while processing thread for event {event['event_id']}: {e}")
            traceback.print_exc()
            await self.db.mark_thread_as_created(event['event_id'])

    @tasks.loop(minutes=5)
    async def recreate_recurring_events(self):
        """Periodically checks for recurring events that need to be recreated."""
        try:
            events_to_recreate = await self.db.get_events_for_recreation()
            if not events_to_recreate:
                return

            print(f"Scheduler: Found {len(events_to_recreate)} recurring event(s) to process for recreation.")
            for event in events_to_recreate:
                await self.process_event_recreation(event)
        except Exception as e:
            print(f"An error occurred in the recreate_recurring_events loop: {e}")
            traceback.print_exc()

    def calculate_next_occurrence(self, last_event_time: datetime.datetime, rule: str) -> datetime.datetime:
        """Calculates the next occurrence of an event based on its rule."""
        if rule == 'daily':
            return last_event_time + relativedelta(days=1)
        elif rule == 'weekly':
            return last_event_time + relativedelta(weeks=1)
        elif rule == 'monthly':
            return last_event_time + relativedelta(months=1)
        return None

    async def process_event_recreation(self, event: dict):
        """Handles the logic for recreating a single recurring event."""
        # --- FIX: Local import to prevent circular dependency ---
        from .event_management import create_event_embed, PersistentEventView

        print(f"Scheduler: Processing event ID {event['event_id']} ('{event['title']}') for recreation.")
        
        next_event_time = self.calculate_next_occurrence(event['event_time'], event['recurrence_rule'])
        if not next_event_time:
            print(f"Scheduler: Invalid recurrence rule '{event['recurrence_rule']}' for event {event['event_id']}. Skipping.")
            return

        time_until_next = next_event_time - datetime.datetime.now(pytz.utc)
        recreation_delta = datetime.timedelta(hours=event.get('recreation_hours', 24*7))

        if time_until_next <= recreation_delta:
            print(f"Scheduler: Event {event['event_id']} is within the recreation window. Creating new event.")
            
            new_event_data = dict(event)
            new_event_data['start_time'] = next_event_time
            
            if event['end_time']:
                duration = event['end_time'] - event['event_time']
                new_event_data['end_time'] = next_event_time + duration
            
            new_event_data['parent_event_id'] = event.get('parent_event_id') or event['event_id']

            guild = self.bot.get_guild(event['guild_id'])
            channel = guild.get_channel(event['channel_id']) if guild else None

            if not guild or not channel:
                print(f"Scheduler: Could not find guild or channel for event {event['event_id']}. Cannot recreate."); return

            try:
                new_event_id = await self.db.create_event(guild.id, channel.id, event['creator_id'], new_event_data)
                print(f"Scheduler: Created new event record {new_event_id} for original event {event['event_id']}.")

                view = PersistentEventView(self.db)
                embed = await create_event_embed(self.bot, new_event_id, self.db)
                content = " ".join([f"<@&{rid}>" for rid in event.get('mention_role_ids', [])])
                
                msg = await channel.send(content=content, embed=embed, view=view)
                await self.db.update_event_message_id(new_event_id, msg.id)
                print(f"Scheduler: Posted new message {msg.id} for new event {new_event_id}.")

                await self.db.update_last_recreated_at(event['event_id'])
                print(f"Scheduler: Marked original event {event['event_id']} as recreated.")

            except Exception as e:
                print(f"Scheduler: FAILED to recreate event {event['event_id']}. Error: {e}")
                traceback.print_exc()

    @tasks.loop(time=datetime.time(hour=0, minute=1, tzinfo=pytz.utc))
    async def cleanup_finished_events(self):
        """Runs once daily to delete old, non-recurring events and their threads."""
        print("Scheduler: Running daily cleanup of finished events...")
        try:
            events_to_delete = await self.db.get_events_for_deletion()
            if not events_to_delete:
                print("Scheduler: No old events found to delete.")
                return

            print(f"Scheduler: Found {len(events_to_delete)} old event(s) to delete.")
            deleted_count = 0
            for event in events_to_delete:
                print(f"Scheduler: Deleting event ID {event['event_id']}...")
                guild = self.bot.get_guild(event['guild_id'])
                if not guild:
                    print(f"  - Guild {event['guild_id']} not found. Deleting DB record only.")
                    await self.db.delete_event(event['event_id'])
                    deleted_count += 1
                    continue

                if event['thread_id']:
                    try:
                        thread = guild.get_thread(event['thread_id'])
                        if thread:
                            await thread.delete()
                            print(f"  - Deleted thread {event['thread_id']}.")
                    except discord.Forbidden:
                        print(f"  - PERMISSION ERROR: Could not delete thread {event['thread_id']}.")
                    except Exception as e:
                        print(f"  - Unexpected error deleting thread {event['thread_id']}: {e}")

                if event['message_id']:
                    try:
                        channel = guild.get_channel(event['channel_id'])
                        if channel:
                            message = channel.get_partial_message(event['message_id'])
                            await message.delete()
                            print(f"  - Deleted message {event['message_id']}.")
                    except discord.NotFound:
                        pass
                    except discord.Forbidden:
                        print(f"  - PERMISSION ERROR: Could not delete message {event['message_id']}.")
                    except Exception as e:
                        print(f"  - Unexpected error deleting message {event['message_id']}: {e}")
                
                await self.db.delete_event(event['event_id'])
                deleted_count += 1
                print(f"  - Deleted event record {event['event_id']} from database.")
            
            print(f"Scheduler: Cleanup complete. Deleted {deleted_count} event(s).")

        except Exception as e:
            print(f"An error occurred in the cleanup_finished_events loop: {e}")
            traceback.print_exc()

    @create_event_threads.before_loop
    @recreate_recurring_events.before_loop
    @cleanup_finished_events.before_loop
    async def before_tasks(self):
        """Waits until the bot is fully logged in and ready before starting loops."""
        await self.bot.wait_until_ready()

async def setup(bot: commands.Bot, db: Database):
    """Sets up the scheduler cog."""
    await bot.add_cog(Scheduler(bot, db))
