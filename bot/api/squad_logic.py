from collections import defaultdict
from typing import List, Dict

from ..utils.database import Database, RsvpStatus, ROLES, SUBCLASSES

def get_squad_letter(count: int) -> str:
    """Converts a number to a letter (0=A, 1=B, etc.)."""
    if count < 26:
        return chr(ord('A') + count)
    return f"Z{count - 25}"

async def run_web_draft(db: Database, event_id: int, request_data) -> List[Dict]:
    """The core logic for drafting players into squads, adapted for the web API."""
    
    await db.delete_squads_for_event(event_id)
    signups = await db.get_signups_for_event(event_id)
    
    # --- Simplified Player Pool Creation ---
    player_pools = defaultdict(lambda: defaultdict(list))
    for signup in signups:
        if signup['rsvp_status'] != RsvpStatus.ACCEPTED:
            continue
        
        role = signup.get('role_name') or "Unassigned"
        subclass = signup.get('subclass_name') or "Unassigned"
        
        player_info = dict(signup) # Convert record to dict
        
        if role in ['Commander', 'Recon', 'Armour']:
            player_pools[role.lower()][subclass].append(player_info)
        else: # All other roles (Infantry, etc.) go into a general pool
            player_pools['infantry'][subclass].append(player_info)

    # --- Draft Logic ---
    # 1. Commander
    if player_pools['commander']['Commander']:
        s_id = await db.create_squad(event_id, "Command", "Command")
        player = player_pools['commander']['Commander'].pop(0)
        await db.add_squad_member(s_id, player['user_id'], "Commander")

    # 2. Recon
    for i in range(request_data.recon_squads):
        s_id = await db.create_squad(event_id, f"Recon {get_squad_letter(i)}", "Recon")
        if player := player_pools['recon']['Spotter']: await db.add_squad_member(s_id, player.pop(0)['user_id'], "Spotter")
        if player := player_pools['recon']['Sniper']: await db.add_squad_member(s_id, player.pop(0)['user_id'], "Sniper")

    # 3. Armour
    for i in range(request_data.armour_squads):
        s_id = await db.create_squad(event_id, f"Armour {get_squad_letter(i)}", "Armour")
        if player := player_pools['armour']['Tank Commander']: await db.add_squad_member(s_id, player.pop(0)['user_id'], "Tank Commander")
        for _ in range(2):
            if player := player_pools['armour']['Crewman']: await db.add_squad_member(s_id, player.pop(0)['user_id'], "Crewman")

    # 4. Infantry Squads
    all_infantry = []
    officers = player_pools['infantry'].pop('Officer', [])
    subclass_priority = ["Anti-Tank", "Support", "Medic", "Machine Gunner", "Automatic Rifleman", "Assault", "Engineer", "Rifleman", "Unassigned"]
    for subclass in subclass_priority:
        all_infantry.extend(player_pools['infantry'].pop(subclass, []))

    inf_squad_count = 0
    for _ in range(request_data.attack_squads + request_data.defence_squads + request_data.flex_squads):
        s_id = await db.create_squad(event_id, f"Infantry {get_squad_letter(inf_squad_count)}", "Infantry")
        inf_squad_count += 1
        if officer := officers: await db.add_squad_member(s_id, officer.pop(0)['user_id'], 'Officer')
        for _ in range(request_data.infantry_squad_size - 1):
            if infantryman := all_infantry: await db.add_squad_member(s_id, infantryman.pop(0)['user_id'], infantryman[0]['subclass_name'])
    
    # 5. Fetch and return the result
    return await db.get_squads_with_members(event_id)
