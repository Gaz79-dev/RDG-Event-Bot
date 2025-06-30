import discord
from discord.ext import commands
from discord import app_commands, ui
import asyncio
from typing import List, Dict, Optional, Tuple
import traceback
from collections import defaultdict

from ..utils.database import Database, RsvpStatus, ROLES, SUBCLASSES

# ... (Keep the get_squad_letter and SquadBuilderModal classes here) ...

# --- FIX: Define the Group at the module level ---
squads_group = app_commands.Group(name="squads", description="Commands for building and managing squads.")

# --- FIX: Define the command as a standalone function ---
@squads_group.command(name="build", description="Build the team composition for an event.")
@app_commands.describe(event_id="The ID of the event to build squads for.")
async def build_command(interaction: discord.Interaction, event_id: int):
    squad_builder_cog = interaction.client.get_cog("SquadBuilder")
    if not squad_builder_cog:
        return await interaction.response.send_message("SquadBuilder cog is not loaded.", ephemeral=True)

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("You need admin perms.", ephemeral=True)
    if not await squad_builder_cog.db.get_event_by_id(event_id):
        return await interaction.response.send_message(f"Event ID {event_id} not found.", ephemeral=True)
    
    await interaction.response.send_modal(SquadBuilderModal(squad_builder_cog, event_id))


# --- FIX: The Cog class now primarily holds state and helper methods ---
class SquadBuilder(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db

    # Helper methods are now part of the cog instance
    async def run_draft_and_post_workshop(self, i: discord.Interaction, event_id: int, modal: 'SquadBuilderModal') -> str:
        try:
            await self._run_automated_draft(i.guild, event_id, modal)
            workshop_embed = await self._generate_workshop_embed(i.guild, event_id)
            await i.channel.send(embed=workshop_embed)
            return "✅ Squads built and workshop posted."
        except Exception as e:
            print(f"!!! SQUAD BUILD ERROR !!!"), traceback.print_exc()
            return "An error occurred during the squad build process."

    async def _get_player_pools(self, guild: discord.Guild, signups: List[Dict]) -> Dict[str, Dict[str, List[Dict]]]:
        # ... implementation ...
        pass

    async def _run_automated_draft(self, guild: discord.Guild, event_id: int, modal: 'SquadBuilderModal'):
        # ... implementation ...
        pass
        
    async def _generate_workshop_embed(self, guild: discord.Guild, event_id: int) -> discord.Embed:
        # ... implementation from previous version ...
        # (Make sure to fix the syntax error from the last turn here if you haven't already)
        event, squads = await self.db.get_event_by_id(event_id), await self.db.get_squads_for_event(event_id)
        embed = discord.Embed(title=f"🛠️ Squad Workshop for: {event['title']}", color=discord.Color.gold())
        for squad in squads:
            members = await self.db.get_squad_members(squad['squad_id'])
            member_list = []
            for m in members:
                member_obj = guild.get_member(m['user_id'])
                name = member_obj.display_name if member_obj else f"ID: {m['user_id']}"
                member_list.append(f"**{m['assigned_role_name']}:** {name}")
            embed.add_field(name=f"__**{squad['name']}**__ ({squad['squad_type']})", value="\n".join(member_list) or "Empty", inline=True)
        embed.set_footer(text=f"Event ID: {event_id}")
        return embed

# --- FIX: The setup function now registers both the Cog and the command group ---
async def setup(bot: commands.Bot):
    db = bot.web_app.state.db
    await bot.add_cog(SquadBuilder(bot, db))
    bot.tree.add_command(squads_group)
