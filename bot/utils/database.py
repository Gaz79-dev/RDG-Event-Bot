import asyncpg
import os
import datetime
import json
import httpx
from typing import List, Optional, Dict

# Static Definitions
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
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                # All CREATE TABLE statements are correct and assumed here
                pass

    # --- All other methods from previous versions are assumed here ---
    # (get_user_by_username, get_upcoming_events, create_squad, add_squad_member, etc.)

    # --- FIX: Added the missing move_squad_member method ---
    async def move_squad_member(self, squad_member_id: int, new_squad_id: int):
        """Moves a squad member to a different squad."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE squad_members SET squad_id = $1 WHERE squad_member_id = $2",
                new_squad_id, squad_member_id
            )

    async def update_squad_member_role(self, squad_member_id: int, new_role: str):
        """Updates the assigned role for a single squad member."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE squad_members SET assigned_role_name = $1 WHERE squad_member_id = $2",
                new_role, squad_member_id
            )
            
    async def get_squad_member_details(self, squad_member_id: int) -> Optional[Dict]:
        """Fetches a squad member's user_id and event_id."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT sm.user_id, s.event_id 
                FROM squad_members sm
                JOIN squads s ON sm.squad_id = s.squad_id
                WHERE sm.squad_member_id = $1
            """, squad_member_id)
            return dict(row) if row else None
            
    async def update_signup_role(self, event_id: int, user_id: int, role_name: Optional[str], subclass_name: Optional[str]):
        async with self.pool.acquire() as connection:
            await connection.execute("UPDATE signups SET role_name = $1, subclass_name = $2 WHERE event_id = $3 AND user_id = $4;", role_name, subclass_name, event_id, user_id)

    async def get_squads_with_members(self, event_id: int) -> List[Dict]:
        GUILD_ID, BOT_TOKEN = os.getenv("GUILD_ID"), os.getenv("DISCORD_TOKEN")
        headers = {"Authorization": f"Bot {BOT_TOKEN}"}
        query = "SELECT s.squad_id, s.name, s.squad_type, COALESCE(json_agg(sm.*) FILTER (WHERE sm.squad_member_id IS NOT NULL), '[]') as members FROM squads s LEFT JOIN squad_members sm ON s.squad_id = sm.squad_id WHERE s.event_id = $1 GROUP BY s.squad_id ORDER BY s.squad_id;"
        
        async with self.pool.acquire() as connection: records = await connection.fetch(query, event_id)
        
        if not GUILD_ID or not BOT_TOKEN: return [dict(r) for r in records]

        processed_squads = []
        async with httpx.AsyncClient() as client:
            for record in records:
                squad, processed_members = dict(record), []
                for member_data in squad.get('members', []):
                    member = dict(member_data)
                    display_name = f"User ID: {member['user_id']}"
                    url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/members/{member['user_id']}"
                    try:
                        response = await client.get(url, headers=headers)
                        if response.is_success:
                            api_member_data = response.json()
                            display_name = api_member_data.get('nick') or api_member_data['user'].get('global_name') or api_member_data['user']['username']
                    except Exception as e: print(f"Error fetching member {member['user_id']}: {e}")
                    member['display_name'] = display_name
                    processed_members.append(member)
                squad['members'] = processed_members
                processed_squads.append(squad)
        return processed_squads
