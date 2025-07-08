import discord
from discord.ext import commands
from discord import app_commands
import os

GUILD_ID = os.getenv("GUILD_ID")
if not GUILD_ID: raise ValueError("GUILD_ID not set in the environment, which is required for setup commands.")

# Define the Group and tie it to your specific guild
setup_group = app_commands.Group(name="setup", description="Commands for setting up the bot.", guild_ids=[int(GUILD_ID)])

@setup_group.command(name="thread_hours", description="Set hours before an event to open its discussion thread.")
@app_commands.describe(hours="e.g., 24 for one day")
async def set_thread_hours(interaction: discord.Interaction, hours: int):
    if not 1 <= hours <= 336: # 2 weeks
        return await interaction.response.send_message("Hours must be between 1 and 336.", ephemeral=True)
    
    db = interaction.client.db
    await db.set_thread_creation_hours(interaction.guild.id, hours)
    await interaction.response.send_message(f"Event discussion threads will now be created {hours} hours before an event starts.", ephemeral=True)

# --- ADDITION: Temporary command to force-clear the command cache ---
@app_commands.command(name="dev_clear_commands", description="[ADMIN] Forcibly clear and re-sync all commands for this server.")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
async def dev_clear_commands(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        # Clear and then sync commands for the specific guild where the command was used
        interaction.client.tree.clear_commands(guild=interaction.guild)
        await interaction.client.tree.sync(guild=interaction.guild)
        await interaction.followup.send("Commands have been cleared and re-synced for this server. It may take a minute for the changes to appear.")
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}")
# --- END ADDITION ---

class SetupCog(commands.Cog):
    """A cog for containing setup commands."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

async def setup(bot: commands.Bot):
    """The setup function to add the cog and its commands."""
    await bot.add_cog(SetupCog(bot))
    bot.tree.add_command(setup_group)
    # --- ADDITION: Register the new temporary command ---
    bot.tree.add_command(dev_clear_commands, guild=discord.Object(id=GUILD_ID))
