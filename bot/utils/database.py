import asyncpg
import os
import datetime
from typing import List, Optional, Dict
from enum import Enum

# This file contains all database interaction logic for both the bot and the web API.

# --- Constants & Enums ---
class RsvpStatus(str, Enum):
    """Enum for RSVP statuses."""
    ACCEPTED = "Accepted"
    TENTATIVE = "Tentative"
    DECLINED = "Declined"

ROLES = ["Commander", "Infantry", "Armour", "Recon"]

SUBCLASSES = {
    "Infantry": ["Officer", "Rifleman", "Anti-Tank", "Assault", "Automatic Rifleman", "Engineer", "Machine Gunner", "Medic", "Support"],
    "Armour": ["Tank Commander", "Crewman"],
    "Recon": ["Spotter", "Sniper"]
}

RESTRICTED_ROLES = ["Commander", "Recon"]

# --- Database Class ---
class Database:
    """A database interface for the Discord event bot and web API."""
    def __init__(self):
        self.pool = None

    async def connect(self):
        """Establishes the connection pool to the database."""
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
        """Sets up all necessary tables if they don't exist."""
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY, username VARCHAR(50) UNIQUE NOT NULL,
                        hashed_password VARCHAR(255) NOT NULL, is_active BOOLEAN DEFAULT TRUE,
                        is_admin BOOLEAN DEFAULT FALSE
                    );
                    CREATE TABLE IF NOT EXISTS guilds (
                        guild_id BIGINT PRIMARY KEY, event_manager_role_ids BIGINT[],
                        commander_role_id BIGINT, recon_role_id BIGINT, officer_role_id BIGINT,
                        tank_commander_role_id BIGINT, thread_creation_hours INT DEFAULT 24,
                        squad_attack_role_id BIGINT, squad_defence_role_id BIGINT,
                        squad_arty_role_id BIGINT, squad_armour_role_id BIGINT
                    );
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
                    CREATE TABLE IF NOT EXISTS signups (
                        signup_id SERIAL PRIMARY KEY, event_id INT REFERENCES events(event_id) ON DELETE CASCADE,
                        user_id BIGINT NOT NULL, role_name VARCHAR(100), subclass_name VARCHAR(100),
                        rsvp_status VARCHAR(10) NOT NULL, UNIQUE(event_id, user_id)
                    );
                    CREATE TABLE IF NOT EXISTS squads (
                        squad_id SERIAL PRIMARY KEY, event_id INT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
                        name VARCHAR(100) NOT NULL, squad_type VARCHAR(50) NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS squad_members (
                        squad_member_id SERIAL PRIMARY KEY,
                        squad_id INT NOT NULL REFERENCES squads(squad_id) ON DELETE CASCADE,
                        user_id BIGINT NOT NULL, assigned_role_name VARCHAR(100) NOT NULL,
                        UNIQUE(squad_id, user_id)
                    );
                """)
                print("Database setup is complete.")

    # --- User Management Functions ---
    async def get_user_by_username(self, username: str):
        return await self.pool.fetchrow("SELECT * FROM users WHERE username = $1", username)

    async def get_user_by_id(self, user_id: int):
        return await self.pool.fetchrow("SELECT * FROM users WHERE id = $1", user_id)

    async def get_all_users(self):
        return await self.pool.fetch("SELECT id, username, is_active, is_admin FROM users ORDER BY username")

    async def create_user(self, username: str, hashed_password: str, is_admin: bool = False) -> int:
        return await self.pool.fetchval(
            "INSERT INTO users (username, hashed_password, is_admin) VALUES ($1, $2, $3) RETURNING id",
            username, hashed_password, is_admin
        )

    async def update_user_password(self, user_id: int, new_hashed_password: str):
        await self.pool.execute("UPDATE users SET hashed_password = $1 WHERE id = $2", new_hashed_password, user_id)

    async def update_user_status(self, user_id: int, is_active: Optional[bool], is_admin: Optional[bool]):
        if is_active is not None:
            await self.pool.execute("UPDATE users SET is_active = $1 WHERE id = $2", is_active, user_id)
        if is_admin is not None:
            await self.pool.execute("UPDATE users SET is_admin = $1 WHERE id = $2", is_admin, user_id)

    async def delete_user(self, user_id: int):
        await self.pool.execute("DELETE FROM users WHERE id = $1", user_id)

    # --- Event Functions ---
    async def create_event(self, guild_id, channel_id, creator_id, data):
        return await self.pool.fetchval(
            """INSERT INTO events (guild_id, channel_id, creator_id, title, description, event_time, end_time, timezone, is_recurring, recurrence_rule, mention_role_ids, restrict_to_role_ids, recreation_hours, parent_event_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14) RETURNING event_id""",
            guild_id, channel_id, creator_id, data['title'], data['description'], data['start_time'], data.get('end_time'),
            data['timezone'], data.get('is_recurring', False), data.get('recurrence_rule'), data.get('mention_role_ids', []),
            data.get('restrict_to_role_ids', []), data.get('recreation_hours'), data.get('parent_event_id')
        )

    async def get_event_by_id(self, event_id: int):
        return await self.pool.fetchrow("SELECT * FROM events WHERE event_id = $1", event_id)

    async def get_event_by_message_id(self, message_id: int):
        return await self.pool.fetchrow("SELECT * FROM events WHERE message_id = $1", message_id)
    
    async def get_upcoming_events(self):
        return await self.pool.fetch("SELECT event_id, title, event_time FROM events WHERE event_time > NOW() AND is_recurring = FALSE ORDER BY event_time ASC;")

    async def update_event_message_id(self, event_id: int, message_id: int):
        await self.pool.execute("UPDATE events SET message_id = $1 WHERE event_id = $2", message_id, event_id)

    async def update_event_thread_id(self, event_id: int, thread_id: int):
        await self.pool.execute("UPDATE events SET thread_id = $1 WHERE event_id = $2", thread_id, event_id)

    async def delete_event(self, event_id: int):
        await self.pool.execute("DELETE FROM events WHERE event_id = $1", event_id)

    # --- Signup Functions ---
    async def set_rsvp(self, event_id: int, user_id: int, status: RsvpStatus):
        await self.pool.execute(
            """INSERT INTO signups (event_id, user_id, rsvp_status) VALUES ($1, $2, $3)
               ON CONFLICT (event_id, user_id) DO UPDATE SET rsvp_status = $3""",
            event_id, user_id, status.value
        )

    async def update_signup_role(self, event_id: int, user_id: int, role: Optional[str], subclass: Optional[str]):
        await self.pool.execute(
            "UPDATE signups SET role_name = $3, subclass_name = $4 WHERE event_id = $1 AND user_id = $2",
            event_id, user_id, role, subclass
        )

    async def get_signups_for_event(self, event_id: int):
        return await self.pool.fetch("SELECT * FROM signups WHERE event_id = $1", event_id)

    # --- Squad Functions ---
    async def create_squad(self, event_id: int, name: str, squad_type: str):
        return await self.pool.fetchval(
            "INSERT INTO squads (event_id, name, squad_type) VALUES ($1, $2, $3) RETURNING squad_id",
            event_id, name, squad_type
        )

    async def add_squad_member(self, squad_id: int, user_id: int, role_name: str):
        await self.pool.execute(
            "INSERT INTO squad_members (squad_id, user_id, assigned_role_name) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
            squad_id, user_id, role_name
        )
    
    async def get_squad_by_id(self, squad_id: int) -> Optional[Dict]:
        row = await self.pool.fetchrow("SELECT * FROM squads WHERE squad_id = $1;", squad_id)
        return dict(row) if row else None

    async def get_squads_for_event(self, event_id: int):
        return await self.pool.fetch("SELECT * FROM squads WHERE event_id = $1 ORDER BY squad_id", event_id)

    async def get_squad_members(self, squad_id: int):
        return await self.pool.fetch("SELECT * FROM squad_members WHERE squad_id = $1", squad_id)

    async def delete_squads_for_event(self, event_id: int):
        await self.pool.execute("DELETE FROM squads WHERE event_id = $1", event_id)

    # --- Scheduler Functions ---
    async def get_events_for_thread_creation(self):
        return await self.pool.fetch(
            "SELECT * FROM events WHERE thread_created = FALSE AND thread_id IS NULL AND event_time <= NOW() + INTERVAL '24 hours'"
        )

    async def get_events_for_recreation(self):
        return await self.pool.fetch("SELECT * FROM events WHERE is_recurring = TRUE AND last_recreated_at IS NULL")

    async def get_events_for_deletion(self):
        return await self.pool.fetch("SELECT * FROM events WHERE is_recurring = FALSE AND event_time < NOW() - INTERVAL '7 days'")

    async def mark_thread_as_created(self, event_id: int):
        await self.pool.execute("UPDATE events SET thread_created = TRUE WHERE event_id = $1", event_id)

    async def update_last_recreated_at(self, event_id: int):
        await self.pool.execute("UPDATE events SET last_recreated_at = NOW() WHERE event_id = $1", event_id)

    # --- Guild Config Functions ---
    async def set_squad_config_role(self, guild_id: int, role_type: str, role_id: int):
        query = f"UPDATE guilds SET squad_{role_type}_role_id = $1 WHERE guild_id = $2"
        await self.pool.execute(query, role_id, guild_id)

    async def get_squad_config_roles(self, guild_id: int):
        return await self.pool.fetchrow(
            """SELECT squad_attack_role_id, squad_defence_role_id, squad_arty_role_id, squad_armour_role_id 
               FROM guilds WHERE guild_id = $1""", guild_id
        )

    # --- Close Connection ---
    async def close(self):
        """Closes the database connection pool."""
        if self.pool:
            await self.pool.close()
            print("Database connection pool closed.")
