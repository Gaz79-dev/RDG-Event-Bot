import discord
from discord.ext import commands
import os
import asyncio
import traceback  # --- FIX: Import the traceback module
from dotenv import load_dotenv

# We need to adjust the path for standalone execution
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from bot.utils.database import Database

# Load environment variables from .env file
load_dotenv()

class EventBot(commands.Bot):
    """A custom Bot class to hold the database connection."""
    def __init__(self, db: Database, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = db

    async def setup_hook(self):
        """The setup_hook is called when the bot logs in."""
        print("Bot setup hook running...")
        
        # --- FIX: Use correct dot-notation paths for load_extension ---
        cogs_to_load = [
            'bot.cogs.event_management',
            'bot.cogs.scheduler',
            'bot.cogs.squad_builder',
            'bot.cogs.setup'
        ]

        # Load each cog
        for cog_path in cogs_to_load:
            try:
                await self.load_extension(cog_path)
                print(f"Successfully loaded cog: {cog_path}")
            except Exception as e:
                print(f"Failed to load cog {cog_path}:")
                traceback.print_exc() # This will now work correctly
        
        # Sync commands
        guild_id = os.getenv("GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            print(f"Synced {len(synced)} command(s) to guild {guild_id}.")
        else:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} command(s) globally.")


async def main():
    """Main function to connect to the database and run the bot."""
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
        print("Bot cleanup complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Program interrupted by user.")
