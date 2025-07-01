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
    """A database interface for the Discord event bot."""
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
                await connection.execute("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username VARCHAR(50) UNIQUE NOT NULL, hashed_password VARCHAR(255) NOT NULL, is_active BOOLEAN DEFAULT TRUE, is_admin BOOLEAN DEFAULT FALSE);")
                await connection.execute("CREATE TABLE IF NOT EXISTS guilds (guild_id BIGINT PRIMARY KEY, event_manager_role_ids BIGINT[], commander_role_id BIGINT, recon_role_id BIGINT, officer_role_id BIGINT, tank_commander_role_id BIGINT, thread_creation_hours INT DEFAULT 24, squad_attack_role_id BIGINT, squad_defence_role_id BIGINT, squad_arty_role_id BIGINT, squad_armour_role_id BIGINT);")
                await connection.execute("CREATE TABLE IF NOT EXISTS events (event_id SERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, creator_id BIGINT NOT NULL, message_id BIGINT UNIQUE, channel_id BIGINT NOT NULL, thread_id BIGINT, title VARCHAR(255) NOT NULL, description TEXT, event_time TIMESTAMP WITH TIME ZONE NOT NULL, end_time TIMESTAMP WITH TIME ZONE, timezone VARCHAR(100), created_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc'), thread_created BOOLEAN DEFAULT FALSE, is_recurring BOOLEAN DEFAULT FALSE, recurrence_rule VARCHAR(50), mention_role_ids BIGINT[], restrict_to_role_ids BIGINT[], recreation_hours INT, parent_event_id INT REFERENCES events(event_id) ON DELETE SET NULL, last_recreated_at TIMESTAMP WITH TIME ZONE);")
                await connection.execute("CREATE TABLE IF NOT EXISTS signups (signup_id SERIAL PRIMARY KEY, event_id INT REFERENCES events(event_id) ON DELETE CASCADE, user_id BIGINT NOT NULL, role_name VARCHAR(100), subclass_name VARCHAR(100), rsvp_status VARCHAR(10) NOT NULL, UNIQUE(event_id, user_id));")
                await connection.execute("CREATE TABLE IF NOT EXISTS squads (squad_id SERIAL PRIMARY KEY, event_id INT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE, name VARCHAR(100) NOT NULL, squad_type VARCHAR(50) NOT NULL);")
                await connection.execute("CREATE TABLE IF NOT EXISTS squad_members (squad_member_id SERIAL PRIMARY KEY, squad_id INT NOT NULL REFERENCES squads(squad_id) ON DELETE CASCADE, user_id BIGINT NOT NULL, assigned_role_name VARCHAR(100) NOT NULL, UNIQUE(squad_id, user_id));")
                print("Database setup is complete.")

    # --- User Management Functions ---
    async def get_user_by_username(self, username: str) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE username = $1", username)
            return dict(row) if row else None
            
    # ... all other user management functions ...

    # --- Event & Signup Functions ---
    async def get_upcoming_events(self) -> List[Dict]:
        query = "SELECT event_id, title, event_time FROM events WHERE COALESCE(end_time, event_time + INTERVAL '2 hours') > (NOW() AT TIME ZONE 'utc' - INTERVAL '12 hours') ORDER BY event_time DESC;"
        async with self.pool.acquire() as connection:
            return [dict(row) for row in await connection.fetch(query)]

    async def get_signups_for_event(self, event_id: int) -> List[Dict]:
        async with self.pool.acquire() as connection:
            return [dict(row) for row in await connection.fetch("SELECT * FROM signups WHERE event_id = $1;", event_id)]

    async def get_event_by_id(self, event_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow("SELECT * FROM events WHERE event_id = $1;", event_id)
            return dict(row) if row else None
            
    # ... all other event functions ...

    # --- Squad & Guild Config Functions ---
    async def get_squads_with_members(self, event_id: int) -> List[Dict]:
        # ... implementation from previous version ...
        pass
            
    async def delete_squads_for_event(self, event_id: int):
        async with self.pool.acquire() as connection:
            await connection.execute("DELETE FROM squads WHERE event_id = $1;", event_id)

    # ... all other squad functions ...

    async def close(self):
        if self.pool:
            await self.pool.close()
            print("Database connection pool closed.")
