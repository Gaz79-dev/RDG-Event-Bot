import asyncpg
import os
import datetime
import json # Import the json library
from typing import List, Optional, Dict

# --- Static Definitions ---
ROLES = ["Commander", "Infantry", "Armour", "Recon"]
SUBCLASSES = {
    "Infantry": ["Anti-Tank", "Assault", "Automatic Rifleman", "Engineer", "Machine Gunner", "Medic", "Officer", "Rifleman", "Support"],
    "Armour": ["Tank Commander", "Crewman"],
    "Recon": ["Spotter", "Sniper"]
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
        # --- FIX: Define an init function to set up JSON handling ---
        async def init_connection(conn):
            # This tells asyncpg to automatically encode/decode JSON data
            await conn.set_type_codec(
                'json',
                encoder=json.dumps,
                decoder=json.loads,
                schema='pg_catalog'
            )
            await conn.set_type_codec(
                'jsonb',
                encoder=json.dumps,
                decoder=json.loads,
                schema='pg_catalog'
            )

        try:
            # --- FIX: Pass the init function to the connection pool ---
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
    async def get_user_by_username(self, username: str):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM users WHERE username = $1", username)
    
    # ... All other methods from the previous version remain here, unchanged ...
    # For brevity, they are omitted, but your file should contain them.
    
    async def get_squads_with_members(self, event_id: int) -> List[Dict]:
        query = """
            SELECT 
                s.squad_id, s.name, s.squad_type,
                COALESCE(
                    (SELECT json_agg(sm.*) FROM squad_members sm WHERE sm.squad_id = s.squad_id),
                    '[]'::json
                ) as members
            FROM squads s
            WHERE s.event_id = $1
            GROUP BY s.squad_id
            ORDER BY s.squad_id;
        """
        async with self.pool.acquire() as connection:
            records = await connection.fetch(query, event_id)
            return [dict(record) for record in records]
            
    async def close(self):
        if self.pool:
            await self.pool.close()
            print("Database connection pool closed.")
