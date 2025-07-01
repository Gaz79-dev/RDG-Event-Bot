import discord
from discord.ext import commands
from discord import app_commands, ui
import asyncio
from typing import List, Dict, Optional, Tuple
import traceback
from collections import defaultdict

# Use relative import to go up one level to the 'bot' package root
from ..utils.database import Database, RsvpStatus, ROLES, SUBCLASSES

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

# --- Command Definition (Module Level) ---
squads_group = app_commands.Group(name="squads", description="Commands for building and managing squads.")

@squads_group.command(name="build", description="Build the team composition for an event.")
@app_commands.describe(event_id="The ID of the event to build squads for.")
async def build_command(interaction: discord.Interaction, event_id: int):
    # Get the cog from the bot client to access its methods and state
    squad_builder_cog = interaction.client.get_cog("SquadBuilder")
    if not squad_builder_cog:
        return await interaction.response.send_message("SquadBuilder cog is not loaded.", ephemeral=True)

    # Permission check
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("You need to be an administrator to use this command.", ephemeral=True)

    # Check if event exists
    event = await squad_builder_cog.db.get_event_by_id(event_id)
    if not event:
        return await interaction.response.send_message(f"Event with ID {event_id} not found.", ephemeral=True)

    # Send the modal to the user, passing the cog instance
    await interaction.response.send_modal(SquadBuilderModal(squad_builder_cog, event_id))

