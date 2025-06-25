import discord
from discord.ext import tasks, commands
import datetime
from utils.database import Database

class Scheduler(commands.Cog):
    """Cog for handling scheduled background tasks."""
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        self.create_event_threads.start()

    def cog_unload(self):
        """Cleanly cancels the task when the cog is unloaded."""
        self.create_event_threads.cancel()

    @tasks.loop(minutes=1)
    async def create_event_threads(self):
        """Periodically checks for events that need a discussion thread created."""
        try:
            events_to_process = await self.db.get_events_for_thread_creation()
            for event in events_to_process:
                guild = self.bot.get_guild(event['guild_id'])
                if not guild:
                    print(f"Scheduler: Could not find guild {event['guild_id']}. Skipping event {event['event_id']}.")
                    continue

                channel = guild.get_channel(event['channel_id'])
                if not channel:
                    print(f"Scheduler: Could not find channel {event['channel_id']} in guild {guild.id}. Skipping event {event['event_id']}.")
                    continue
                
                try:
                    # Fetch the original event message to create the thread on
                    message = await channel.fetch_message(event['message_id'])
                    thread = await message.create_thread(name=event['title'])
                    
                    # Update database to mark the thread as created
                    await self.db.update_event_thread_id(event['event_id'], thread.id)
                    
                    print(f"Created thread for event {event['event_id']} ('{event['title']}') in guild {guild.id}.")

                except discord.NotFound:
                    print(f"Scheduler: Could not find message {event['message_id']} for event {event['event_id']}. Marking as failed to prevent retries.")
                    # Mark as created to prevent the loop from constantly trying to fetch a deleted message
                    await self.db.mark_thread_as_created(event['event_id'])
                except discord.HTTPException as e:
                    print(f"Scheduler: HTTP error creating thread for event {event['event_id']}: {e}")

        except Exception as e:
            print(f"An error occurred in the create_event_threads loop: {e}")

    @create_event_threads.before_loop
    async def before_create_event_threads(self):
        """Waits until the bot is fully logged in and ready before starting the loop."""
        await self.bot.wait_until_ready()
        print("Scheduler loop is ready and starting.")


async def setup(bot: commands.Bot, db: Database):
    """Sets up the scheduler cog."""
    await bot.add_cog(Scheduler(bot, db))
