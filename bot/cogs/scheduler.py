import discord
from discord.ext import tasks, commands
import datetime
import pytz
import traceback
from dateutil.relativedelta import relativedelta

# Use relative import to go up one level to the 'bot' package root
from ..utils.database import Database, RsvpStatus
from .event_management import create_event_embed, PersistentEventView

class Scheduler(commands.Cog):
    """Cog for handling scheduled background tasks."""
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        print("[Scheduler Cog] Initialized. Starting tasks...")
        self.check_event_messages.start()
        self.create_event_threads.start()
        self.recreate_recurring_events.start()
        self.cleanup_finished_events.start()
        self.purge_deleted_events.start()
        self.sync_event_threads.start()
        self.process_tentatives.start()

    def cog_unload(self):
        """Cleanly cancels all tasks when the cog is unloaded."""
        self.check_event_messages.cancel()
        self.create_event_threads.cancel()
        self.recreate_recurring_events.cancel()
        self.cleanup_finished_events.cancel()
        self.purge_deleted_events.cancel()
        self.sync_event_threads.cancel()
        self.process_tentatives.cancel()

    @tasks.loop(minutes=3)
    async def check_event_messages(self):
        """
        Periodically checks if the message for an active event still exists.
        If not, it re-posts it. This acts as a self-healing mechanism.
        """
        print("\n[Scheduler] Running check_event_messages loop...")
        try:
            active_events = await self.db.get_active_events_with_message_id()
            if not active_events:
                print("[Scheduler] No active events with messages to check.")
                return

            print(f"[Scheduler] Checking {len(active_events)} active event message(s)...")
            for event in active_events:
                try:
                    channel = self.bot.get_channel(event['channel_id']) or await self.bot.fetch_channel(event['channel_id'])
                    await channel.fetch_message(event['message_id'])
                except discord.NotFound:
                    print(f"  [Self-Heal] Message for event {event['event_id']} ('{event['title']}') not found. Re-posting...")
                    try:
                        embed = await create_event_embed(self.bot, event['event_id'], self.db)
                        view = PersistentEventView(self.db)
                        content = " ".join([f"<@&{rid}>" for rid in event.get('mention_role_ids', [])])
                        
                        new_message = await channel.send(content=content, embed=embed, view=view)
                        await self.db.update_event_message_id(event['event_id'], new_message.id)
                        print(f"  [Self-Heal] Successfully re-posted message for event {event['event_id']}.")
                    except Exception as post_error:
                        print(f"  [Self-Heal] FAILED to re-post message for event {event['event_id']}: {post_error}")
                except Exception as e:
                    print(f"  [Self-Heal] Error checking message for event {event['event_id']}: {e}")
        except Exception as e:
            print(f"[Scheduler] FATAL ERROR in check_event_messages loop: {e}")
            traceback.print_exc()
    
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
                await self.db.set_rsvp(signup['event_id'], signup['user_id'], RsvpStatus.DECLINED)
                print(f"  [ProcessTentative] Converted User {signup['user_id']} to Declined for Event {signup['event_id']}.")
            
            print(f"[Scheduler] Processed {len(tentative_signups)} tentative signups.")
        except Exception as e:
            print(f"[Scheduler] FATAL ERROR in process_tentatives loop: {e}")
            traceback.print_exc()
    
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

                signups = await self.db.get_signups_for_event(event['event_id'])
                accepted_user_ids = {s['user_id'] for s in signups if s['rsvp_status'] == RsvpStatus.ACCEPTED}

                thread_member_ids = {member.id for member in await thread.fetch_members()}

                users_to_add = accepted_user_ids - thread_member_ids
                users_to_remove = thread_member_ids - accepted_user_ids

                for user_id in users_to_add:
                    try:
                        member = await guild.fetch_member(user_id)
                        await thread.add_user(member)
                        print(f"  [Sync:{event['event_id']}] Added {member.display_name} to thread.")
                    except Exception as e:
                        print(f"  [Sync:{event['event_id']}] FAILED to add member {user_id}: {e}")
                
                for user_id in users_to_remove:
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
            
            # --- START: Updated Naming Convention ---
            event_time = event['event_time']
            # Format the date as "Mon Day" (e.g., Aug 09)
            date_str = event_time.strftime('%b %d')
            thread_name = f"{event['title']} - {date_str}"
            # --- END: Updated Naming Convention ---
            
            print(f"  [Process:{event_id}] Attempting to create a private thread with name '{thread_name}'...")
            discussion_thread = await parent_channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.private_thread
            )
            print(f"  [Process:{event_id}] SUCCESS: Discord API returned a thread object. ID: {discussion_thread.id}")

            signups = await self.db.get_signups_for_event(event_id)
            accepted_user_ids = [s['user_id'] for s in signups if s['rsvp_status'] == RsvpStatus.ACCEPTED]
            
            print(f"  [Process:{event_id}] Adding {len(accepted_user_ids)} members to the private thread...")
            for user_id in accepted_user_ids:
                try:
                    member = await parent_channel.guild.fetch_member(user_id)
                    if member:
                        await discussion_thread.add_user(member)
                except discord.NotFound:
                    print(f"    - Could not find member with ID {user_id} to add to thread.")
                except Exception as e:
                    print(f"    - Error adding member {user_id} to thread: {e}")
            print(f"  [Process:{event_id}] Finished adding members.")

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
            print(f"  [Process:{event_id}] FAILED: PERMISSION ERROR. The bot is likely missing 'Create Private Threads' permission. The event will be re-attempted later.")
        except Exception as e:
            print(f"  [Process:{event_id}] FAILED: An unexpected error occurred. The event will be re-attempted later.")
            traceback.print_exc()

    @tasks.loop(minutes=5)
    async def recreate_recurring_events(self):
        """Checks if a recurring event's last occurrence has finished and creates the next one."""
        print("\n[Scheduler] Running recreate_recurring_events loop...")
        try:
            parent_events = await self.db.get_events_for_recreation()
            for parent_event in parent_events:
                await self.process_event_recreation(parent_event)
        except Exception as e:
            print(f"Error in recreate_recurring_events loop: {e}")
            traceback.print_exc()

    def calculate_next_occurrence(self, basis_time: datetime.datetime, rule: str) -> datetime.datetime:
        """Calculates the next occurrence strictly based on the previous time and rule."""
        if rule == 'daily':
            return basis_time + relativedelta(days=1)
        elif rule == 'weekly':
            return basis_time + relativedelta(weeks=1)
        elif rule == 'monthly':
            return basis_time + relativedelta(months=1)
        return None

    async def process_event_recreation(self, parent_event: dict):
        """Creates the next occurrence of a recurring event if the last one is finished."""
        now = datetime.datetime.now(pytz.utc)
        latest_child = await self.db.get_latest_child_event(parent_event['event_id'])

        # This logic handles the very first occurrence after the parent is made
        if not latest_child:
            # Check if it's within the creation window based on the parent's time
            recreation_window = parent_event['event_time'] - datetime.timedelta(hours=parent_event.get('recreation_hours', 168))
            if now < recreation_window:
                return
        else:
            # For all subsequent occurrences, check if the latest child has finished
            if latest_child['end_time'] > now:
                return

        print(f"Recreating event for parent ID {parent_event['event_id']}.")
        
        basis_time = latest_child['event_time'] if latest_child else parent_event['event_time']
        next_start_time = self.calculate_next_occurrence(basis_time, parent_event['recurrence_rule'])
        if not next_start_time: return
        
        child_data = dict(parent_event)
        duration = parent_event['end_time'] - parent_event['event_time']
        child_data['event_time'] = next_start_time
        child_data['end_time'] = next_start_time + duration
        child_data['is_recurring'] = False
        child_data['parent_event_id'] = parent_event['event_id']
        
        # --- START OF FIX ---
        # 1. Determine the correct channel ID. Use the latest child's channel if it exists,
        #    otherwise fall back to the parent's default. This handles cases where events were moved.
        target_channel_id = latest_child['channel_id'] if latest_child else parent_event['channel_id']
        
        # 2. Explicitly overwrite the channel ID in the data payload to ensure the new
        #    database record is correct, overriding any stale ID copied from the parent.
        child_data['channel_id'] = target_channel_id
        # --- END OF FIX ---
        
        try:
            # 3. Use the corrected `target_channel_id` when creating the new event record.
            child_id = await self.db.create_event(
                parent_event['guild_id'], target_channel_id, parent_event['creator_id'], child_data
            )
            
            # 4. Use the corrected `target_channel_id` to fetch the channel for posting.
            target_channel = self.bot.get_channel(target_channel_id) or await self.bot.fetch_channel(target_channel_id)
            
            embed = await create_event_embed(self.bot, child_id, self.db)
            view = PersistentEventView(self.db)
            content = " ".join([f"<@&{rid}>" for rid in parent_event.get('mention_role_ids', [])])
            
            msg = await target_channel.send(content=content, embed=embed, view=view)
            await self.db.update_event_message_id(child_id, msg.id)
            await self.db.update_last_recreated_at(parent_event['event_id'])
            print(f"Successfully created new recurring child event. New child ID: {child_id}")
            
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
        """Finds finished events and PERMANENTLY deletes their messages, threads and DB records."""
        print("Running cleanup of old events...")
        try:
            events_to_delete = await self.db.get_finished_events_for_cleanup()
            for event in events_to_delete:
                print(f"Cleaning up finished event ID: {event['event_id']}")
                # Delete Discord assets first
                if event.get('message_id') and event.get('channel_id'):
                    try:
                        channel = self.bot.get_channel(event['channel_id']) or await self.bot.fetch_channel(event['channel_id'])
                        message = await channel.fetch_message(event['message_id'])
                        await message.delete()
                    except discord.NotFound: pass
                    except Exception as e: print(f"Could not delete event message for event {event['event_id']}: {e}")

                if event.get('thread_id'):
                    try:
                        thread = self.bot.get_channel(event['thread_id']) or await self.bot.fetch_channel(event['thread_id'])
                        await thread.delete()
                    except discord.NotFound: pass
                    except Exception as e: print(f"Could not delete thread for event {event['event_id']}: {e}")

                # Hard delete the event from the database, which will cascade to signups and squads
                await self.db.delete_event(event['event_id'])
            
            if len(events_to_delete) > 0:
                print(f"Cleanup finished. Permanently removed {len(events_to_delete)} old events.")
        except Exception as e:
            print(f"Error in cleanup_finished_events loop: {e}")
            traceback.print_exc()

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
