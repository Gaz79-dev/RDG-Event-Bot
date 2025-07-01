import asyncpg
import os
import datetime
import json
import httpx
from typing import List, Optional, Dict

# --- Static Definitions ---
ROLES = ["Commander", "Infantry", "Armour", "Recon", "Pathfinders"]
SUBCLASSES = {
    "Infantry": ["Anti-Tank", "Assault", "Automatic Rifleman", "Engineer", "Machine Gunner", "Medic", "Officer", "Rifleman", "Support"],
    "Armour": ["Tank Commander", "Crewman"],
    "Recon": ["Spotter", "Sniper"],
    "Pathfinders": ["Spotter"]
}
RESTRICTED_ROLES = ["Commander", "Recon", "Officer", "Tank Commander"]

class RsvpStatus:
    ACCEPTED = "Accepted"
    TENTATIVE = "Tentative"
    DECLINED = "Declined"

class Database:
    # ... (Keep the __init__, connect, and _initial_setup methods as they are) ...
    # ... (Keep all User Management, Event, and Scheduler functions) ...

    # --- Squad & Guild Config Functions ---
    
    # --- FIX: Add the missing get_all_roles_and_subclasses method ---
    async def get_all_roles_and_subclasses(self) -> Dict:
        """Returns the static lists of roles and subclasses."""
        return {"roles": ROLES, "subclasses": SUBCLASSES}

    # ... (Keep all other squad-related functions like create_squad, delete_squads_for_event, etc.) ...

    async def close(self):
        if self.pool:
            await self.pool.close()
            print("Database connection pool closed.")
