import discord
from discord.ext import commands
from discord import app_commands, ui
import asyncio
from typing import List, Dict, Optional, Tuple
import traceback
from collections import defaultdict

# Adjust the import path based on your project structure
from utils.database import Database, RsvpStatus, ROLES, SUBCLASSES
# We will need to import this from event_management to update the public embed
from .event_management import create_event_embed

# --- Helper ---
def get_squad_letter(count: int) -> str:
    """Converts a number to a letter (0=A, 1=B, etc.)."""
    if count < 26:
        return chr(ord('A') + count)
    return f"Z{count - 25}"

# --- Modals for User Input ---
class SquadBuilderModal(ui.Modal, title="Build Squads"):
    """The pop-up form for specifying squad composition."""
    infantry_squad_size = ui.TextInput(label="Max Infantry Squad Size", placeholder="e.g., 6", required=True, default="6")
    attack_squads = ui.TextInput(label="Number of Attack Squads", placeholder="e.g., 2", required=True, default="0")
    defence_squads = ui.TextInput(label="Number of Defence Squads", placeholder="e.g., 2", required=True, default="0")
    flex_squads = ui.TextInput(label="Number of Flex Squads", placeholder="e.g., 1", required=True, default="0")
    armour_squads = ui.TextInput(label="Number of Armour Squads", placeholder="e.g., 2", required=True, default="0")
    recon_squads = ui.TextInput(label="Number of Recon Squads", placeholder="e.g., 2", required=True, default="0")
    arty_squads = ui.TextInput(label="Number of Arty Squads", placeholder="e.g., 1", required=True, default="0")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            self.infantry_squad_size_val = int(self.infantry_squad_size.value)
            self.attack_squads_val = int(self.attack_squads.value)
            self.defence_squads_val = int(self.defence_squads.value)
            self.flex_squads_val = int(self.flex_squads.value)
            self.armour_squads_val = int(self.armour_squads.value)
            self.recon_squads_val = int(self.recon_squads.value)
            self.arty_squads_val = int(self.arty_squads.value)
        except ValueError:
            await interaction.response.send_message("All squad counts must be valid numbers.", ephemeral=True)
            self.stop()
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        self.stop()

