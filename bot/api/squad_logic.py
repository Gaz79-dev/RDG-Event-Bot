from collections import defaultdict
from typing import List, Dict
from bot.utils.database import Database, RsvpStatus

CLASS_LIMITS = {
    "Officer": 1, "Anti-Tank": 1, "Machine Gunner": 1, "Automatic Rifleman": 1,
    "Spotter": 1, "Sniper": 1, "Tank Commander": 1, "Medic": 1, "Support": 1, "Engineer": 1
}

def get_squad_letter(squad_type: str, counts: Dict) -> str:
    """Gets the next letter for a squad type (e.g., Attack A, Attack B)."""
    counts[squad_type] = counts.get(squad_type, 0) + 1
    count = counts[squad_type] - 1
    return chr(ord('A') + count) if count < 26 else f"Z{count - 25}"

async def run_web_draft(db: Database, event_id: int, request_data) -> List[Dict]:
    """The core logic for drafting players into squads with new rules."""
    await db.delete_squads_for_event(event_id)
    signups = await db.get_signups_for_event(event_id)
    
    player_pools = defaultdict(list)
    for signup in signups:
        if signup['rsvp_status'] == RsvpStatus.ACCEPTED:
            # Use the primary role_name for pooling
            player_pools[signup['role_name']].append(dict(signup))

    squad_counts, squads_to_fill = {}, []
    
    # 1. Always create one hardcoded Commander squad
    commander_squad_id = await db.create_squad(event_id, "Commander", "Command")
    squads_to_fill.append({'id': commander_squad_id, 'base_name': 'Commander', 'type': 'Command', 'class_counts': defaultdict(int)})
    
    # 2. Create all other empty squad shells based on the request
    squad_configs = [("Attack", request_data.attack_squads, "Infantry"), 
                     ("Defence", request_data.defence_squads, "Infantry"), 
                     ("Flex", request_data.flex_squads, "Infantry"),
                     ("Pathfinders", request_data.pathfinder_squads, "Recon"), 
                     ("Recon", request_data.recon_squads, "Recon"),
                     ("Armour", request_data.armour_squads, "Armour"), 
                     ("Arty", request_data.arty_squads, "Artillery")]
                     
    for base_name, count, squad_type in squad_configs:
        for _ in range(count):
            squad_name = f"{base_name} {get_squad_letter(base_name, squad_counts)}"
            s_id = await db.create_squad(event_id, squad_name, squad_type)
            squads_to_fill.append({'id': s_id, 'base_name': base_name, 'type': squad_type, 'class_counts': defaultdict(int)})
    
    # 3. Draft players into the created squads
    for squad in squads_to_fill:
        # --- FIX: Handle Commander squad specifically to prevent wrong assignments ---
        if squad['type'] == 'Command':
            # Only pull from the 'Commander' pool. If empty, the squad remains empty.
            player_pool = player_pools.get('Commander', [])
            squad_size = 1
        else:
            # For other squads, determine which player pool to draw from
            pool_key = squad['base_name'] if squad['base_name'] in player_pools else "Infantry"
            player_pool = player_pools.get(pool_key, [])
            squad_size = 3 if squad['type'] == "Armour" else 2 if squad['type'] in ["Recon", "Artillery"] else request_data.infantry_squad_size
        
        # Sort players to prioritize key roles
        subclass_priority = ["Officer", "Medic", "Support", "Anti-Tank", "Machine Gunner", "Spotter", "Tank Commander", "Automatic Rifleman", "Engineer", "Assault", "Rifleman", "Crewman", "Sniper"]
        player_pool.sort(key=lambda p: subclass_priority.index(p['subclass_name']) if p.get('subclass_name') in subclass_priority else 99)

        temp_unplaced_pool = []
        member_count = 0
        
        while member_count < squad_size and player_pool:
            player = player_pool.pop(0)
            # Use subclass_name for role assignment, as it's more specific
            player_class = player.get('subclass_name')
            
            # This check prevents players with no specific subclass from being drafted into limited slots
            if not player_class:
                temp_unplaced_pool.append(player)
                continue

            limit = CLASS_LIMITS.get(player_class, 99)

            if squad['class_counts'][player_class] < limit:
                await db.add_squad_member(squad['id'], player['user_id'], player_class)
                squad['class_counts'][player_class] += 1
                member_count += 1
            else:
                temp_unplaced_pool.append(player)
        
        # Determine the correct pool key to return unplaced players to
        if squad['type'] == 'Command':
            pool_key_for_return = 'Commander'
        else:
            pool_key_for_return = squad['base_name'] if squad['base_name'] in player_pools else "Infantry"

        # Add unplaced players back to their original pool
        player_pools[pool_key_for_return] = temp_unplaced_pool + player_pool

    # 4. All remaining players from all pools go to Reserves
    reserves_squad_id = await db.create_squad(event_id, "Reserves", "Reserves")
    for role in player_pools:
        for player in player_pools[role]:
            # Assign using the most specific role available
            assigned_role = player.get('subclass_name') or player.get('role_name', 'Unassigned')
            await db.add_squad_member(reserves_squad_id, player['user_id'], assigned_role)
        
    return await db.get_squads_with_members(event_id)
