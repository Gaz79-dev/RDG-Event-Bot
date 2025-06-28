import asyncpg
import os
import datetime
from typing import List, Optional, Dict

# --- Static Role and Sub-class Definitions ---
ROLES = ["Commander", "Infantry", "Armour", "Recon"]
SUBCLASSES = {
    "Infantry": ["Anti-Tank", "Assault", "Automatic Rifleman", "Engineer", "Machine Gunner", "Medic", "Officer", "Rifleman", "Support"],
    "Armour": ["Tank Commander", "Crewman"],
    "Recon": ["Spotter", "Sniper"]
}
RESTRICTED_ROLES = ["Commander", "Recon", "Officer", "Tank Commander"]

# --- RSVP Status Enum ---
class RsvpStatus:
    ACCEPTED = "Accepted"
    TENTATIVE = "Tentative"
    DECLINED = "Declined"

class Database:
    """A database interface for the Discord event bot."""
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
        """Sets up all necessary tables and performs schema migrations."""
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("""
                    CREATE TABLE IF NOT EXISTS guilds (
                        guild_id BIGINT PRIMARY KEY, event_manager_role_ids BIGINT[],
                        commander_role_id BIGINT, recon_role_id BIGINT, officer_role_id BIGINT,
                        tank_commander_role_id BIGINT, thread_creation_hours INT DEFAULT 24,
                        squad_attack_role_id BIGINT, squad_defence_role_id BIGINT,
                        squad_arty_role_id BIGINT, squad_armour_role_id BIGINT
                    );
                """)
                await connection.execute("ALTER TABLE guilds ADD COLUMN IF NOT EXISTS squad_attack_role_id BIGINT;")
                await connection.execute("ALTER TABLE guilds ADD COLUMN IF NOT EXISTS squad_defence_role_id BIGINT;")
                await connection.execute("ALTER TABLE guilds ADD COLUMN IF NOT EXISTS squad_arty_role_id BIGINT;")
                await connection.execute("ALTER TABLE guilds ADD COLUMN IF NOT EXISTS squad_armour_role_id BIGINT;")

                await connection.execute("""
                    CREATE TABLE IF NOT EXISTS events (
                        event_id SERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, creator_id BIGINT NOT NULL,
                        message_id BIGINT UNIQUE, channel_id BIGINT NOT NULL, thread_id BIGINT,
                        title VARCHAR(255) NOT NULL, description TEXT, 
                        event_time TIMESTAMP WITH TIME ZONE NOT NULL, end_time TIMESTAMP WITH TIME ZONE,
                        timezone VARCHAR(100), created_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc'),
                        thread_created BOOLEAN DEFAULT FALSE, is_recurring BOOLEAN DEFAULT FALSE,
                        recurrence_rule VARCHAR(50), mention_role_ids BIGINT[], restrict_to_role_ids BIGINT[],
                        recreation_hours INT, parent_event_id INT REFERENCES events(event_id) ON DELETE SET NULL,
                        last_recreated_at TIMESTAMP WITH TIME ZONE
                    );
                """)

                await connection.execute("""
                    CREATE TABLE IF NOT EXISTS signups (
                        signup_id SERIAL PRIMARY KEY, event_id INT REFERENCES events(event_id) ON DELETE CASCADE,
                        user_id BIGINT NOT NULL, role_name VARCHAR(100), subclass_name VARCHAR(100),
                        rsvp_status VARCHAR(10) NOT NULL, UNIQUE(event_id, user_id)
                    );
                """)
                
                try:
                    await connection.execute("ALTER TABLE signups DROP COLUMN IF EXISTS role_id, DROP COLUMN IF EXISTS subclass_id;")
                    await connection.execute("ALTER TABLE signups ADD COLUMN IF NOT EXISTS role_name VARCHAR(100), ADD COLUMN IF NOT EXISTS subclass_name VARCHAR(100);")
                except asyncpg.PostgresError:
                    pass

                await connection.execute("""
                    CREATE TABLE IF NOT EXISTS squads (
                        squad_id SERIAL PRIMARY KEY,
                        event_id INT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
                        name VARCHAR(100) NOT NULL, squad_type VARCHAR(50) NOT NULL
                    );
                """)
                await connection.execute("""
                    CREATE TABLE IF NOT EXISTS squad_members (
                        squad_member_id SERIAL PRIMARY KEY,
                        squad_id INT NOT NULL REFERENCES squads(squad_id) ON DELETE CASCADE,
                        user_id BIGINT NOT NULL, assigned_role_name VARCHAR(100) NOT NULL,
                        UNIQUE(squad_id, user_id)
                    );
                """)
                print("Database setup is complete.")

    # --- Squad Config Functions ---
    async def set_squad_config_role(self, guild_id: int, role_type: str, role_id: int):
        column_name = f"squad_{role_type}_role_id"
        async with self.pool.acquire() as connection:
            await connection.execute("INSERT INTO guilds (guild_id) VALUES ($1) ON CONFLICT (guild_id) DO NOTHING;", guild_id)
            await connection.execute(f"UPDATE guilds SET {column_name} = $1 WHERE guild_id = $2;", role_id, guild_id)

    async def get_squad_config_roles(self, guild_id: int) -> Dict:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow("SELECT squad_attack_role_id, squad_defence_role_id, squad_arty_role_id, squad_armour_role_id FROM guilds WHERE guild_id = $1;", guild_id)
            return dict(row) if row else {}

    # --- Squad Management Functions ---
    async def create_squad(self, event_id: int, name: str, squad_type: str) -> int:
        async with self.pool.acquire() as connection:
            return await connection.fetchval("INSERT INTO squads (event_id, name, squad_type) VALUES ($1, $2, $3) RETURNING squad_id;", event_id, name, squad_type)

    async def add_squad_member(self, squad_id: int, user_id: int, assigned_role: str):
        async with self.pool.acquire() as connection:
            await connection.execute("INSERT INTO squad_members (squad_id, user_id, assigned_role_name) VALUES ($1, $2, $3) ON CONFLICT (squad_id, user_id) DO UPDATE SET assigned_role_name = EXCLUDED.assigned_role_name;", squad_id, user_id, assigned_role)

    async def get_squads_for_event(self, event_id: int) -> List[Dict]:
        async with self.pool.acquire() as connection:
            return await connection.fetch("SELECT * FROM squads WHERE event_id = $1 ORDER BY squad_id;", event_id)

    async def get_squad_members(self, squad_id: int) -> List[Dict]:
        async with self.pool.acquire() as connection:
            return await connection.fetch("SELECT * FROM squad_members WHERE squad_id = $1;", squad_id)
            
    async def delete_squads_for_event(self, event_id: int):
        async with self.pool.acquire() as connection:
            await connection.execute("DELETE FROM squads WHERE event_id = $1;", event_id)
            
    # --- Other Functions ---
    async def get_signups_for_event(self, event_id: int):
        async with self.pool.acquire() as connection:
            return await connection.fetch("SELECT * FROM signups WHERE event_id = $1;", event_id)

    async def get_event_by_id(self, event_id: int):
        async with self.pool.acquire() as connection:
            return await connection.fetchrow("SELECT * FROM events WHERE event_id = $1;", event_id)
            
    async def update_signup_role(self, event_id: int, user_id: int, role_name: str, subclass_name: Optional[str] = None):
        async with self.pool.acquire() as connection:
            await connection.execute("UPDATE signups SET role_name = $1, subclass_name = $2 WHERE event_id = $3 AND user_id = $4;", role_name, subclass_name, event_id, user_id)
            
    async def set_rsvp(self, event_id: int, user_id: int, status: str):
        async with self.pool.acquire() as connection:
            await connection.execute("INSERT INTO signups (event_id, user_id, rsvp_status) VALUES ($1, $2, $3) ON CONFLICT (event_id, user_id) DO UPDATE SET rsvp_status = EXCLUDED.rsvp_status;", event_id, user_id, status)
    
    async def get_manager_role_ids(self, guild_id: int) -> List[int]:
        """Gets the list of event manager role IDs for a guild."""
        async with self.pool.acquire() as connection:
            role_ids = await connection.fetchval("SELECT event_manager_role_ids FROM guilds WHERE guild_id = $1;", guild_id)
            return role_ids or []

    async def set_manager_roles(self, guild_id: int, role_ids: List[int]):
        """Sets the event manager roles for a guild."""
        async with self.pool.acquire() as connection:
            await connection.execute("INSERT INTO guilds (guild_id) VALUES ($1) ON CONFLICT (guild_id) DO NOTHING;", guild_id)
            await connection.execute("UPDATE guilds SET event_manager_role_ids = $1 WHERE guild_id = $2;", role_ids, guild_id)
    
    # ... other existing functions like update_event, delete_event, etc.
