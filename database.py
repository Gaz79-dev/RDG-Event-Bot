import asyncpg
import os
import datetime
from typing import Optional, List

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
        """Establishes a connection pool to the PostgreSQL database and runs initial setup."""
        try:
            self.pool = await asyncpg.create_pool(
                user=os.getenv("POSTGRES_USER"),
                password=os.getenv("POSTGRES_PASSWORD"),
                database=os.getenv("POSTGRES_DB"),
                host=os.getenv("POSTGRES_HOST", "db"),
                port=os.getenv("POSTGRES_PORT", 5432)
            )
            print("Successfully connected to the PostgreSQL database.")
            await self._initial_setup()
        except Exception as e:
            print(f"Error: Could not connect to the PostgreSQL database. {e}")
            raise

    async def _initial_setup(self):
        """Sets up the necessary tables and initial data in the database."""
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                # Guilds table setup
                await connection.execute("""
                    CREATE TABLE IF NOT EXISTS guilds (
                        guild_id BIGINT PRIMARY KEY,
                        event_manager_role_id BIGINT,
                        commander_role_id BIGINT,
                        recon_role_id BIGINT,
                        officer_role_id BIGINT,
                        tank_commander_role_id BIGINT,
                        thread_creation_hours INT DEFAULT 24
                    );
                """)
                await connection.execute("ALTER TABLE guilds ADD COLUMN IF NOT EXISTS thread_creation_hours INT DEFAULT 24;")

                # Roles and Subclasses tables setup
                await connection.execute("""
                    CREATE TABLE IF NOT EXISTS roles ( role_id SERIAL PRIMARY KEY, name VARCHAR(100) UNIQUE NOT NULL );
                """)
                await connection.execute("""
                    CREATE TABLE IF NOT EXISTS subclasses ( subclass_id SERIAL PRIMARY KEY, role_id INT REFERENCES roles(role_id) ON DELETE CASCADE, name VARCHAR(100) NOT NULL );
                """)
                
                # Events table setup
                await connection.execute("""
                    CREATE TABLE IF NOT EXISTS events (
                        event_id SERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        creator_id BIGINT NOT NULL,
                        message_id BIGINT UNIQUE,
                        channel_id BIGINT NOT NULL,
                        thread_id BIGINT,
                        title VARCHAR(255) NOT NULL,
                        description TEXT, 
                        event_time TIMESTAMP WITH TIME ZONE NOT NULL,
                        end_time TIMESTAMP WITH TIME ZONE,
                        timezone VARCHAR(100),
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc'),
                        thread_created BOOLEAN DEFAULT FALSE,
                        is_recurring BOOLEAN DEFAULT FALSE,
                        recurrence_rule VARCHAR(50),
                        mention_role_ids BIGINT[],
                        restrict_to_role_ids BIGINT[],
                        recreation_hours INT,
                        parent_event_id INT REFERENCES events(event_id) ON DELETE SET NULL,
                        last_recreated_at TIMESTAMP WITH TIME ZONE
                    );
                """)
                
                # Add new columns for recurrence if they don't exist
                await connection.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS recreation_hours INT;")
                await connection.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS parent_event_id INT REFERENCES events(event_id) ON DELETE SET NULL;")
                await connection.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS last_recreated_at TIMESTAMP WITH TIME ZONE;")

                # Signups table setup
                await connection.execute("""
                    CREATE TABLE IF NOT EXISTS signups (
                        signup_id SERIAL PRIMARY KEY, event_id INT REFERENCES events(event_id) ON DELETE CASCADE,
                        user_id BIGINT NOT NULL, role_id INT REFERENCES roles(role_id), subclass_id INT REFERENCES subclasses(subclass_id),
                        rsvp_status VARCHAR(10) NOT NULL, UNIQUE(event_id, user_id)
                    );
                """)

                # Populate initial role data
                role_count = await connection.fetchval("SELECT COUNT(*) FROM roles;")
                if role_count == 0:
                    print("Populating initial role data...")
                    for role_name in ROLES:
                        await connection.execute("INSERT INTO roles (name) VALUES ($1) ON CONFLICT (name) DO NOTHING;", role_name)
                    for role_name, subclass_list in SUBCLASSES.items():
                        role_id = await connection.fetchval("SELECT role_id FROM roles WHERE name = $1;", role_name)
                        if role_id:
                            for subclass_name in subclass_list:
                                await connection.execute("INSERT INTO subclasses (role_id, name) VALUES ($1, $2);", role_id, subclass_name)
                print("Database setup is complete.")

    async def create_event(self, guild_id: int, channel_id: int, creator_id: int, data: dict) -> int:
        """Creates a new event in the database."""
        async with self.pool.acquire() as connection:
            # When creating a recurring event for the first time, its parent_event_id is NULL
            parent_id = data.get('parent_event_id')

            return await connection.fetchval(
                """
                INSERT INTO events (
                    guild_id, channel_id, creator_id, title, description, 
                    event_time, end_time, timezone, is_recurring, recurrence_rule,
                    mention_role_ids, restrict_to_role_ids, recreation_hours, parent_event_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                RETURNING event_id;
                """,
                guild_id, channel_id, creator_id, data.get('title'), data.get('description'),
                data.get('start_time'), data.get('end_time'), data.get('timezone'),
                data.get('is_recurring', False), data.get('recurrence_rule'),
                data.get('mention_role_ids'), data.get('restrict_to_role_ids'),
                data.get('recreation_hours'), parent_id
            )

    async def update_event(self, event_id: int, data: dict):
        """Updates an existing event in the database."""
        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                UPDATE events SET
                    title = $1, description = $2, event_time = $3, end_time = $4,
                    timezone = $5, is_recurring = $6, recurrence_rule = $7,
                    mention_role_ids = $8, restrict_to_role_ids = $9, recreation_hours = $10
                WHERE event_id = $11;
                """,
                data.get('title'), data.get('description'), data.get('start_time'), data.get('end_time'),
                data.get('timezone'), data.get('is_recurring', False), data.get('recurrence_rule'),
                data.get('mention_role_ids'), data.get('restrict_to_role_ids'),
                data.get('recreation_hours'), event_id
            )

    async def get_events_for_recreation(self):
        """Fetches recurring events that have passed and are due for recreation."""
        query = """
            SELECT * FROM events
            WHERE is_recurring = TRUE
            AND event_time < (NOW() AT TIME ZONE 'utc')
            AND (last_recreated_at IS NULL OR last_recreated_at < (NOW() - INTERVAL '1 hour'));
        """
        async with self.pool.acquire() as connection:
            return await connection.fetch(query)

    async def update_last_recreated_at(self, event_id: int):
        """Updates the last_recreated_at timestamp for an event."""
        async with self.pool.acquire() as connection:
            await connection.execute(
                "UPDATE events SET last_recreated_at = (NOW() AT TIME ZONE 'utc') WHERE event_id = $1;",
                event_id
            )

    # --- Other existing database functions ---
    async def _ensure_guild_exists(self, connection, guild_id: int):
        await connection.execute("INSERT INTO guilds (guild_id) VALUES ($1) ON CONFLICT (guild_id) DO NOTHING;", guild_id)

    async def set_thread_creation_hours(self, guild_id: int, hours: int):
        async with self.pool.acquire() as connection:
            await self._ensure_guild_exists(connection, guild_id)
            await connection.execute("UPDATE guilds SET thread_creation_hours = $1 WHERE guild_id = $2;", hours, guild_id)

    async def get_events_for_thread_creation(self):
        query = """
            SELECT e.*
            FROM events e
            JOIN guilds g ON e.guild_id = g.guild_id
            WHERE e.thread_created = FALSE
            AND e.event_time IS NOT NULL
            AND (e.event_time - (g.thread_creation_hours * INTERVAL '1 hour')) <= (NOW() AT TIME ZONE 'utc');
        """
        async with self.pool.acquire() as connection:
            return await connection.fetch(query)

    async def mark_thread_as_created(self, event_id: int):
        async with self.pool.acquire() as connection:
            await connection.execute("UPDATE events SET thread_created = TRUE WHERE event_id = $1;", event_id)

    async def set_manager_role(self, guild_id: int, discord_role_id: int):
        async with self.pool.acquire() as connection:
            await self._ensure_guild_exists(connection, guild_id)
            await connection.execute("UPDATE guilds SET event_manager_role_id = $1 WHERE guild_id = $2;", discord_role_id, guild_id)

    async def get_manager_role_id(self, guild_id: int) -> int | None:
        async with self.pool.acquire() as connection:
            return await connection.fetchval("SELECT event_manager_role_id FROM guilds WHERE guild_id = $1;", guild_id)

    async def set_restricted_role(self, guild_id: int, role_name: str, discord_role_id: int):
        column_name = role_name.lower().replace(" ", "_") + "_role_id"
        if column_name not in ["commander_role_id", "recon_role_id", "officer_role_id", "tank_commander_role_id"]:
            raise ValueError("Invalid restricted role name.")
        async with self.pool.acquire() as connection:
            await self._ensure_guild_exists(connection, guild_id)
            await connection.execute(f"UPDATE guilds SET {column_name} = $1 WHERE guild_id = $2;", discord_role_id, guild_id)

    async def get_required_role_id(self, guild_id: int, role_or_subclass_name: str) -> int | None:
        if role_or_subclass_name not in RESTRICTED_ROLES: return None
        column_name = role_or_subclass_name.lower().replace(" ", "_") + "_role_id"
        async with self.pool.acquire() as connection:
            return await connection.fetchval(f"SELECT {column_name} FROM guilds WHERE guild_id = $1;", guild_id)
            
    async def update_event_message_id(self, event_id: int, message_id: int):
        async with self.pool.acquire() as connection:
            await connection.execute("UPDATE events SET message_id = $1 WHERE event_id = $2;", message_id, event_id)

    async def update_event_thread_id(self, event_id: int, thread_id: int):
        async with self.pool.acquire() as connection:
            await connection.execute("UPDATE events SET thread_id = $1 WHERE event_id = $2;", thread_id, event_id)

    async def delete_event(self, event_id: int):
        async with self.pool.acquire() as connection:
            await connection.execute("DELETE FROM events WHERE event_id = $1;", event_id)

    async def get_event_by_id(self, event_id: int):
        async with self.pool.acquire() as connection:
            return await connection.fetchrow("SELECT * FROM events WHERE event_id = $1;", event_id)

    async def get_event_by_message_id(self, message_id: int):
        async with self.pool.acquire() as connection:
            return await connection.fetchrow("SELECT * FROM events WHERE message_id = $1;", message_id)

    async def set_rsvp(self, event_id: int, user_id: int, status: str):
        async with self.pool.acquire() as connection:
            await connection.execute("INSERT INTO signups (event_id, user_id, rsvp_status) VALUES ($1, $2, $3) ON CONFLICT (event_id, user_id) DO UPDATE SET rsvp_status = EXCLUDED.rsvp_status, role_id = NULL, subclass_id = NULL;", event_id, user_id, status)

    async def update_signup_role(self, event_id: int, user_id: int, role_name: str, subclass_name: str = None):
        async with self.pool.acquire() as connection:
            role_id = await connection.fetchval("SELECT role_id FROM roles WHERE name = $1;", role_name)
            subclass_id = None
            if subclass_name:
                subclass_id = await connection.fetchval("SELECT subclass_id FROM subclasses WHERE role_id = $1 AND name = $2;", role_id, subclass_name)
            await connection.execute("UPDATE signups SET role_id = $1, subclass_id = $2 WHERE event_id = $3 AND user_id = $4;", role_id, subclass_id, event_id, user_id)

    async def get_signups_for_event(self, event_id: int):
        async with self.pool.acquire() as connection:
            return await connection.fetch("SELECT s.user_id, s.rsvp_status, r.name as role_name, sc.name as subclass_name FROM signups s LEFT JOIN roles r ON s.role_id = r.role_id LEFT JOIN subclasses sc ON s.subclass_id = sc.subclass_id WHERE s.event_id = $1 ORDER BY r.name, sc.name;", event_id)

    async def close(self):
        if self.pool: await self.pool.close(); print("Database connection pool closed.")
