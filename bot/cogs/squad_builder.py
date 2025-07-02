import os
import httpx
from collections import defaultdict
from typing import List, Dict, Coroutine

# Use absolute imports from the 'bot' package root
from bot.utils.database import Database, RsvpStatus
from bot.api.models import SquadBuildRequest

# Hell Let Loose class limits per squad
CLASS_LIMITS = {
    "Officer": 1, "Medic": 1, "Support": 1, "Anti-Tank": 1,
    "Machine Gunner": 1, "Automatic Rifleman": 1, "Assault": 1, "Engineer": 1,
    "Spotter": 1, "Sniper": 1, "Tank Commander": 1,
    # Rifleman and Crewman have no hard limit beyond squad size
    "Rifleman": 99, "Crewman": 99,
}

# The order in which players should be picked to fill squads
SUBCLASS_PRIORITY = [
    "Officer", "Support", "Medic", "Anti-Tank", "Machine Gunner", "Automatic Rifleman",
    "Engineer", "Assault", "Rifleman", "Tank Commander", "Crewman", "Spotter", "Sniper"
]


def get_squad_letter(squad_type: str, counts: Dict) -> str:
    """Gets the next letter for a squad type (e.g., Attack A, Attack B)."""
    counts[squad_type] = counts.get(squad_type, 0) + 1
    count = counts[squad_type] - 1
    return chr(ord('A') + count) if count < 26 else f"Z{count - 25}"


async def _get_full_roster_details(db: Database, event_id: int) -> List[Dict]:
    """
    Fetches all accepted signups and enriches them with their current Discord roles.
    This is critical for determining eligibility for specialty squads.
    """
    signups = await db.get_signups_for_event(event_id)
    event_details = await db.get_event_by_id(event_id)
    if not event_details:
        return []

    GUILD_ID = os.getenv("GUILD_ID")
    BOT_TOKEN = os.getenv("DISCORD_TOKEN")
    if not GUILD_ID or not BOT_TOKEN:
        print("Warning: GUILD_ID or DISCORD_TOKEN not set. Cannot fetch member roles.")
        return [dict(s) for s in signups if s['rsvp_status'] == RsvpStatus.ACCEPTED]

    full_roster = []
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    async with httpx.AsyncClient() as client:
        for signup in signups:
            if signup['rsvp_status'] != RsvpStatus.ACCEPTED:
                continue

            url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/members/{signup['user_id']}"
            try:
                response = await client.get(url, headers=headers)
                if response.is_success:
                    member_data = response.json()
                    # Add the list of role IDs from Discord to the signup data
                    signup['discord_role_ids'] = {int(role_id) for role_id in member_data.get('roles', [])}
                else:
                    signup['discord_role_ids'] = set() # User might not be in the server anymore
            except Exception:
                signup['discord_role_ids'] = set()

            full_roster.append(dict(signup))
    return full_roster


async def _fill_squad(squad: Dict, player_pool: List[Dict], squad_size: int, class_limits: Dict) -> List[Dict]:
    """
    Fills a single squad with players from a given pool, respecting class limits.
    Returns the list of players who could not be placed.
    """
    unplaced_players = []
    # Sort the pool to prioritize essential roles
    player_pool.sort(key=lambda p: SUBCLASS_PRIORITY.index(p['subclass_name']) if p.get('subclass_name') in SUBCLASS_PRIORITY else 99)

    while len(squad['members']) < squad_size and player_pool:
        player_to_add = player_pool.pop(0)
        player_class = player_to_add.get('subclass_name')

        if not player_class:
            unplaced_players.append(player_to_add)
            continue

        # Check if the class slot is available
        if squad['class_counts'][player_class] < class_limits.get(player_class, 99):
            squad['members'].append(player_to_add)
            squad['class_counts'][player_class] += 1
        else:
            # This class is full in this squad, put player back for another squad
            unplaced_players.append(player_to_add)

    # Return any players who were popped but not placed, plus the rest of the original pool
    return unplaced_players + player_pool


