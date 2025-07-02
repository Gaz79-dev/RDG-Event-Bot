import discord
from discord.ext import commands
from discord import app_commands
import os

# Set Guild ID
GUILD_ID = os.getenv("GUILD_ID")
if not GUILD_ID: raise ValueError("GUILD_ID not set in the environment, which is required for setup commands.")

# --- FIX: Define the Group at the module level ---
setup_group = app_commands.Group(name="setup", description="Commands for setting up the bot.")
squad_config_group = app_commands.Group(name="squad_config", description="Commands for configuring squad roles.", parent=setup_group)
restricted_role_group = app_commands.Group(name="restricted_role", description="Commands for configuring core restricted roles.", parent=setup_group)

# --- FIX: Define the commands as standalone functions ---
@squad_config_group.command(name="attack_role", description="Set the role for Attack specialty.")
async def set_attack_role(interaction: discord.Interaction, role: discord.Role):
    db = interaction.client.db
    await db.set_squad_config_role(interaction.guild.id, "attack", role.id)
    await interaction.response.send_message(f"Attack specialty role set to {role.mention}.", ephemeral=True)

@squad_config_group.command(name="defence_role", description="Set the role for Defence specialty.")
async def set_defence_role(interaction: discord.Interaction, role: discord.Role):
    db = interaction.client.db
    await db.set_squad_config_role(interaction.guild.id, "defence", role.id)
    await interaction.response.send_message(f"Defence specialty role set to {role.mention}.", ephemeral=True)

@squad_config_group.command(name="arty_role", description="Set the role for Arty Certified players.")
async def set_arty_role(interaction: discord.Interaction, role: discord.Role):
    db = interaction.client.db
    await db.set_squad_config_role(interaction.guild.id, "arty", role.id)
    await interaction.response.send_message(f"Arty specialty role set to {role.mention}.", ephemeral=True)

@squad_config_group.command(name="armour_role", description="Set the role for Armour specialty players.")
async def set_armour_role(interaction: discord.Interaction, role: discord.Role):
    db = interaction.client.db
    await db.set_squad_config_role(interaction.guild.id, "armour", role.id)
    await interaction.response.send_message(f"Armour specialty role set to {role.mention}.", ephemeral=True)

@squad_config_group.command(name="pathfinder_role", description="Set the role for Pathfinder specialty.")
async def set_pathfinder_role(interaction: discord.Interaction, role: discord.Role):
    db = interaction.client.db
    await db.set_squad_config_role(interaction.guild.id, "pathfinder", role.id)
    await interaction.response.send_message(f"Pathfinder specialty role set to {role.mention}.", ephemeral=True)

@restricted_role_group.command(name="commander", description="Set the role required for the Commander role.")
async def set_commander_role(interaction: discord.Interaction, role: discord.Role):
    db = interaction.client.db
    await db.set_squad_config_role(interaction.guild.id, "commander", role.id)
    await interaction.response.send_message(f"Restricted Commander role set to {role.mention}.", ephemeral=True)

@restricted_role_group.command(name="officer", description="Set the role required for the Officer subclass.")
async def set_officer_role(interaction: discord.Interaction, role: discord.Role):
    db = interaction.client.db
    await db.set_squad_config_role(interaction.guild.id, "officer", role.id)
    await interaction.response.send_message(f"Restricted Officer role set to {role.mention}.", ephemeral=True)

@restricted_role_group.command(name="recon", description="Set the role required for the Recon role.")
async def set_recon_role(interaction: discord.Interaction, role: discord.Role):
    db = interaction.client.db
    await db.set_squad_config_role(interaction.guild.id, "recon", role.id)
    await interaction.response.send_message(f"Restricted Recon role set to {role.mention}.", ephemeral=True)

@restricted_role_group.command(name="tank_commander", description="Set the role required for the Tank Commander subclass.")
async def set_tank_commander_role(interaction: discord.Interaction, role: discord.Role):
    db = interaction.client.db
    await db.set_squad_config_role(interaction.guild.id, "tank_commander", role.id)
    await interaction.response.send_message(f"Restricted Tank Commander role set to {role.mention}.", ephemeral=True)

@setup_group.command(name="thread_hours", description="Set hours before an event to open its discussion thread.")
@app_commands.describe(hours="e.g., 24 for one day")
async def set_thread_hours(interaction: discord.Interaction, hours: int):
    if not 1 <= hours <= 336: # 2 weeks
        return await interaction.response.send_message("Hours must be between 1 and 336.", ephemeral=True)
    
    db = interaction.client.db
    await db.set_thread_creation_hours(interaction.guild.id, hours)
    await interaction.response.send_message(f"Event discussion threads will now be created {hours} hours before an event starts.", ephemeral=True)

# --- FIX: The Cog class is now only for state if needed, but here it's not, so we just need a setup function ---
class SetupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

# --- FIX: The setup function now registers both the Cog and the command group ---
async def setup(bot: commands.Bot):
    # We still add the cog in case we want to add state or listeners to it later
    await bot.add_cog(SetupCog(bot))
    # Explicitly add the command group to the bot's tree
    bot.tree.add_command(setup_group)
