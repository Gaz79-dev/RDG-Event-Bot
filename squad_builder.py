import discord
from discord.ext import commands
from discord import app_commands, ui
import asyncio
from typing import List, Dict, Optional, Tuple
import traceback
from collections import defaultdict

# Adjust the import path based on your project structure
from utils.database import Database, RsvpStatus, ROLES, SUBCLASSES
from cogs.event_management import create_event_embed

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

    def __init__(self, cog: 'SquadBuilder', event_id: int):
        super().__init__()
        self.cog = cog
        self.event_id = event_id

    async def on_submit(self, interaction: discord.Interaction):
        # Defer the response immediately to prevent timeout errors.
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        try:
            # Validate and store modal values
            self.infantry_squad_size_val = int(self.infantry_squad_size.value)
            self.attack_squads_val = int(self.attack_squads.value)
            self.defence_squads_val = int(self.defence_squads.value)
            self.flex_squads_val = int(self.flex_squads.value)
            self.armour_squads_val = int(self.armour_squads.value)
            self.recon_squads_val = int(self.recon_squads.value)
            self.arty_squads_val = int(self.arty_squads.value)

            # Run the main logic and get the followup message
            followup_message = await self.cog.run_draft_and_post_workshop(interaction, self.event_id, self)
            await interaction.followup.send(followup_message, ephemeral=True)

        except ValueError:
            await interaction.followup.send("All squad counts must be valid numbers.", ephemeral=True)
        except Exception as e:
            print(f"Error in modal submission: {e}")
            traceback.print_exc()
            await interaction.followup.send("An unexpected error occurred while processing the squad build.", ephemeral=True)

