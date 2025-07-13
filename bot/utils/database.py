import asyncpg
import os
import datetime
import json
import httpx
from typing import List, Optional, Dict
import uuid

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
                # --- ADDITION: New temporary table for reminder jobs ---
                await connection.execute("""
                    CREATE TABLE IF NOT EXISTS reminder_jobs (
                        job_id UUID PRIMARY KEY,
                        user_ids BIGINT[] NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc')
                    );
                """)
                print("Database setup is complete.")

    # --- User Management Functions ---
    async def get_user_by_username(self, username: str) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE username = $1", username)
            return dict(row) if row else None

    async def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
            return dict(row) if row else None

    async def get_all_users(self) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM users ORDER BY username;")
            return [dict(row) for row in rows]

    async def create_user(self, username: str, hashed_password: str, is_admin: bool = False) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "INSERT INTO users (username, hashed_password, is_admin) VALUES ($1, $2, $3) RETURNING id",
                username, hashed_password, is_admin
            )

    async def update_user_password(self, user_id: int, new_hashed_password: str):
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE users SET hashed_password = $1 WHERE id = $2", new_hashed_password, user_id)

    async def update_user_status(self, user_id: int, is_active: Optional[bool], is_admin: Optional[bool]):
        query_parts, params = [], []
        if is_active is not None: params.append(is_active); query_parts.append(f"is_active = ${len(params)}")
        if is_admin is not None: params.append(is_admin); query_parts.append(f"is_admin = ${len(params)}")
        if not query_parts: return
        params.append(user_id)
        query = f"UPDATE users SET {', '.join(query_parts)} WHERE id = ${len(params)}"
        async with self.pool.acquire() as conn: await conn.execute(query, *params)

    async def delete_user(self, user_id: int):
        async with self.pool.acquire() as conn: await conn.execute("DELETE FROM users WHERE id = $1", user_id)
 
    # --- Event & Signup Functions ---
    async def create_event(self, guild_id: int, channel_id: int, creator_id: int, data: Dict) -> int:
        query = """
            INSERT INTO events (guild_id, channel_id, creator_id, title, description, event_time, end_time, timezone, is_recurring, recurrence_rule, mention_role_ids, restrict_to_role_ids, recreation_hours)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13) RETURNING event_id;
        """
        async with self.pool.acquire() as connection:
            return await connection.fetchval(
                query, guild_id, channel_id, creator_id,
                data.get('title'), data.get('description'),
                data.get('event_time'), data.get('end_time'), data.get('timezone'),
                data.get('is_recurring'), data.get('recurrence_rule'),
                data.get('mention_role_ids', []), data.get('restrict_to_role_ids', []),
                data.get('recreation_hours')
            )

    async def update_event(self, event_id: int, data: Dict):
        """Updates an event's details in the database."""
        # This corrected version no longer resets thread information on every edit.
        query = """
            UPDATE events SET
                title = $1, description = $2, event_time = $3, end_time = $4, timezone = $5,
                is_recurring = $6, recurrence_rule = $7, mention_role_ids = $8,
                restrict_to_role_ids = $9, recreation_hours = $10
            WHERE event_id = $11;
        """
        async with self.pool.acquire() as connection:
            await connection.execute(
                query, data.get('title'), data.get('description'),
                data.get('event_time'), data.get('end_time'), data.get('timezone'),
                data.get('is_recurring'), data.get('recurrence_rule'),
                data.get('mention_role_ids', []),
                data.get('restrict_to_role_ids', []),
                data.get('recreation_hours'), event_id
            )

    async def update_event_message_id(self, event_id: int, message_id: int):
        async with self.pool.acquire() as connection:
            await connection.execute("UPDATE events SET message_id = $1 WHERE event_id = $2;", message_id, event_id)

    async def get_event_by_message_id(self, message_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM events WHERE message_id = $1;", message_id)
            return dict(row) if row else None

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
    
    async def get_upcoming_events(self) -> List[Dict]:
        query = "SELECT * FROM events WHERE deleted_at IS NULL AND COALESCE(end_time, event_time + INTERVAL '2 hours') > (NOW() AT TIME ZONE 'utc' - INTERVAL '12 hours');"
        async with self.pool.acquire() as connection:
            return [dict(row) for row in await connection.fetch(query)]

    async def get_signups_for_event(self, event_id: int) -> List[Dict]:
        query = "SELECT * FROM signups WHERE event_id = $1 ORDER BY role_name, subclass_name;"
        async with self.pool.acquire() as conn:
            return [dict(row) for row in await conn.fetch(query, event_id)]

    async def get_signup(self, event_id: int, user_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM signups WHERE event_id = $1 AND user_id = $2", event_id, user_id)
            return dict(row) if row else None
            
    async def get_event_by_id(self, event_id: int, include_deleted: bool = False) -> Optional[Dict]:
        query = "SELECT * FROM events WHERE event_id = $1"
        if not include_deleted:
            query += " AND deleted_at IS NULL"
        query += ";"

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, event_id)
            return dict(row) if row else None

    async def update_signup_role(self, event_id: int, user_id: int, role_name: Optional[str], subclass_name: Optional[str]):
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "UPDATE signups SET role_name = $1, subclass_name = $2 WHERE event_id = $3 AND user_id = $4;",
                    role_name, subclass_name, event_id, user_id
                )
                await connection.execute(
                    """
                    UPDATE player_event_history
                    SET role_name = $1, subclass_name = $2
                    WHERE user_id = $3 AND event_id = $4;
                    """,
                    role_name, subclass_name, user_id, event_id
                )

    async def get_recurring_parent_events(self) -> List[Dict]:
        """Gets all parent recurring event templates."""
        query = "SELECT * FROM events WHERE is_recurring = TRUE AND parent_event_id IS NULL AND deleted_at IS NULL ORDER BY event_time DESC;"
        async with self.pool.acquire() as connection:
            return [dict(row) for row in await connection.fetch(query)]

    async def get_deleted_events(self) -> List[Dict]:
        """Gets all soft-deleted events that can be restored."""
        query = "SELECT * FROM events WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC;"
        async with self.pool.acquire() as connection:
            return [dict(row) for row in await connection.fetch(query)]
    
    # --- Player Statistics Functions ---
    async def update_player_stats(self, user_id: int, old_status: Optional[str], new_status: str):
        decrement_col = f"{old_status.lower()}_count" if old_status else None
        increment_col = f"{new_status.lower()}_count"

        update_parts = [f"{increment_col} = player_stats.{increment_col} + 1"]
        if decrement_col:
            update_parts.append(f"{decrement_col} = GREATEST(0, player_stats.{decrement_col} - 1)")

        if new_status == RsvpStatus.ACCEPTED:
            update_parts.append("last_signup_date = (NOW() AT TIME ZONE 'utc')")
        
        query = f"""
            INSERT INTO player_stats (user_id, {increment_col}) VALUES ($1, 1)
            ON CONFLICT (user_id) DO UPDATE SET {', '.join(update_parts)};
        """
        
        async with self.pool.acquire() as connection:
            await connection.execute(query, user_id)

    async def get_all_player_stats(self) -> List[Dict]:
        async with self.pool.acquire() as connection:
            return [dict(row) for row in await connection.fetch("SELECT * FROM player_stats;")]
            
    async def get_accepted_events_for_user(self, user_id: int) -> List[Dict]:
        query = """
            SELECT event_title, event_time, role_name, subclass_name
            FROM player_event_history
            WHERE user_id = $1 ORDER BY event_time DESC;
        """
        async with self.pool.acquire() as connection:
            return [dict(row) for row in await connection.fetch(query, user_id)]
    
    async def get_all_rsvpd_user_ids_for_event(self, event_id: int) -> List[int]:
        query = "SELECT user_id FROM signups WHERE event_id = $1;"
        async with self.pool.acquire() as connection:
            records = await connection.fetch(query, event_id)
            return [record['user_id'] for record in records]

    # --- Reminder Job Functions ---
    async def create_reminder_job(self, job_id: uuid.UUID, user_ids: List[int]) -> None:
        """Creates a new reminder job in the temporary table."""
        query = "INSERT INTO reminder_jobs (job_id, user_ids) VALUES ($1, $2);"
        async with self.pool.acquire() as connection:
            await connection.execute(query, job_id, user_ids)

    async def get_reminder_job(self, job_id: uuid.UUID) -> Optional[List[int]]:
        """Retrieves the list of user IDs for a given reminder job."""
        query = "SELECT user_ids FROM reminder_jobs WHERE job_id = $1;"
        async with self.pool.acquire() as connection:
            record = await connection.fetchrow(query, job_id)
            return record['user_ids'] if record else None

    async def delete_reminder_job(self, job_id: uuid.UUID) -> None:
        """Deletes a reminder job after it has been processed."""
        query = "DELETE FROM reminder_jobs WHERE job_id = $1;"
        async with self.pool.acquire() as connection:
            await connection.execute(query, job_id)

    # --- Squad & Guild Config Functions ---
    async def force_unlock_all_events(self):
        query = "UPDATE events SET locked_by_user_id = NULL, locked_at = NULL WHERE locked_by_user_id IS NOT NULL;"
        async with self.pool.acquire() as connection:
            await connection.execute(query)
    
    async def get_all_roles_and_subclasses(self) -> Dict:
        return {"roles": ROLES, "subclasses": SUBCLASSES}

    async def create_squad(self, event_id: int, name: str, squad_type: str) -> int:
        async with self.pool.acquire() as connection:
            return await connection.fetchval("INSERT INTO squads (event_id, name, squad_type) VALUES ($1, $2, $3) RETURNING squad_id;", event_id, name, squad_type)

    async def add_squad_member(self, squad_id: int, user_id: int, assigned_role: str):
        async with self.pool.acquire() as connection:
            await connection.execute("INSERT INTO squad_members (squad_id, user_id, assigned_role_name) VALUES ($1, $2, $3) ON CONFLICT (squad_id, user_id) DO UPDATE SET assigned_role_name = EXCLUDED.assigned_role_name;", squad_id, user_id, assigned_role)
            
    async def update_squad_member_role(self, squad_member_id: int, new_role: str):
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE squad_members SET assigned_role_name = $1 WHERE squad_member_id = $2", new_role, squad_member_id)

    async def move_squad_member(self, squad_member_id: int, new_squad_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE squad_members SET squad_id = $1 WHERE squad_member_id = $2", new_squad_id, squad_member_id)

    async def get_squad_by_name(self, event_id: int, squad_name: str) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM squads WHERE event_id = $1 AND name = $2", event_id, squad_name)
            return dict(row) if row else None

    async def update_squad_member_task(self, squad_member_id: int, task: Optional[str]):
        query = "UPDATE squad_members SET startup_task = $1 WHERE squad_member_id = $2;"
        async with self.pool.acquire() as connection:
            await connection.execute(query, task, squad_member_id)

    async def get_event_lock_status(self, event_id: int) -> Optional[Dict]:
        query = "SELECT e.locked_by_user_id, e.locked_at, u.username as locked_by_username FROM events e LEFT JOIN users u ON e.locked_by_user_id = u.id WHERE e.event_id = $1;"
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, event_id)
            return dict(row) if row else None

    async def lock_event(self, event_id: int, user_id: int):
        query = "UPDATE events SET locked_by_user_id = $1, locked_at = (NOW() AT TIME ZONE 'utc') WHERE event_id = $2;"
        async with self.pool.acquire() as conn:
            await conn.execute(query, user_id, event_id)

    async def unlock_event(self, event_id: int):
        query = "UPDATE events SET locked_by_user_id = NULL, locked_at = NULL WHERE event_id = $1;"
        async with self.pool.acquire() as conn:
            await conn.execute(query, event_id)
    
    # --- Scheduler Functions ---
    async def get_active_events_with_threads(self) -> List[Dict]:
        query = """
            SELECT event_id, guild_id, thread_id FROM events
            WHERE thread_created = TRUE
              AND thread_id IS NOT NULL
              AND deleted_at IS NULL
              AND event_time > (NOW() AT TIME ZONE 'utc');
        """
        async with self.pool.acquire() as connection:
            return [dict(row) for row in await connection.fetch(query)]

    async def get_past_events_with_tentatives(self) -> List[Dict]:
        query = """
            SELECT s.event_id, s.user_id FROM signups s
            JOIN events e ON s.event_id = e.event_id
            WHERE s.rsvp_status = 'Tentative' AND e.end_time < (NOW() AT TIME ZONE 'utc');
        """
        async with self.pool.acquire() as connection:
            return [dict(row) for row in await connection.fetch(query)]

    async def set_thread_creation_hours(self, guild_id: int, hours: int):
        query = """
            INSERT INTO guilds (guild_id, thread_creation_hours) VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE SET thread_creation_hours = EXCLUDED.thread_creation_hours;
        """
        async with self.pool.acquire() as connection:
            await connection.execute(query, guild_id, hours)

    async def get_events_for_thread_creation(self) -> List[dict]:
        query = "SELECT e.event_id, e.guild_id, e.channel_id, e.message_id, e.title, e.event_time FROM events e JOIN guilds g ON e.guild_id = g.guild_id WHERE e.thread_created = FALSE AND e.deleted_at IS NULL AND (NOW() AT TIME ZONE 'utc') >= (e.event_time - (g.thread_creation_hours * INTERVAL '1 hour'));"
        async with self.pool.acquire() as connection:
            return [dict(row) for row in await connection.fetch(query)]

    async def mark_thread_created(self, event_id: int, thread_id: int):
        query = "UPDATE events SET thread_created = TRUE, thread_id = $1 WHERE event_id = $2;"
        async with self.pool.acquire() as connection:
            await connection.execute(query, thread_id, event_id)

    async def get_finished_events_for_cleanup(self) -> List[dict]:
        query = """
            SELECT event_id, thread_id, message_id, channel_id 
            FROM events
            WHERE 
                -- The event must have finished more than 2 hours ago
                COALESCE(end_time, event_time + INTERVAL '2 hours') < (NOW() AT TIME ZONE 'utc' - INTERVAL '2 hours')
            AND (
                -- It is a regular, non-recurring event
                is_recurring = FALSE 
                OR
                -- OR it is a child of a recurring event (and therefore should be deleted)
                parent_event_id IS NOT NULL
            );
        """
        async with self.pool.acquire() as connection:
            return [dict(row) for row in await connection.fetch(query)]

    async def soft_delete_event(self, event_id: int):
        query = "UPDATE events SET deleted_at = (NOW() AT TIME ZONE 'utc') WHERE event_id = $1;"
        async with self.pool.acquire() as connection:
            await connection.execute(query, event_id)

    async def restore_event(self, event_id: int):
        query = "UPDATE events SET deleted_at = NULL WHERE event_id = $1;"
        async with self.pool.acquire() as connection:
            await connection.execute(query, event_id)

    async def get_events_for_purging(self) -> List[Dict]:
        query = "SELECT event_id FROM events WHERE deleted_at IS NOT NULL AND deleted_at <= (NOW() AT TIME ZONE 'utc' - INTERVAL '7 days');"
        async with self.pool.acquire() as connection:
            return [dict(row) for row in await connection.fetch(query)]
    
    async def delete_event(self, event_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM events WHERE event_id = $1", event_id)

    async def get_events_for_recreation(self) -> List[dict]:
        query = "SELECT * FROM events WHERE is_recurring = TRUE AND deleted_at IS NULL;"
        async with self.pool.acquire() as connection:
            return [dict(row) for row in await connection.fetch(query)]

    async def update_last_recreated_at(self, event_id: int):
        query = "UPDATE events SET last_recreated_at = (NOW() AT TIME ZONE 'utc') WHERE event_id = $1;"
        async with self.pool.acquire() as connection:
            await connection.execute(query, event_id)
    
    async def get_squad_by_id(self, squad_id: int) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM squads WHERE squad_id = $1", squad_id)
            return dict(row) if row else None

    async def remove_user_from_all_squads(self, event_id: int, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM squad_members WHERE user_id = $1 AND squad_id IN (SELECT squad_id FROM squads WHERE event_id = $2)", user_id, event_id)
            
    async def get_squad_member_details(self, squad_member_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT sm.user_id, s.event_id FROM squad_members sm JOIN squads s ON sm.squad_id = s.squad_id WHERE sm.squad_member_id = $1", squad_member_id)
            return dict(row) if row else None

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

    async def delete_squads_for_event(self, event_id: int):
        async with self.pool.acquire() as connection:
            await connection.execute("DELETE FROM squads WHERE event_id = $1;", event_id)

    async def close(self):
        if self.pool: await self.pool.close(); print("Database connection pool closed.")