async def run_web_draft(db: Database, event_id: int, request: SquadBuildRequest) -> List[Dict]:
    """
    The main squad building logic, rewritten to follow HLL standards.
    """
    # 1. SETUP: Clear old squads and get full roster details
    await db.delete_squads_for_event(event_id)
    full_roster = await _get_full_roster_details(db, event_id)
    
    # Get specialty role IDs from environment variables
    attack_role_id = int(os.getenv("ROLE_ID_ATTACK")) if os.getenv("ROLE_ID_ATTACK") else None
    defence_role_id = int(os.getenv("ROLE_ID_DEFENCE")) if os.getenv("ROLE_ID_DEFENCE") else None

    # 2. PRE-DRAFT: Sort all players into specific pools
    player_pools = defaultdict(list)
    for player in full_roster:
        primary_role = player.get('role_name')
        discord_roles = player.get('discord_role_ids', set())

        if primary_role == "Commander":
            player_pools["commander"].append(player)
        elif primary_role == "Infantry" and attack_role_id in discord_roles:
            player_pools["attack"].append(player)
        elif primary_role == "Infantry" and defence_role_id in discord_roles:
            player_pools["defence"].append(player)
        elif primary_role == "Artillery":
            player_pools["artillery"].append(player)
        elif primary_role == "Pathfinders":
            player_pools["pathfinder"].append(player)
        elif primary_role == "Recon":
            player_pools["recon"].append(player)
        elif primary_role == "Armour":
            player_pools["armour"].append(player)
        else: # General infantry or unassigned
            player_pools["general_infantry"].append(player)

    # 3. DRAFTING - PHASE 1: Handle unique squads first
    squads = []
    unplaced_players = []
    squad_name_counts = defaultdict(int)

    # Commander Squad
    squads.append({'name': "Commander", 'squad_type': "Command", 'members': [], 'class_counts': defaultdict(int)})
    if player_pools["commander"]:
        squads[0]['members'].append(player_pools["commander"].pop(0)) # Assign first commander
    unplaced_players.extend(player_pools.pop("commander", [])) # Add any extras to reserves

    # Recon Squads
    for _ in range(request.recon_squads):
        squad_name = f"Recon {get_squad_letter('Recon', squad_name_counts)}"
        recon_squad = {'name': squad_name, 'squad_type': "Recon", 'members': [], 'class_counts': defaultdict(int)}
        
        # Find one spotter and one sniper
        spotter_pool = [p for p in player_pools["recon"] if p.get('subclass_name') == 'Spotter']
        sniper_pool = [p for p in player_pools["recon"] if p.get('subclass_name') == 'Sniper']

        if spotter_pool: recon_squad['members'].append(spotter_pool.pop(0))
        if sniper_pool: recon_squad['members'].append(sniper_pool.pop(0))
        
        # Remove placed players from the main pool
        placed_ids = {p['user_id'] for p in recon_squad['members']}
        player_pools["recon"] = [p for p in player_pools["recon"] if p['user_id'] not in placed_ids]
        squads.append(recon_squad)
    unplaced_players.extend(player_pools.pop("recon", []))

    # Armour Squads
    for _ in range(request.armour_squads):
        squad_name = f"Armour {get_squad_letter('Armour', squad_name_counts)}"
        armour_squad = {'name': squad_name, 'squad_type': "Armour", 'members': [], 'class_counts': defaultdict(int)}
        armour_squad, remaining_armour = await _fill_squad(armour_squad, player_pools["armour"], 3, CLASS_LIMITS)
        player_pools["armour"] = remaining_armour
        squads.append(armour_squad)
    unplaced_players.extend(player_pools.pop("armour", []))
    
    # Artillery Squads
    for _ in range(request.arty_squads):
        squad_name = f"Artillery {get_squad_letter('Artillery', squad_name_counts)}"
        arty_squad = {'name': squad_name, 'squad_type': "Artillery", 'members': [], 'class_counts': defaultdict(int)}
        if player_pools["artillery"]:
            arty_squad['members'].append(player_pools["artillery"].pop(0))
        squads.append(arty_squad)
    unplaced_players.extend(player_pools.pop("artillery", []))

    # 4. DRAFTING - PHASE 2: Handle standard infantry-style squads
    squad_definitions = [
        ("attack", request.attack_squads, "Attack", request.infantry_squad_size),
        ("defence", request.defence_squads, "Defence", request.infantry_squad_size),
        ("pathfinder", request.pathfinder_squads, "Pathfinder", request.infantry_squad_size),
    ]

    for pool_key, num_squads, squad_name_base, squad_size in squad_definitions:
        for _ in range(num_squads):
            squad_name = f"{squad_name_base} {get_squad_letter(squad_name_base, squad_name_counts)}"
            new_squad = {'name': squad_name, 'squad_type': "Infantry", 'members': [], 'class_counts': defaultdict(int)}
            new_squad, remaining_players = await _fill_squad(new_squad, player_pools[pool_key], squad_size, CLASS_LIMITS)
            player_pools[pool_key] = remaining_players
            squads.append(new_squad)
        # Any players left in these specialty pools are now considered general infantry
        player_pools["general_infantry"].extend(player_pools.pop(pool_key, []))

    # 5. DRAFTING - PHASE 3: Fill remaining general infantry squads
    while len(player_pools["general_infantry"]) >= request.infantry_squad_size:
        squad_name = f"Infantry {get_squad_letter('Infantry', squad_name_counts)}"
        inf_squad = {'name': squad_name, 'squad_type': "Infantry", 'members': [], 'class_counts': defaultdict(int)}
        inf_squad, remaining_players = await _fill_squad(inf_squad, player_pools["general_infantry"], request.infantry_squad_size, CLASS_LIMITS)
        player_pools["general_infantry"] = remaining_players
        squads.append(inf_squad)
    unplaced_players.extend(player_pools.pop("general_infantry", []))

    # 6. CLEANUP: Assign all remaining players to Reserves
    squads.append({
        'name': "Reserves", 'squad_type': "Reserves",
        'members': unplaced_players, 'class_counts': defaultdict(int)
    })

    # 7. FINALIZATION: Write all created squads and members to the database
    for squad_data in squads:
        squad_id = await db.create_squad(event_id, squad_data['name'], squad_data['squad_type'])
        for member in squad_data['members']:
            role = member.get('subclass_name') or member.get('role_name') or 'Unassigned'
            await db.add_squad_member(squad_id, member['user_id'], role)

    # Return the final state from the database, now with display names
    return await db.get_squads_with_members(event_id)
