import asyncpg
import os
import datetime
import json
import httpx
from typing import List, Optional, Dict

# Static Definitions
ROLES = ["Commander", "Infantry", "Armour", "Recon", "Pathfinders", "Artillery"]
SUBCLASSES = {
    "Infantry": ["Anti-Tank", "Assault", "Automatic Rifleman", "Engineer", "Machine Gunner", "Medic", "Officer", "Rifleman", "Support"],
    "Armour": ["Tank Commander", "Crewman"],
    "Recon": ["Spotter", "Sniper"],
    "Pathfinders": ["Anti-Tank", "Assault", "Automatic Rifleman", "Engineer", "Machine Gunner", "Medic", "Officer", "Rifleman", "Support"],
    "Artillery": ["Anti-Tank", "Assault", "Automatic Rifleman", "Engineer", "Machine Gunner", "Medic", "Officer", "Rifleman", "Support"]
}
RESTRICTED_ROLES = ["Commander", "Recon", "Officer", "Tank Commander", "Pathfinders", "Artillery"]

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
                await connection.execute("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username VARCHAR(50) UNIQUE NOT NULL, hashed_password VARCHAR(255) NOT NULL, is_active BOOLEAN DEFAULT TRUE, is_admin BOOLEAN DEFAULT FALSE);")
                await connection.execute("CREATE TABLE IF NOT EXISTS guilds (guild_id BIGINT PRIMARY KEY, event_manager_role_ids BIGINT[], thread_creation_hours INT DEFAULT 24);")
                await connection.execute("""CREATE TABLE IF NOT EXISTS events (event_id SERIAL PRIMARY KEY, 
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
                        last_recreated_at TIMESTAMP WITH TIME ZONE, 
                        deleted_at TIMESTAMP WITH TIME ZONE DEFAULT NULL, 
                        locked_by_user_id INT REFERENCES users(id) ON DELETE SET NULL, 
                        locked_at TIMESTAMP WITH TIME ZONE
                    );
                """)
                await connection.execute("CREATE TABLE IF NOT EXISTS signups (signup_id SERIAL PRIMARY KEY, event_id INT REFERENCES events(event_id) ON DELETE CASCADE, user_id BIGINT NOT NULL, role_name VARCHAR(100), subclass_name VARCHAR(100), rsvp_status VARCHAR(10) NOT NULL, UNIQUE(event_id, user_id));")
                await connection.execute("CREATE TABLE IF NOT EXISTS squads (squad_id SERIAL PRIMARY KEY, event_id INT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE, name VARCHAR(100) NOT NULL, squad_type VARCHAR(50) NOT NULL);")
                await connection.execute("""
                    CREATE TABLE IF NOT EXISTS squad_members (
                        squad_member_id SERIAL PRIMARY KEY,
                        squad_id INT NOT NULL REFERENCES squads(squad_id) ON DELETE CASCADE,
                        user_id BIGINT NOT NULL,
                        assigned_role_name VARCHAR(100) NOT NULL,
                        startup_task VARCHAR(100),
                        UNIQUE(squad_id, user_id)
                    );
                """)
                await connection.execute("""
                    CREATE TABLE IF NOT EXISTS player_stats (
                        user_id BIGINT PRIMARY KEY,
                        accepted_count INT DEFAULT 0,
                        tentative_count INT DEFAULT 0,
                        declined_count INT DEFAULT 0,
                        last_signup_date TIMESTAMP WITH TIME ZONE
                    );
                """)
                # --- UPDATE: Add new columns to the history table ---
                await connection.execute("""
                    CREATE TABLE IF NOT EXISTS player_event_history (
                        history_id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        event_id INT NOT NULL,
                        event_title VARCHAR(255) NOT NULL,
                        event_time TIMESTAMP WITH TIME ZONE NOT NULL,
                        role_name VARCHAR(100),
                        subclass_name VARCHAR(100),
                        UNIQUE(user_id, event_id)
                    );
                """)
                print("Database setup is complete.")

    # --- User Management Functions ---
    # ... (no changes in this section)

    # --- Event & Signup Functions ---
    # ... (no changes to create_event, update_event, etc.)

    async def set_rsvp(self, event_id: int, user_id: int, new_status: str):
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                event_and_signup_data = await connection.fetchrow(
                    """
                    SELECT e.title, e.event_time, s.rsvp_status, s.role_name, s.subclass_name
                    FROM events e
                    LEFT JOIN signups s ON e.event_id = s.event_id AND s.user_id = $2
                    WHERE e.event_id = $1
                    """,
                    event_id, user_id
                )

                if not event_and_signup_data:
                    return

                old_status = event_and_signup_data['rsvp_status']

                if old_status == new_status:
                    return

                await connection.execute(
                    """
                    INSERT INTO signups (event_id, user_id, rsvp_status) VALUES ($1, $2, $3)
                    ON CONFLICT (event_id, user_id) DO UPDATE SET rsvp_status = EXCLUDED.rsvp_status;
                    """,
                    event_id, user_id, new_status
                )

                await self.update_player_stats(user_id, old_status, new_status)

                if new_status == RsvpStatus.ACCEPTED:
                    await connection.execute(
                        """
                        INSERT INTO player_event_history (user_id, event_id, event_title, event_time, role_name, subclass_name)
                        VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (user_id, event_id) DO NOTHING;
                        """,
                        user_id,
                        event_id,
                        event_and_signup_data['title'],
                        event_and_signup_data['event_time'],
                        event_and_signup_data['role_name'],
                        event_and_signup_data['subclass_name']
                    )
                elif old_status == RsvpStatus.ACCEPTED:
                    await connection.execute(
                        "DELETE FROM player_event_history WHERE user_id = $1 AND event_id = $2;",
                        user_id, event_id
                    )

    # --- UPDATE: Modify update_signup_role to sync with history ---
    async def update_signup_role(self, event_id: int, user_id: int, role_name: Optional[str], subclass_name: Optional[str]):
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                # Update the main signups table
                await connection.execute(
                    "UPDATE signups SET role_name = $1, subclass_name = $2 WHERE event_id = $3 AND user_id = $4;",
                    role_name, subclass_name, event_id, user_id
                )
                # Also update the permanent history table if an entry exists
                await connection.execute(
                    """
                    UPDATE player_event_history
                    SET role_name = $1, subclass_name = $2
                    WHERE user_id = $3 AND event_id = $4;
                    """,
                    role_name, subclass_name, user_id, event_id
                )

    # --- Player Statistics Functions ---
    # ... (no changes to update_player_stats, get_past_events_with_tentatives, etc.)

    # --- UPDATE: Modify get_accepted_events_for_user to select new columns ---
    async def get_accepted_events_for_user(self, user_id: int) -> List[Dict]:
        query = """
            SELECT event_title, event_time, role_name, subclass_name
            FROM player_event_history
            WHERE user_id = $1 ORDER BY event_time DESC;
        """
        async with self.pool.acquire() as connection:
            return [dict(row) for row in await connection.fetch(query, user_id)]
    
    # ... (rest of file is unchanged)
