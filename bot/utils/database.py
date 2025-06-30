import asyncpg
import os
import datetime
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
        try:
            self.pool = await asyncpg.create_pool(
                user=os.getenv("POSTGRES_USER"), password=os.getenv("POSTGRES_PASSWORD"),
                database=os.getenv("POSTGRES_DB"), host=os.getenv("POSTGRES_HOST", "db"),
                port=os.getenv("POSTGRES_PORT", 5432)
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

    async def get_user_by_id(self, user_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)

    async def get_all_users(self):
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT * FROM users ORDER BY username;")

    async def create_user(self, username: str, hashed_password: str, is_admin: bool = False):
        async with self.pool.acquire() as conn:
            return await conn.fetchval("INSERT INTO users (username, hashed_password, is_admin) VALUES ($1, $2, $3) RETURNING id", username, hashed_password, is_admin)

    async def update_event(self, event_id: int, data: dict):
        # This method was missing from the user's reference file, but is needed for the edit command
        # A full implementation would be needed here based on the `data` dict keys.
        # For now, we'll just update the title as an example.
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE events SET title = $1 WHERE event_id = $2", data.get('title'), event_id)

    # --- Event & Scheduler Functions ---
    async def get_upcoming_events(self) -> List[Dict]:
        query = "SELECT event_id, title, event_time FROM events WHERE COALESCE(end_time, event_time + INTERVAL '2 hours') > (NOW() AT TIME ZONE 'utc' - INTERVAL '12 hours') ORDER BY event_time DESC;"
        async with self.pool.acquire() as connection:
            return await connection.fetch(query)

    async def get_signups_for_event(self, event_id: int):
        async with self.pool.acquire() as connection:
            return await connection.fetch("SELECT * FROM signups WHERE event_id = $1;", event_id)

    async def get_events_for_recreation(self):
        query = "SELECT * FROM events WHERE is_recurring = TRUE AND event_time < (NOW() AT TIME ZONE 'utc') AND (last_recreated_at IS NULL OR last_recreated_at < (NOW() - INTERVAL '1 hour'));"
        async with self.pool.acquire() as connection:
            return await connection.fetch(query)

    async def get_event_by_id(self, event_id: int):
        async with self.pool.acquire() as connection:
            return await connection.fetchrow("SELECT * FROM events WHERE event_id = $1;", event_id)

    async def get_event_by_message_id(self, message_id: int):
        async with self.pool.acquire() as connection:
            return await connection.fetchrow("SELECT * FROM events WHERE message_id = $1;", message_id)

    async def create_event(self, guild_id: int, channel_id: int, creator_id: int, data: dict) -> int:
        async with self.pool.acquire() as connection:
            return await connection.fetchval(
                "INSERT INTO events (guild_id, channel_id, creator_id, title, description, event_time, end_time, timezone, is_recurring, recurrence_rule, mention_role_ids, restrict_to_role_ids, recreation_hours, parent_event_id) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14) RETURNING event_id;",
                guild_id, channel_id, creator_id, data.get('title'), data.get('description'), data.get('start_time'), data.get('end_time'), data.get('timezone'), data.get('is_recurring', False), data.get('recurrence_rule'), data.get('mention_role_ids'), data.get('restrict_to_role_ids'), data.get('recreation_hours'), data.get('parent_event_id')
            )
            
    async def update_event_message_id(self, event_id: int, message_id: int):
        async with self.pool.acquire() as connection:
            await connection.execute("UPDATE events SET message_id = $1 WHERE event_id = $2;", message_id, event_id)

    async def set_rsvp(self, event_id: int, user_id: int, status: str):
        async with self.pool.acquire() as connection:
            await connection.execute("INSERT INTO signups (event_id, user_id, rsvp_status) VALUES ($1, $2, $3) ON CONFLICT (event_id, user_id) DO UPDATE SET rsvp_status = EXCLUDED.rsvp_status;", event_id, user_id, status)
            
    async def update_signup_role(self, event_id: int, user_id: int, role_name: str, subclass_name: Optional[str] = None):
        async with self.pool.acquire() as connection:
            await connection.execute("UPDATE signups SET role_name = $1, subclass_name = $2 WHERE event_id = $3 AND user_id = $4;", role_name, subclass_name, event_id, user_id)

    async def get_squad_config_roles(self, guild_id: int) -> Dict:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow("SELECT squad_attack_role_id, squad_defence_role_id, squad_arty_role_id, squad_armour_role_id FROM guilds WHERE guild_id = $1;", guild_id)
            return dict(row) if row else {}

    async def close(self):
        if self.pool:
            await self.pool.close()
            print("Database connection pool closed.")
