import discord
from discord.ext import commands
import os
import asyncio
from dotenv import load_dotenv

from utils.database import Database

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
        
        # List of cogs to load
        cogs_to_load = [
            'cogs.event_management',
            'cogs.scheduler',
            'cogs.squad_builder',
            # We don't need the 'setup' cog anymore as those commands
            # are now correctly placed within event_management.py
        ]

        # Load each cog
        for cog_path in cogs_to_load:
            try:
                # The full path to the cog module
                full_cog_path = f'bot.{cog_path}'
                await self.load_extension(full_cog_path)
                print(f"Successfully loaded cog: {full_cog_path}")
            except Exception as e:
                print(f"Failed to load cog {full_cog_path}: {e}")
                traceback.print_exc()
        
        # Sync commands to a specific guild if GUILD_ID is set
        guild_id = os.getenv("GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            print(f"Synced {len(synced)} command(s) to guild {guild_id}.")
        else:
            # Sync commands globally if no GUILD_ID is set
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