# --- Main Cog ---
class SquadBuilder(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db

    squads_group = app_commands.Group(name="squads", description="Commands for building and managing squads.")

    @squads_group.command(name="build", description="Build the team composition for an event.")
    @app_commands.describe(event_id="The ID of the event to build squads for.")
    async def build(self, interaction: discord.Interaction, event_id: int):
        # Basic permission check
        if not interaction.user.guild_permissions.administrator:
             await interaction.response.send_message("You need to be an administrator to use this command.", ephemeral=True)
             return

        event = await self.db.get_event_by_id(event_id)
        if not event:
            await interaction.response.send_message(f"Event with ID {event_id} not found.", ephemeral=True)
            return

        # Send the modal to the user
        modal = SquadBuilderModal(cog=self, event_id=event_id)
        await interaction.response.send_modal(modal)

    async def run_draft_and_post_workshop(self, interaction: discord.Interaction, event_id: int, modal: SquadBuilderModal) -> str:
        """
        Runs the full draft and workshop posting logic.
        Returns a string for the followup message.
        """
        try:
            await self._run_automated_draft(interaction.guild, event_id, modal)
            
            workshop_embed = await self._generate_workshop_embed(interaction.guild, event_id)
            
            # Post the workshop embed in the original channel
            await interaction.channel.send(embed=workshop_embed)
            return "✅ Squads have been built and the workshop is posted above."

        except Exception as e:
            print(f"Error during background squad build process: {e}")
            traceback.print_exc()
            return f"An error occurred while building the squads: {e}"

    async def _get_player_pools(self, guild: discord.Guild, signups: List[Dict]) -> Dict[str, Dict[str, List[Dict]]]:
        """Sorts signed-up players into pools based on their roles and specialties."""
        squad_roles = await self.db.get_squad_config_roles(guild.id)
        player_pools = defaultdict(lambda: defaultdict(list))
        
        for signup in signups:
            if signup['rsvp_status'] != RsvpStatus.ACCEPTED:
                continue
            
            member = guild.get_member(signup['user_id'])
            if not member: continue

            user_role_ids = {r.id for r in member.roles}
            player_info = {**signup, 'member': member}
            role = player_info.get('role_name')
            subclass = player_info.get('subclass_name')

            if not role or role == "Unassigned":
                player_pools['general']['Unassigned'].append(player_info)
                continue

            if role == 'Commander':
                player_pools['commander'][role].append(player_info)
            elif role == 'Recon':
                s_class = subclass or 'Unassigned'
                player_pools['recon'][s_class].append(player_info)
            elif role == 'Armour' and squad_roles.get('squad_armour_role_id') in user_role_ids:
                s_class = subclass or 'Unassigned'
                player_pools['armour'][s_class].append(player_info)
            elif role == 'Infantry':
                s_class = subclass or 'Unassigned'
                if squad_roles.get('squad_arty_role_id') in user_role_ids and s_class == 'Officer':
                    player_pools['arty'][s_class].append(player_info)
                elif squad_roles.get('squad_attack_role_id') in user_role_ids and squad_roles.get('squad_defence_role_id') in user_role_ids:
                    player_pools['flex'][s_class].append(player_info)
                elif squad_roles.get('squad_attack_role_id') in user_role_ids:
                    player_pools['attack'][s_class].append(player_info)
                elif squad_roles.get('squad_defence_role_id') in user_role_ids:
                    player_pools['defence'][s_class].append(player_info)
                else:
                    player_pools['general'][s_class].append(player_info)
        
        return player_pools

    async def _run_automated_draft(self, guild: discord.Guild, event_id: int, modal: SquadBuilderModal):
        """The core logic for drafting players into squads."""
        await self.db.delete_squads_for_event(event_id)
        signups = await self.db.get_signups_for_event(event_id)
        pools = await self._get_player_pools(guild, signups)
        
        # --- Draft Logic ---

        # 1. Commander
        squad_id = await self.db.create_squad(event_id, "Command", "Command")
        try:
            player = pools['commander']['Commander'].pop(0)
            await self.db.add_squad_member(squad_id, player['user_id'], "Commander")
        except IndexError: pass

        # 2. Arty
        for i in range(modal.arty_squads_val):
            squad_id = await self.db.create_squad(event_id, f"Arty {get_squad_letter(i)}", "Arty")
            try:
                player = pools['arty']['Officer'].pop(0)
                await self.db.add_squad_member(squad_id, player['user_id'], "Officer")
            except IndexError: pass

        # 3. Recon
        for i in range(modal.recon_squads_val):
            squad_id = await self.db.create_squad(event_id, f"Recon {get_squad_letter(i)}", "Recon")
            try:
                player = pools['recon']['Spotter'].pop(0)
                await self.db.add_squad_member(squad_id, player['user_id'], "Spotter")
            except IndexError: pass
            try:
                player = pools['recon']['Sniper'].pop(0)
                await self.db.add_squad_member(squad_id, player['user_id'], "Sniper")
            except IndexError: pass

        # 4. Armour
        for i in range(modal.armour_squads_val):
            squad_id = await self.db.create_squad(event_id, f"Armour {get_squad_letter(i)}", "Armour")
            try:
                player = pools['armour']['Tank Commander'].pop(0)
                await self.db.add_squad_member(squad_id, player['user_id'], "Tank Commander")
            except IndexError: pass
            for _ in range(2): 
                try:
                    player = pools['armour']['Crewman'].pop(0)
                    await self.db.add_squad_member(squad_id, player['user_id'], "Crewman")
                except IndexError: pass

        # 5. Infantry Squads (ROBUST REWRITE)
        
        # Create a master list of all infantry players, sorted by priority
        all_infantry = []
        officers = []
        
        inf_pools_to_check = ['attack', 'flex', 'defence', 'general']
        officer_priority = ['attack', 'flex', 'defence', 'general']
        subclass_priority = ["Anti-Tank", "Support", "Medic", "Machine Gunner", "Automatic Rifleman", "Assault", "Engineer", "Rifleman", "Unassigned"]

        # Gather Officers
        for pool_name in officer_priority:
            officers.extend(pools[pool_name].get('Officer', []))
        
        # Gather all other infantry
        for pool_name in inf_pools_to_check:
            for subclass in subclass_priority:
                all_infantry.extend(pools[pool_name].get(subclass, []))

        # Create all infantry squads first
        inf_squads_to_create = []
        inf_squad_count = 0
        squad_types = [('Attack', modal.attack_squads_val), ('Defence', modal.defence_squads_val), ('Flex', modal.flex_squads_val)]
        for squad_type, count in squad_types:
            for _ in range(count):
                squad_name = f"{squad_type} {get_squad_letter(inf_squad_count)}"
                squad_id = await self.db.create_squad(event_id, squad_name, squad_type)
                inf_squads_to_create.append(squad_id)
                inf_squad_count += 1
        
        # Fill the created squads
        for squad_id in inf_squads_to_create:
            # Assign Officer
            try:
                officer = officers.pop(0)
                await self.db.add_squad_member(squad_id, officer['user_id'], 'Officer')
            except IndexError:
                continue # No more officers, cannot fill this squad further

            # Fill remaining slots
            for _ in range(modal.infantry_squad_size_val - 1):
                try:
                    infantryman = all_infantry.pop(0)
                    subclass = infantryman.get('subclass_name') or "Unassigned"
                    await self.db.add_squad_member(squad_id, infantryman['user_id'], subclass)
                except IndexError:
                    break # No more infantry players left

        # 6. Add all unassigned players to reserves
        # Re-fetch signups and created squad members to find who is left
        all_signups = {s['user_id'] for s in await self.db.get_signups_for_event(event_id) if s['rsvp_status'] == RsvpStatus.ACCEPTED}
        all_squads = await self.db.get_squads_for_event(event_id)
        placed_members = set()
        for squad in all_squads:
            members = await self.db.get_squad_members(squad['squad_id'])
            for member in members:
                placed_members.add(member['user_id'])
        
        reserves = all_signups - placed_members
        
        if reserves:
            reserve_squad_id = await self.db.create_squad(event_id, "Reserves", "Reserves")
            for user_id in reserves:
                signup = next((s for s in signups if s['user_id'] == user_id), None)
                if signup:
                    role_display = signup.get('subclass_name') or signup.get('role_name') or "Unassigned"
                    await self.db.add_squad_member(reserve_squad_id, user_id, role_display)

    async def _generate_workshop_embed(self, guild: discord.Guild, event_id: int) -> discord.Embed:
        """Generates the final embed showing the built squads."""
        event = await self.db.get_event_by_id(event_id)
        squads = await self.db.get_squads_for_event(event_id)
        
        embed = discord.Embed(
            title=f"🛠️ Squad Workshop for: {event['title']}",
            description="This is the automatically generated team composition. Admins can make manual adjustments as needed.",
            color=discord.Color.gold()
        )

        for squad in squads:
            members = await self.db.get_squad_members(squad['squad_id'])
            member_list = []
            for member_data in members:
                member_obj = guild.get_member(member_data['user_id'])
                member_name = member_obj.display_name if member_obj else f"ID: {member_data['user_id']}"
                member_list.append(f"**{member_data['assigned_role_name']}:** {member_name}")
        
            value = "\n".join(member_list) or "Empty"
            embed.add_field(name=f"__**{squad['name']}**__ ({squad['squad_type']})", value=value, inline=True)
            
        embed.set_footer(text=f"Event ID: {event_id}")
        return embed

async def setup(bot: commands.Bot, db: Database):
    await bot.add_cog(SquadBuilder(bot, db))
