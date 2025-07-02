import discord
from discord.ext import commands
import os
import asyncio
import traceback
from dotenv import load_dotenv

# --- FIX: The sys.path hack is removed. Imports are now relative to the project root. ---
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
        
        cogs_to_load = [
            'bot.cogs.event_management',
            'bot.cogs.scheduler',
            'bot.cogs.setup'
        ]

        # Load each cog
        for cog_path in cogs_to_load:
            try:
                await self.load_extension(cog_path)
                print(f"Successfully loaded cog: {cog_path}")
            except Exception as e:
                print(f"Failed to load cog {cog_path}:")
                traceback.print_exc()
        
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

    # --- START: New Global Command Check ---
    @bot.check
    async def global_role_check(interaction: discord.Interaction):
        # Load the configured role IDs from the .env file.
        allowed_role_ids = set()
        for i in range(1, 6): # Checks for ALLOWED_ROLE_ID_1 through 5
            role_id_str = os.getenv(f"ALLOWED_ROLE_ID_{i}")
            if role_id_str and role_id_str.isdigit():
                allowed_role_ids.add(int(role_id_str))

        # If no roles are configured in the .env file, allow everyone.
        if not allowed_role_ids:
            return True

        # Ensure the command is being run by a member in a server, not a user in a DM.
        if not isinstance(interaction.user, discord.Member):
            return False
            
        # Check if the user has any of the allowed roles.
        user_role_ids = {role.id for role in interaction.user.roles}
        if user_role_ids.intersection(allowed_role_ids):
            return True # User has at least one of the required roles.
        
        # If the check fails, send an ephemeral message and block the command.
        try:
            await interaction.response.send_message(
                "You do not have the required role to use bot commands.", 
                ephemeral=True,
                delete_after=15
            )
        except discord.InteractionResponded:
            # If the interaction was already responded to (e.g., a deferred modal), do nothing.
            pass
            
        return False
    # --- END: New Global Command Check ---

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
