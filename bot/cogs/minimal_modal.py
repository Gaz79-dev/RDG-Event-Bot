import discord
from discord.ext import commands
from discord import app_commands, ui

class SecondModal(ui.Modal, title="Second Step"):
    answer = ui.TextInput(label="What's your favourite color?")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"Your favorite color: {self.answer.value}", ephemeral=True)

class FirstModal(ui.Modal, title="First Step"):
    name = ui.TextInput(label="What's your name?")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SecondModal())

class MinimalModal(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="modaltest", description="Test modals.")
    async def modaltest(self, interaction: discord.Interaction):
        await interaction.response.send_modal(FirstModal())

async def setup(bot):
    await bot.add_cog(MinimalModal(bot))
