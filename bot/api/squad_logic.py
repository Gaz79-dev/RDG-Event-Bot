from collections import defaultdict
from typing import List, Dict
from bot.utils.database import Database, RsvpStatus

CLASS_LIMITS = {"Officer": 1, "Medic": 1, "Support": 1, "Anti-Tank": 1, "Machine Gunner": 1, "Spotter": 1, "Sniper": 1, "Tank Commander": 1}

def get_squad_letter(squad_type: str, counts: Dict) -> str:
    counts[squad_type] = counts.get(squad_type, 0) + 1; count = counts[squad_type] - 1
    return chr(ord('A') + count) if count < 26 else f"Z{count - 25}"

async def run_web_draft(db: Database, event_id: int, request_data) -> List[Dict]:
    await db.delete_squads_for_event(event_id)
    signups = await db.get_signups_for_event(event_id)
    
    player_pools = defaultdict(list)
    for signup in signups:
        if signup['rsvp_status'] == RsvpStatus.ACCEPTED:
            player_pools[signup['role_name']].append(dict(signup))

    squad_counts, squads_created = {}, []
    
    # Create Squads
    squad_configs = [("Commander", request_data.commander_squads), ("Attack", request_data.attack_squads), ("Defence", request_data.defence_squads), ("Recon", request_data.recon_squads), ("Armour", request_data.armour_squads), ("Pathfinders", request_data.pathfinder_squads)]
    for base_name, count in squad_configs:
        for _ in range(count):
            s_type = "Recon" if base_name in ["Recon", "Pathfinders"] else "Armour" if base_name == "Armour" else "Command" if base_name == "Commander" else "Infantry"
            s_id = await db.create_squad(event_id, f"{base_name} {get_squad_letter(base_name, squad_counts)}", s_type)
            squads_created.append({'id': s_id, 'type': s_type, 'members': [], 'class_counts': defaultdict(int)})

    # Draft players
    # ... A more detailed drafting logic would go here, for now we add to reserves ...
    
    reserves, all_players = [], [p for pool in player_pools.values() for p in pool]
    reserves_squad_id = await db.create_squad(event_id, "Reserves", "Reserves")
    for player in all_players:
        await db.add_squad_member(reserves_squad_id, player['user_id'], player.get('subclass_name') or player.get('role_name', 'Unassigned'))
        
    return await db.get_squads_with_members(event_id)
