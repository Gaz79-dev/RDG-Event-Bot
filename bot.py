import discord
from discord.ext import commands
import os
import asyncio
from dotenv import load_dotenv

# Adjust the import path based on your project structure
from utils.database import Database
from cogs.event_management import setup as event_management_setup
from cogs.scheduler import setup as scheduler_setup # Import the scheduler setup

# Load environment variables from a .env file
load_dotenv()

class EventBot(commands.Bot):
    """Custom Bot class to hold the database connection."""
    def __init__(self, db: Database, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = db

    async def setup_hook(self):
        """The setup_hook is called when the bot logs in and is ready."""
        print("Running setup hook...")
        await event_management_setup(self, self.db)
        print("Event management cog loaded.")
        
        await scheduler_setup(self, self.db) # Load the scheduler cog
        print("Scheduler cog loaded.")
        
        # This is important for syncing app commands to Discord.
        # It can take up to an hour for global commands to sync.
        await self.tree.sync()
        print("Command tree synced.")


async def main():
    """Main function to initialize and run the bot."""
    
    # --- Database Connection ---
    db = Database()
    await db.connect()
    
    # --- Bot Intents ---
    # Intents define which events the bot will receive from Discord.
    # We need members and message_content intents for some functionality.
    # Make sure to enable these in your Discord Developer Portal.
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True
    
    # --- Initialize and Run Bot ---
    bot = EventBot(db=db, command_prefix="!", intents=intents)

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("Error: DISCORD_TOKEN not found in .env file. Please check your configuration.")
        return
        
    try:
        print("Bot is starting...")
        await bot.start(token)
    except KeyboardInterrupt:
        print("Bot shutting down via KeyboardInterrupt...")
    finally:
        print("Closing database connection...")
        await db.close()
        print("Closing bot session...")
        await bot.close()
        print("Cleanup complete.")


if __name__ == "__main__":
    # This ensures the bot runs within an asyncio event loop.
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Program interrupted by user.")

