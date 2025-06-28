import discord
from discord.ext import commands
import os
import asyncio
from dotenv import load_dotenv

# Adjust the import path based on your project structure
from utils.database import Database
from cogs.event_management import setup as event_management_setup
from cogs.scheduler import setup as scheduler_setup
from cogs.squad_builder import setup as squad_builder_setup # Import the new squad builder setup

load_dotenv()

class EventBot(commands.Bot):
    """Custom Bot class to hold the database connection."""
    def __init__(self, db: Database, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = db

    async def setup_hook(self):
        """The setup_hook is called when the bot logs in."""
        print("Running setup hook...")
        await event_management_setup(self, self.db)
        print("Event management cog loaded.")
        
        await scheduler_setup(self, self.db)
        print("Scheduler cog loaded.")
        
        await squad_builder_setup(self, self.db) # Load the new squad builder cog
        print("Squad builder cog loaded.")
        
        # Sync commands
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} command(s)")
        except Exception as e:
            print(f"Failed to sync commands: {e}")


async def main():
    """Main function to run the bot."""
    
    db = Database()
    await db.connect()
    
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True
    
    bot = EventBot(db=db, command_prefix="!", intents=intents)

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("Error: DISCORD_TOKEN not found in .env file.")
        return
        
    try:
        print("Bot is starting...")
        await bot.start(token)
    except KeyboardInterrupt:
        print("Bot shutting down...")
    finally:
        await db.close()
        await bot.close()
        print("Cleanup complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Program interrupted.")