# --- Cog Definition (For State and Helpers) ---
class SquadBuilder(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db

    async def run_draft_and_post_workshop(self, interaction: discord.Interaction, event_id: int, modal: SquadBuilderModal) -> str:
        """
        Runs the full draft and workshop posting logic.
        Returns a string for the followup message.
        """
        try:
            print("Starting automated draft...")
            await self._run_automated_draft(interaction.guild, event_id, modal)
            print("Automated draft finished successfully.")
            
            print("Generating workshop embed...")
            workshop_embed = await self._generate_workshop_embed(interaction.guild, event_id)
            print("Workshop embed generated.")
            
            # Post the workshop embed in the original channel
            await interaction.channel.send(embed=workshop_embed)
            return "✅ Squads have been built and the workshop is posted above."

        except Exception as e:
            print(f"!!! AN ERROR OCCURRED DURING SQUAD BUILD PROCESS !!!")
            traceback.print_exc()
            return f"An error occurred while building the squads. Please check the bot logs."

    async def _get_player_pools(self, guild: discord.Guild, signups: List[Dict]) -> Dict[str, Dict[str, List[Dict]]]:
        """Sorts signed-up players into pools based on their roles and specialties."""
        squad_roles = await self.db.get_squad_config_roles(guild.id)
        pools = defaultdict(lambda: defaultdict(list))
        
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
                pools['general']['Unassigned'].append(player_info)
                continue

            if role == 'Commander':
                pools['commander'][role].append(player_info)
            elif role == 'Recon':
                s_class = subclass or 'Unassigned'
                pools['recon'][s_class].append(player_info)
            elif role == 'Armour' and squad_roles and squad_roles.get('squad_armour_role_id') in user_role_ids:
                s_class = subclass or 'Unassigned'
                pools['armour'][s_class].append(player_info)
            elif role == 'Infantry':
                s_class = subclass or 'Unassigned'
                if squad_roles and squad_roles.get('squad_arty_role_id') in user_role_ids and s_class == 'Officer':
                    pools['arty'][s_class].append(player_info)
                elif squad_roles and squad_roles.get('squad_attack_role_id') in user_role_ids and squad_roles.get('squad_defence_role_id') in user_role_ids:
                    pools['flex'][s_class].append(player_info)
                elif squad_roles and squad_roles.get('squad_attack_role_id') in user_role_ids:
                    pools['attack'][s_class].append(player_info)
                elif squad_roles and squad_roles.get('squad_defence_role_id') in user_role_ids:
                    pools['defence'][s_class].append(player_info)
                else:
                    pools['general'][s_class].append(player_info)
        
        return pools

    async def _run_automated_draft(self, guild: discord.Guild, event_id: int, modal: SquadBuilderModal):
        """The core logic for drafting players into squads."""

        print("--- RUNNING AUTOMATED DRAFT ---")
        await self.db.delete_squads_for_event(event_id)
        signups = await self.db.get_signups_for_event(event_id)
        pools = await self._get_player_pools(guild, signups)

        # 1. Always create a single Commander squad (no letter/suffix)
        commander_pool = pools['commander'].get('Commander', [])
        commander_squad_id = await self.db.create_squad(event_id, name="Commander", squad_type="Commander")
        if commander_pool:
            # Only assign one user, extras go to reserves or unassigned
            commander = commander_pool[0]
            await self.db.add_squad_member(commander_squad_id, commander['user_id'], "Commander")
            # Any additional commanders can be added to reserves or left out; here we do nothing for extras

        # 2. Infantry Squads
        infantry_pool = []
        for subclass in SUBCLASSES.get("Infantry", []):
            infantry_pool.extend(pools['general'].get(subclass, []))
        infantry_pool.extend(pools['general'].get('Unassigned', []))
        infantry_squad_size = modal.infantry_squad_size_val

        infantry_count = 0
        for idx in range(0, len(infantry_pool), infantry_squad_size):
            members = infantry_pool[idx:idx + infantry_squad_size]
            squad_name = f"Infantry {get_squad_letter(infantry_count)}"
            squad_id = await self.db.create_squad(event_id, name=squad_name, squad_type="Infantry")
            for m in members:
                await self.db.add_squad_member(squad_id, m['user_id'], m.get('subclass_name') or m.get('role_name', 'Infantry'))
            infantry_count += 1

        # 3. Other squads (Attack, Defence, Flex, Armour, Recon, Arty)
        squad_types = [
            ("attack", modal.attack_squads_val, "Attack"),
            ("defence", modal.defence_squads_val, "Defence"),
            ("flex", modal.flex_squads_val, "Flex"),
            ("armour", modal.armour_squads_val, "Armour"),
            ("recon", modal.recon_squads_val, "Recon"),
            ("arty", modal.arty_squads_val, "Arty")
        ]
        for pool_key, num_squads, squad_label in squad_types:
            if num_squads > 0 and pool_key in pools:
                pool_members = []
                for subclass_list in pools[pool_key].values():
                    pool_members.extend(subclass_list)
                count = 0
                size = infantry_squad_size if squad_label not in ("Armour", "Recon", "Arty") else 3  # Example size logic
                for idx in range(0, len(pool_members), size):
                    members = pool_members[idx:idx + size]
                    squad_name = f"{squad_label} {get_squad_letter(count)}"
                    squad_id = await self.db.create_squad(event_id, name=squad_name, squad_type=squad_label)
                    for m in members:
                        await self.db.add_squad_member(squad_id, m['user_id'], m.get('subclass_name') or m.get('role_name', squad_label))
                    count += 1

        # 4. Reserves squad: anyone not assigned above
        assigned_ids = set()
        squads = await self.db.get_squads_with_members(event_id)
        for squad in squads:
            for m in squad.get('members', []):
                assigned_ids.add(m['user_id'])
        reserves = [s for s in signups if s['user_id'] not in assigned_ids and s['rsvp_status'] == RsvpStatus.ACCEPTED]
        if reserves:
            reserves_squad_id = await self.db.create_squad(event_id, name="Reserves", squad_type="Reserves")
            for s in reserves:
                await self.db.add_squad_member(reserves_squad_id, s['user_id'], s.get('subclass_name') or s.get('role_name', 'Unassigned'))

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
            for m in members:
                member_obj = guild.get_member(m['user_id'])
                if member_obj:
                    name = member_obj.display_name
                else:
                    name = f"ID: {m['user_id']}"
                member_list.append(f"**{m['assigned_role_name']}:** {name}")
            
            value = "\n".join(member_list) or "Empty"
            embed.add_field(name=f"__**{squad['name']}**__", value=value, inline=True)
            
        embed.set_footer(text=f"Event ID: {event_id}")
        return embed

# --- Setup Function ---
async def setup(bot: commands.Bot):
    """Sets up the SquadBuilder cog and explicitly adds its commands."""
    await bot.add_cog(SquadBuilder(bot, bot.db))
    bot.tree.add_command(squads_group)