# --- Interactive Workshop View ---
class WorkshopView(ui.View):
    def __init__(self, event_id: int, db: Database, bot: commands.Bot):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.db = db
        self.bot = bot

    async def refresh_embed(self, interaction: discord.Interaction):
        """Helper to refresh the workshop embed."""
        new_embed = await _generate_workshop_embed(interaction.guild, self.event_id, self.db)
        await interaction.message.edit(embed=new_embed, view=self)

    @ui.button(label="Refresh Roster", style=discord.ButtonStyle.primary, row=0)
    async def refresh_roster(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(thinking=True)
        # Add logic here to sync players
        await interaction.followup.send("Roster refreshed!", ephemeral=True)
        await self.refresh_embed(interaction)

    @ui.button(label="Move Player", style=discord.ButtonStyle.secondary, row=0)
    async def move_player(self, interaction: discord.Interaction, button: ui.Button):
        # Add logic to open a modal for moving players
        await interaction.response.send_message("Move player functionality not yet implemented.", ephemeral=True)

    @ui.button(label="Re-assign Role", style=discord.ButtonStyle.secondary, row=0)
    async def reassign_role(self, interaction: discord.Interaction, button: ui.Button):
        # Add logic to open a modal for re-assigning roles
        await interaction.response.send_message("Re-assign role functionality not yet implemented.", ephemeral=True)

    @ui.button(label="Add Squad", style=discord.ButtonStyle.green, row=1)
    async def add_squad(self, interaction: discord.Interaction, button: ui.Button):
        # Add logic to open a modal for adding a squad
        await interaction.response.send_message("Add squad functionality not yet implemented.", ephemeral=True)

    @ui.button(label="Delete Squad", style=discord.ButtonStyle.danger, row=1)
    async def delete_squad(self, interaction: discord.Interaction, button: ui.Button):
        # Add logic to open a modal for deleting a squad
        await interaction.response.send_message("Delete squad functionality not yet implemented.", ephemeral=True)
        
    @ui.button(label="Publish to Event Thread", style=discord.ButtonStyle.success, row=2)
    async def publish(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        event = await self.db.get_event_by_id(self.event_id)
        if not event or not event['thread_id']:
            await interaction.followup.send("This event does not have a discussion thread yet.", ephemeral=True)
            return
            
        thread = interaction.guild.get_thread(event['thread_id'])
        if not thread:
            await interaction.followup.send("Could not find the event discussion thread.", ephemeral=True)
            return

        final_embed = await _generate_workshop_embed(interaction.guild, self.event_id, self.db)
        final_embed.title = f"Final Team Sheet for: {event['title']}"
        final_embed.description = "The teams have been set. Good luck!"
        final_embed.color = discord.Color.green()

        await thread.send(embed=final_embed)
        await interaction.followup.send("Final team sheet has been published to the event thread!", ephemeral=True)

# --- Main Cog ---
class SquadBuilder(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db

    squads_group = app_commands.Group(name="squads", description="Commands for building and managing squads.")

    @squads_group.command(name="build", description="Build the team composition for an event.")
    @app_commands.describe(event_id="The ID of the event to build squads for.")
    async def build(self, interaction: discord.Interaction, event_id: int):
        if not interaction.user.guild_permissions.administrator:
             await interaction.response.send_message("You need to be an administrator to use this command.", ephemeral=True)
             return

        event = await self.db.get_event_by_id(event_id)
        if not event:
            await interaction.response.send_message(f"Event with ID {event_id} not found.", ephemeral=True)
            return

        modal = SquadBuilderModal()
        await interaction.response.send_modal(modal)
        await modal.wait()

        if modal.is_stopped() and hasattr(modal, 'infantry_squad_size_val'):
            await modal.interaction.followup.send("Building squads based on your input...", ephemeral=True, thinking=True)
            try:
                await self._run_automated_draft(interaction, event_id, modal)
                
                workshop_embed = await _generate_workshop_embed(interaction.guild, event_id, self.db)
                workshop_view = WorkshopView(event_id, self.db, self.bot)
                
                await interaction.channel.send(embed=workshop_embed, view=workshop_view)
                await modal.interaction.followup.send("Squad builder initiated! The workshop has been posted in this channel.", ephemeral=True)

            except Exception as e:
                print(f"Error during squad build process: {e}")
                traceback.print_exc()
                await modal.interaction.followup.send(f"An error occurred while building the squads: {e}", ephemeral=True)

    async def _get_player_pools(self, guild: discord.Guild, signups: List[Dict]) -> Dict[str, Dict[str, List[Dict]]]:
        squad_roles = await self.db.get_squad_config_roles(guild.id)
        player_pools = defaultdict(lambda: defaultdict(list))
        
        for signup in signups:
            if signup['rsvp_status'] != RsvpStatus.ACCEPTED:
                continue
            
            member = guild.get_member(signup['user_id'])
            if not member: continue

            user_role_ids = {r.id for r in member.roles}
            player_info = {**signup, 'member': member}
            role = player_info['role_name']
            subclass = player_info['subclass_name']

            if role == 'Commander':
                player_pools['commander'][role].append(player_info)
            elif role == 'Recon':
                player_pools['recon'][subclass].append(player_info)
            elif role == 'Armour' and squad_roles.get('squad_armour_role_id') in user_role_ids:
                player_pools['armour'][subclass].append(player_info)
            elif role == 'Infantry':
                if squad_roles.get('squad_arty_role_id') in user_role_ids and subclass == 'Officer':
                    player_pools['arty'][subclass].append(player_info)
                elif squad_roles.get('squad_attack_role_id') in user_role_ids and squad_roles.get('squad_defence_role_id') in user_role_ids:
                    player_pools['flex'][subclass].append(player_info)
                elif squad_roles.get('squad_attack_role_id') in user_role_ids:
                    player_pools['attack'][subclass].append(player_info)
                elif squad_roles.get('squad_defence_role_id') in user_role_ids:
                    player_pools['defence'][subclass].append(player_info)
                else:
                    player_pools['general'][subclass].append(player_info)
        
        return player_pools

    async def _run_automated_draft(self, interaction: discord.Interaction, event_id: int, modal: SquadBuilderModal):
        await self.db.delete_squads_for_event(event_id)
        signups = await self.db.get_signups_for_event(event_id)
        pools = await self._get_player_pools(interaction.guild, signups)
        
        reserves = []

        # 1. Commander
        squad_id = await self.db.create_squad(event_id, "Command", "Command")
        if pools['commander']['Commander']:
            await self.db.add_squad_member(squad_id, pools['commander']['Commander'].pop(0)['user_id'], "Commander")
        reserves.extend(p['user_id'] for p in pools['commander']['Commander'])

        # 2. Arty
        for i in range(modal.arty_squads_val):
            squad_id = await self.db.create_squad(event_id, f"Arty {get_squad_letter(i)}", "Arty")
            if pools['arty']['Officer']:
                await self.db.add_squad_member(squad_id, pools['arty']['Officer'].pop(0)['user_id'], "Officer")

        # 3. Recon
        for i in range(modal.recon_squads_val):
            squad_id = await self.db.create_squad(event_id, f"Recon {get_squad_letter(i)}", "Recon")
            if pools['recon']['Spotter']: await self.db.add_squad_member(squad_id, pools['recon']['Spotter'].pop(0)['user_id'], "Spotter")
            if pools['recon']['Sniper']: await self.db.add_squad_member(squad_id, pools['recon']['Sniper'].pop(0)['user_id'], "Sniper")

        # 4. Armour
        for i in range(modal.armour_squads_val):
            squad_id = await self.db.create_squad(event_id, f"Armour {get_squad_letter(i)}", "Armour")
            if pools['armour']['Tank Commander']: await self.db.add_squad_member(squad_id, pools['armour']['Tank Commander'].pop(0)['user_id'], "Tank Commander")
            for _ in range(2):
                if pools['armour']['Crewman']: await self.db.add_squad_member(squad_id, pools['armour']['Crewman'].pop(0)['user_id'], "Crewman")

        # 5. Infantry
        inf_pools = {'Attack': modal.attack_squads_val, 'Defence': modal.defence_squads_val, 'Flex': modal.flex_squads_val}
        inf_player_map = {'Attack': ['attack', 'flex', 'general'], 'Defence': ['defence', 'flex', 'general'], 'Flex': ['flex', 'attack', 'defence', 'general']}
        
        for squad_type, count in inf_pools.items():
            for i in range(count):
                squad_id = await self.db.create_squad(event_id, f"{squad_type} {get_squad_letter(i)}", squad_type)
                placed_officer = False
                # Find officer from appropriate pools
                for pool_name in inf_player_map[squad_type]:
                    if pools[pool_name]['Officer']:
                        await self.db.add_squad_member(squad_id, pools[pool_name]['Officer'].pop(0)['user_id'], "Officer")
                        placed_officer = True
                        break
                # Fill remaining slots
                if placed_officer:
                    # ... complex logic to fill remaining infantry slots based on class limits ...
                    pass

        # Add all remaining players to reserves
        for category in pools.values():
            for role_list in category.values():
                reserves.extend(p['user_id'] for p in role_list)
        
        if reserves:
            reserve_squad_id = await self.db.create_squad(event_id, "Reserves", "Reserves")
            for user_id in reserves:
                # Find original role from signup to display
                signup = next((s for s in signups if s['user_id'] == user_id), None)
                role_display = signup['subclass_name'] if signup and signup['subclass_name'] else signup['role_name']
                await self.db.add_squad_member(reserve_squad_id, user_id, role_display)

async def _generate_workshop_embed(guild: discord.Guild, event_id: int, db: Database) -> discord.Embed:
    event = await db.get_event_by_id(event_id)
    squads = await db.get_squads_for_event(event_id)
    
    embed = discord.Embed(
        title=f"🛠️ Squad Workshop for: {event['title']}",
        description="This is your private workshop to finalize the team.",
        color=discord.Color.gold()
    )

    for squad in squads:
        members = await db.get_squad_members(squad['squad_id'])
        member_list = []
        for member_data in members:
            member_obj = guild.get_member(member_data['user_id'])
            member_name = member_obj.display_name if member_obj else f"ID: {member_data['user_id']}"
            member_list.append(f"**{member_data['assigned_role_name']}:** {member_name}")
        
        value = "\n".join(member_list) or "Empty"
        embed.add_field(name=f"__**{squad['name']}**__", value=value, inline=False)
        
    embed.set_footer(text=f"Event ID: {event_id} | Use the buttons below to manage.")
    return embed

async def setup(bot: commands.Bot, db: Database):
    await bot.add_cog(SquadBuilder(bot, db))

