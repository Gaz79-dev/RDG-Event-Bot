import discord
from discord.ext import tasks, commands
import datetime
import pytz
import traceback
from dateutil.relativedelta import relativedelta

# Adjust the import path based on your project structure
from utils.database import Database, RsvpStatus
from cogs.event_management import create_event_embed, PersistentEventView

class Scheduler(commands.Cog):
    """Cog for handling scheduled background tasks."""
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        self.create_event_threads.start()
        self.recreate_recurring_events.start() # Start the new task

    def cog_unload(self):
        """Cleanly cancels all tasks when the cog is unloaded."""
        self.create_event_threads.cancel()
        self.recreate_recurring_events.cancel()

    @tasks.loop(minutes=1)
    async def create_event_threads(self):
        """Periodically checks for events that need a discussion thread created."""
        print("Scheduler: Running check for events needing threads...")
        try:
            events_to_process = await self.db.get_events_for_thread_creation()
            if not events_to_process:
                print("Scheduler: No events are due for thread creation at this time.")
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

            thread = await message.create_thread(name=thread_name, type=discord.ChannelType.private_thread)
            
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
        print("Scheduler: Running check for recurring events to recreate...")
        try:
            events_to_recreate = await self.db.get_events_for_recreation()
            if not events_to_recreate:
                print("Scheduler: No recurring events are due for recreation at this time.")
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
        print(f"Scheduler: Processing event ID {event['event_id']} ('{event['title']}') for recreation.")
        
        next_event_time = self.calculate_next_occurrence(event['event_time'], event['recurrence_rule'])
        if not next_event_time:
            print(f"Scheduler: Invalid recurrence rule '{event['recurrence_rule']}' for event {event['event_id']}. Skipping.")
            return

        time_until_next = next_event_time - datetime.datetime.now(pytz.utc)
        recreation_delta = datetime.timedelta(hours=event.get('recreation_hours', 24*7)) # Default to 7 days if not set

        if time_until_next <= recreation_delta:
            print(f"Scheduler: Event {event['event_id']} is within the recreation window. Creating new event.")
            
            # Prepare data for the new event
            new_event_data = dict(event)
            new_event_data['start_time'] = next_event_time
            
            # Calculate new end_time if original had a duration
            if event['end_time']:
                duration = event['end_time'] - event['event_time']
                new_event_data['end_time'] = next_event_time + duration
            
            # Set the parent ID to the original event's ID, or its parent's ID if it's already a child
            new_event_data['parent_event_id'] = event.get('parent_event_id') or event['event_id']

            guild = self.bot.get_guild(event['guild_id'])
            channel = guild.get_channel(event['channel_id']) if guild else None

            if not guild or not channel:
                print(f"Scheduler: Could not find guild or channel for event {event['event_id']}. Cannot recreate."); return

            try:
                # Create the new event in the database
                new_event_id = await self.db.create_event(guild.id, channel.id, event['creator_id'], new_event_data)
                print(f"Scheduler: Created new event record {new_event_id} for original event {event['event_id']}.")

                # Post the new embed to the channel
                view = PersistentEventView(self.db)
                embed = await create_event_embed(self.bot, new_event_id, self.db)
                content = " ".join([f"<@&{rid}>" for rid in event.get('mention_role_ids', [])])
                
                msg = await channel.send(content=content, embed=embed, view=view)
                await self.db.update_event_message_id(new_event_id, msg.id)
                print(f"Scheduler: Posted new message {msg.id} for new event {new_event_id}.")

                # Mark the old event as processed to prevent it from being recreated again immediately
                await self.db.update_last_recreated_at(event['event_id'])
                print(f"Scheduler: Marked original event {event['event_id']} as recreated.")

            except Exception as e:
                print(f"Scheduler: FAILED to recreate event {event['event_id']}. Error: {e}")
                traceback.print_exc()

    @create_event_threads.before_loop
    @recreate_recurring_events.before_loop
    async def before_tasks(self):
        """Waits until the bot is fully logged in and ready before starting loops."""
        await self.bot.wait_until_ready()
        print(f"Scheduler: Cog is ready, task loops are starting.")


async def setup(bot: commands.Bot, db: Database):
    """Sets up the scheduler cog."""
    await bot.add_cog(Scheduler(bot, db))
