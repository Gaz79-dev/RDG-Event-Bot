import discord
from discord.ext import tasks, commands
import datetime
import pytz
import traceback
from dateutil.relativedelta import relativedelta

# Use relative import to go up one level to the 'bot' package root
from ..utils.database import Database, RsvpStatus
# --- FIX: Import the embed creator to post signups in the new thread ---
from .event_management import create_event_embed

class Scheduler(commands.Cog):
    """Cog for handling scheduled background tasks."""
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        print("[Scheduler Cog] Initialized. Starting tasks...")
        self.create_event_threads.start()
        self.recreate_recurring_events.start()
        self.cleanup_finished_events.start()
        self.purge_deleted_events.start()
        self.sync_event_threads.start()
        self.process_tentatives.start()

    def cog_unload(self):
        """Cleanly cancels all tasks when the cog is unloaded."""
        self.create_event_threads.cancel()
        self.recreate_recurring_events.cancel()
        self.cleanup_finished_events.cancel()
        self.purge_deleted_events.cancel()
        self.sync_event_threads.cancel()
        self.process_tentatives.cancel()

    #Process Tentative RSVP's for Player Stats
    @tasks.loop(hours=1)
    async def process_tentatives(self):
        """Periodically converts 'Tentative' to 'Declined' for past events."""
        print("\n[Scheduler] Running process_tentatives loop...")
        try:
            tentative_signups = await self.db.get_past_events_with_tentatives()
            if not tentative_signups:
                print("[Scheduler] No tentative signups to process.")
                return

            for signup in tentative_signups:
                # This will trigger the decrement/increment logic in the database
                await self.db.set_rsvp(signup['event_id'], signup['user_id'], RsvpStatus.DECLINED)
                print(f"  [ProcessTentative] Converted User {signup['user_id']} to Declined for Event {signup['event_id']}.")
            
            print(f"[Scheduler] Processed {len(tentative_signups)} tentative signups.")
        except Exception as e:
            print(f"[Scheduler] FATAL ERROR in process_tentatives loop: {e}")
            traceback.print_exc()
    
    # --- ADDITION: The new task to sync members ---
    @tasks.loop(minutes=5)
    async def sync_event_threads(self):
        """Periodically syncs thread members with the latest accepted signups."""
        print("\n[Scheduler] Running sync_event_threads loop...")
        try:
            active_events = await self.db.get_active_events_with_threads()
            if not active_events:
                print("[Scheduler] No active threads to sync this cycle.")
                return

            for event in active_events:
                guild = self.bot.get_guild(event['guild_id'])
                if not guild: continue
                
                thread = guild.get_thread(event['thread_id'])
                if not thread: continue

                # Get the list of users who SHOULD be in the thread from the DB
                signups = await self.db.get_signups_for_event(event['event_id'])
                accepted_user_ids = {s['user_id'] for s in signups if s['rsvp_status'] == RsvpStatus.ACCEPTED}

                # Get the list of users who ARE in the thread from Discord
                thread_member_ids = {member.id for member in thread.members}

                # Calculate which users to add or remove
                users_to_add = accepted_user_ids - thread_member_ids
                users_to_remove = thread_member_ids - accepted_user_ids

                # Add users who have newly accepted
                for user_id in users_to_add:
                    try:
                        member = await guild.fetch_member(user_id)
                        await thread.add_user(member)
                        print(f"  [Sync:{event['event_id']}] Added {member.display_name} to thread.")
                    except Exception as e:
                        print(f"  [Sync:{event['event_id']}] FAILED to add member {user_id}: {e}")
                
                # Remove users who are no longer "Accepted"
                for user_id in users_to_remove:
                    # Don't let the bot remove itself from the thread
                    if user_id == self.bot.user.id:
                        continue
                    try:
                        member = await guild.fetch_member(user_id)
                        await thread.remove_user(member)
                        print(f"  [Sync:{event['event_id']}] Removed {member.display_name} from thread.")
                    except Exception as e:
                        print(f"  [Sync:{event['event_id']}] FAILED to remove member {user_id}: {e}")

        except Exception as e:
            print(f"[Scheduler] FATAL ERROR in sync_event_threads loop: {e}")
            traceback.print_exc()

    @tasks.loop(minutes=1)
    async def create_event_threads(self):
        """Periodically checks for events that need a discussion thread created."""
        print("\n[Scheduler] Running create_event_threads loop...")
        try:
            events_to_process = await self.db.get_events_for_thread_creation()
            print(f"[Scheduler] Found {len(events_to_process)} event(s) awaiting channel creation.")
            
            if not events_to_process:
                print("[Scheduler] No events to process this cycle.")
                return

            for event in events_to_process:
                print(f"[Scheduler] Processing event ID: {event['event_id']}")
                await self.process_thread_creation(event)
                
        except Exception as e:
            print(f"[Scheduler] FATAL ERROR in create_event_threads loop: {e}")
            traceback.print_exc()

    async def process_thread_creation(self, event: dict):
        """Creates a single event discussion thread and adds/notifies accepted members."""
        event_id = event['event_id']
        print(f"  [Process:{event_id}] Starting thread creation process.")
        try:
            parent_channel = self.bot.get_channel(event['channel_id']) or await self.bot.fetch_channel(event['channel_id'])
            if not parent_channel:
                print(f"  [Process:{event_id}] FAILED: Could not find parent channel {event['channel_id']}. Will not mark as created.")
                return
            
            print(f"  [Process:{event_id}] Found parent channel: '{parent_channel.name}'.")
            
            # Format the thread name correctly with a human-readable date
            event_time = event['event_time']
            event_time_str = event_time.strftime('%d-%m-%Y %H:%M') + f" {event_time.tzname()}"
            thread_name = f"{event['title']} - {event_time_str}"
            
            print(f"  [Process:{event_id}] Attempting to create a private thread with name '{thread_name}'...")
            # --- FIX: Create a private thread in the channel instead of from a message ---
            discussion_thread = await parent_channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.private_thread
            )
            print(f"  [Process:{event_id}] SUCCESS: Discord API returned a thread object. ID: {discussion_thread.id}")

            # Get accepted users
            signups = await self.db.get_signups_for_event(event_id)
            accepted_user_ids = [s['user_id'] for s in signups if s['rsvp_status'] == RsvpStatus.ACCEPTED]
            
            # --- FIX: Add accepted members to the private thread ---
            print(f"  [Process:{event_id}] Adding {len(accepted_user_ids)} members to the private thread...")
            for user_id in accepted_user_ids:
                try:
                    # Fetch member object to add them
                    member = await parent_channel.guild.fetch_member(user_id)
                    if member:
                        await discussion_thread.add_user(member)
                except discord.NotFound:
                    print(f"    - Could not find member with ID {user_id} to add to thread.")
                except Exception as e:
                    print(f"    - Error adding member {user_id} to thread: {e}")
            print(f"  [Process:{event_id}] Finished adding members.")

            # Create the embed and welcome message
            event_embed = await create_event_embed(self.bot, event_id, self.db)
            welcome_message = ""
            if accepted_user_ids:
                mentions = ' '.join([f'<@{user_id}>' for user_id in accepted_user_ids])
                welcome_message = f"Welcome, attendees! {mentions}"
            
            print(f"  [Process:{event_id}] Sending combined welcome message and embed to new thread...")
            await discussion_thread.send(content=welcome_message, embed=event_embed)
            print(f"  [Process:{event_id}] Welcome message and embed sent.")

            print(f"  [Process:{event_id}] Attempting to mark event as created in DB...")
            await self.db.mark_thread_created(event_id, discussion_thread.id)
            print(f"  [Process:{event_id}] SUCCESS: Event marked as created in DB.")

        except discord.Forbidden:
            # --- FIX: Update permission error message ---
            print(f"  [Process:{event_id}] FAILED: PERMISSION ERROR. The bot is likely missing 'Create Private Threads' permission. The event will be re-attempted later.")
        except Exception as e:
            print(f"  [Process:{event_id}] FAILED: An unexpected error occurred. The event will be re-attempted later.")
            traceback.print_exc()

    @tasks.loop(minutes=5)
    async def recreate_recurring_events(self):
        """Periodically checks for recurring events that need to be recreated."""
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
        
        while next_occurrence <= now:
            if rule == 'daily':
                next_occurrence += relativedelta(days=1)
            elif rule == 'weekly':
                next_occurrence += relativedelta(weeks=1)
            elif rule == 'monthly':
                next_occurrence += relativedelta(months=1)
            else:
                return None
        return next_occurrence

    async def process_event_recreation(self, parent_event: dict, create_embed_func, persistent_view_class):
        """Creates the next occurrence of a recurring event."""
        # FIX: Add a cooldown to prevent rapid, duplicate recreations.
        # If the event was already recreated in the last 6 hours, skip it.
        if parent_event['last_recreated_at'] and parent_event['last_recreated_at'] > (datetime.datetime.now(pytz.utc) - datetime.timedelta(hours=6)):
            return

        next_start_time = self.calculate_next_occurrence(parent_event['event_time'], parent_event['recurrence_rule'])
        if not next_start_time: return

        # Check against the user-defined recreation window
        recreation_window = next_start_time - datetime.timedelta(hours=parent_event.get('recreation_hours', 24))
        if datetime.datetime.now(next_start_time.tzinfo) < recreation_window:
            return # It's not time to recreate this event yet.

        print(f"Recreating event for parent ID {parent_event['event_id']}. Next occurrence: {next_start_time}")
        
        child_data = dict(parent_event)
        duration = parent_event['end_time'] - parent_event['event_time']
        child_data['event_time'] = next_start_time
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
            
            await self.db.update_last_recreated_at(parent_event['event_id'])
            print(f"Successfully recreated event. New child event ID: {child_id}")
            
        except Exception as e:
            print(f"Failed to process recreation for parent event {parent_event['event_id']}: {e}")
            traceback.print_exc()

    @tasks.loop(time=datetime.time(hour=0, minute=5, tzinfo=pytz.utc))
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

    
    @tasks.loop(minutes=1)
    async def cleanup_finished_events(self):
        """Runs once daily to delete old, non-recurring events and their threads."""
        print("Running daily cleanup of old events...")
        try:
            events_to_delete = await self.db.get_finished_events_for_cleanup()
            for event in events_to_delete:
                if event.get('message_id') and event.get('channel_id'):
                    try:
                        channel = self.bot.get_channel(event['channel_id']) or await self.bot.fetch_channel(event['channel_id'])
                        message = await channel.fetch_message(event['message_id'])
                        await message.delete()
                    except discord.NotFound:
                        pass # It's okay if it's already gone
                    except Exception as e:
                        print(f"Could not delete event message for event {event['event_id']}: {e}")

                if event.get('thread_id'):
                    try:
                        thread = self.bot.get_channel(event['thread_id']) or await self.bot.fetch_channel(event['thread_id'])
                        await thread.delete()
                    except discord.NotFound:
                        pass
                    except Exception as e:
                        print(f"Could not delete thread for event {event['event_id']}: {e}")

                await self.db.soft_delete_event(event['event_id'])
            
            if len(events_to_delete) > 0:
                print(f"Daily cleanup finished. Removed {len(events_to_delete)} old events.")
        except Exception as e:
            print(f"Error in cleanup_finished_events loop: {e}")
            traceback.print_exc()

    # --- ADDITION: Add the before_loop waiter for the new task ---
    @process_tentatives.before_loop
    @sync_event_threads.before_loop
    @create_event_threads.before_loop
    @recreate_recurring_events.before_loop
    @cleanup_finished_events.before_loop
    @purge_deleted_events.before_loop
    async def before_tasks(self):
        """Waits until the bot is fully logged in and ready before starting loops."""
        print("[Scheduler Tasks] Waiting for bot to be ready...")
        await self.bot.wait_until_ready()
        print("[Scheduler Tasks] Bot is ready. Loops will now start.")

async def setup(bot: commands.Bot):
    """Sets up the scheduler cog."""
    await bot.add_cog(Scheduler(bot, bot.db))
