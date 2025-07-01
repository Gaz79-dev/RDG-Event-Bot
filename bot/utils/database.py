import asyncpg
import os
import datetime
import json
import httpx
from typing import List, Optional, Dict

# --- Static Definitions ---
ROLES = ["Commander", "Infantry", "Armour", "Recon"]
SUBCLASSES = {
    "Infantry": ["Anti-Tank", "Assault", "Automatic Rifleman", "Engineer", "Machine Gunner", "Medic", "Officer", "Rifleman", "Support"],
    "Armour": ["Tank Commander", "Crewman"],
    "Recon": ["Spotter", "Sniper"]
}
# Adding Pathfinders to the role list for drafting
ROLES.append("Pathfinders")
SUBCLASSES["Pathfinders"] = ["Spotter"] # Pathfinders can be spotters

RESTRICTED_ROLES = ["Commander", "Recon", "Officer", "Tank Commander"]

class RsvpStatus:
    ACCEPTED = "Accepted"
    TENTATIVE = "Tentative"
    DECLINED = "Declined"

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        async def init_connection(conn):
            await conn.set_type_codec('json', encoder=json.dumps, decoder=json.loads, schema='pg_catalog')
            await conn.set_type_codec('jsonb', encoder=json.dumps, decoder=json.loads, schema='pg_catalog')
        try:
            self.pool = await asyncpg.create_pool(
                user=os.getenv("POSTGRES_USER"), password=os.getenv("POSTGRES_PASSWORD"),
                database=os.getenv("POSTGRES_DB"), host=os.getenv("POSTGRES_HOST", "db"),
                port=os.getenv("POSTGRES_PORT", 5432),
                init=init_connection
            )
            print("Successfully connected to the PostgreSQL database.")
            await self._initial_setup()
        except Exception as e:
            print(f"Error: Could not connect to the PostgreSQL database. {e}")
            raise

    async def _initial_setup(self):
        # ... This method remains the same ...
        pass

    # --- User Management Functions ---
    # ... All user management functions remain the same ...

    # --- Event & Signup Functions ---
    async def get_upcoming_events(self) -> List[Dict]:
        query = "SELECT event_id, title, event_time FROM events WHERE COALESCE(end_time, event_time + INTERVAL '2 hours') > (NOW() AT TIME ZONE 'utc' - INTERVAL '12 hours') ORDER BY event_time DESC;"
        async with self.pool.acquire() as connection:
            return [dict(row) for row in await connection.fetch(query)]

    async def get_signups_for_event(self, event_id: int) -> List[Dict]:
        query = "SELECT * FROM signups WHERE event_id = $1 ORDER BY role_name, subclass_name;"
        async with self.pool.acquire() as conn:
            return [dict(row) for row in await conn.fetch(query, event_id)]

    async def get_signup(self, event_id: int, user_id: int) -> Optional[Dict]:
        """Fetches a specific signup record for a user in an event."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM signups WHERE event_id = $1 AND user_id = $2", event_id, user_id)
            return dict(row) if row else None
            
    # ... other event functions like get_event_by_id, create_event etc. remain ...

    # --- Squad & Guild Config Functions ---
    # ... create_squad, add_squad_member remain the same ...

    async def get_squads_with_members(self, event_id: int) -> List[Dict]:
        # ... This method remains the same ...
        pass

    async def delete_squads_for_event(self, event_id: int):
        # ... This method remains the same ...
        pass

    async def get_all_roles_and_subclasses(self) -> Dict:
        """Returns the static lists of roles and subclasses."""
        # Include Pathfinders in the returned data
        all_roles = ROLES
        all_subclasses = SUBCLASSES
        return {"roles": all_roles, "subclasses": all_subclasses}

    async def update_squad_member_role(self, squad_member_id: int, new_role: str):
        """Updates the assigned role for a single squad member."""
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE squad_members SET assigned_role_name = $1 WHERE squad_member_id = $2", new_role, squad_member_id)

    async def move_squad_member(self, squad_member_id: int, new_squad_id: int):
        """Moves a squad member to a different squad."""
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE squad_members SET squad_id = $1 WHERE squad_member_id = $2", new_squad_id, squad_member_id)

    async def get_squad_by_name(self, event_id: int, squad_name: str) -> Optional[Dict]:
        """Fetches a squad by its name for a specific event."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM squads WHERE event_id = $1 AND name = $2", event_id, squad_name)
            return dict(row) if row else None

    async def remove_user_from_all_squads(self, event_id: int, user_id: int):
        """Removes a user from any squad they are in for a specific event."""
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM squad_members WHERE user_id = $1 AND squad_id IN (SELECT squad_id FROM squads WHERE event_id = $2)", user_id, event_id)

    async def close(self):
        # ... This method remains the same ...
        pass
