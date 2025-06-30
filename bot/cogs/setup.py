import discord
from discord.ext import commands
from discord import app_commands

# --- FIX: Define the Group at the module level ---
setup_group = app_commands.Group(name="setup", description="Commands for setting up the bot.", default_permissions=discord.Permissions(administrator=True))
squad_config_group = app_commands.Group(name="squad_config", description="Commands for configuring squad roles.", parent=setup_group)

# --- FIX: Define the commands as standalone functions ---
@squad_config_group.command(name="attack_role", description="Set the role for Attack specialty.")
async def set_attack_role(interaction: discord.Interaction, role: discord.Role):
    db = interaction.client.web_app.state.db
    await db.set_squad_config_role(interaction.guild.id, "attack", role.id)
    await interaction.response.send_message(f"Attack specialty role set to {role.mention}.", ephemeral=True)

@squad_config_group.command(name="defence_role", description="Set the role for Defence specialty.")
async def set_defence_role(interaction: discord.Interaction, role: discord.Role):
    db = interaction.client.web_app.state.db
    await db.set_squad_config_role(interaction.guild.id, "defence", role.id)
    await interaction.response.send_message(f"Defence specialty role set to {role.mention}.", ephemeral=True)

@squad_config_group.command(name="arty_role", description="Set the role for Arty Certified players.")
async def set_arty_role(interaction: discord.Interaction, role: discord.Role):
    db = interaction.client.web_app.state.db
    await db.set_squad_config_role(interaction.guild.id, "arty", role.id)
    await interaction.response.send_message(f"Arty specialty role set to {role.mention}.", ephemeral=True)

@squad_config_group.command(name="armour_role", description="Set the role for Armour specialty players.")
async def set_armour_role(interaction: discord.Interaction, role: discord.Role):
    db = interaction.client.web_app.state.db
    await db.set_squad_config_role(interaction.guild.id, "armour", role.id)
    await interaction.response.send_message(f"Armour specialty role set to {role.mention}.", ephemeral=True)

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
