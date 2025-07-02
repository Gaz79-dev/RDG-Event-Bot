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
                data.get('start_time'), data.get('end_time'), data.get('timezone'),
                data.get('is_recurring'), data.get('recurrence_rule'),
                data.get('mention_role_ids', []), data.get('restrict_to_role_ids', []),
                data.get('recreation_hours')
            )

    async def update_event(self, event_id: int, data: Dict):
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
                data.get('start_time'), data.get('end_time'), data.get('timezone'),
                data.get('is_recurring'), data.get('recurrence_rule'),
                data.get('mention_role_ids', []), data.get('restrict_to_role_ids', []),
                data.get('recreation_hours'), event_id
            )

    async def update_event_message_id(self, event_id: int, message_id: int):
        async with self.pool.acquire() as connection:
            await connection.execute("UPDATE events SET message_id = $1 WHERE event_id = $2;", message_id, event_id)

    async def get_event_by_message_id(self, message_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM events WHERE message_id = $1;", message_id)
            return dict(row) if row else None

    async def set_rsvp(self, event_id: int, user_id: int, status: str):
        query = """
            INSERT INTO signups (event_id, user_id, rsvp_status)
            VALUES ($1, $2, $3)
            ON CONFLICT (event_id, user_id)
            DO UPDATE SET rsvp_status = EXCLUDED.rsvp_status;
        """
        async with self.pool.acquire() as connection:
            await connection.execute(query, event_id, user_id, status)
    
    async def get_upcoming_events(self) -> List[Dict]:
        query = "SELECT event_id, title, event_time FROM events WHERE COALESCE(end_time, event_time + INTERVAL '2 hours') > (NOW() AT TIME ZONE 'utc' - INTERVAL '12 hours') ORDER BY event_time DESC;"
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
            
    async def get_event_by_id(self, event_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM events WHERE event_id = $1;", event_id)
            return dict(row) if row else None

    async def update_signup_role(self, event_id: int, user_id: int, role_name: Optional[str], subclass_name: Optional[str]):
        async with self.pool.acquire() as connection:
            await connection.execute("UPDATE signups SET role_name = $1, subclass_name = $2 WHERE event_id = $3 AND user_id = $4;", role_name, subclass_name, event_id, user_id)

    # --- Squad & Guild Config Functions ---
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

    # Add this method to your Database class:
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

    async def get_squad_config_roles(self, guild_id: int) -> Optional[Dict]:
        """Retrieves the configured specialty squad roles for a guild."""
        query = """
            SELECT squad_attack_role_id, squad_defence_role_id, squad_arty_role_id, squad_armour_role_id
            FROM guilds WHERE guild_id = $1;
        """
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(query, guild_id)
            return dict(row) if row else None

    async def set_squad_config_role(self, guild_id: int, role_type: str, role_id: int):
        """Sets a specific specialty squad role for a guild."""
        column_map = {
            "attack": "squad_attack_role_id",
            "defence": "squad_defence_role_id",
            "arty": "squad_arty_role_id",
            "armour": "squad_armour_role_id"
        }
        column_name = column_map.get(role_type)
        if not column_name:
            return

        query = f"""
            INSERT INTO guilds (guild_id, {column_name})
            VALUES ($1, $2)
            ON CONFLICT (guild_id)
            DO UPDATE SET {column_name} = EXCLUDED.{column_name};
        """
        async with self.pool.acquire() as connection:
            await connection.execute(query, guild_id, role_id)
    
    async def delete_squads_for_event(self, event_id: int):
        async with self.pool.acquire() as connection:
            await connection.execute("DELETE FROM squads WHERE event_id = $1;", event_id)

    async def close(self):
        if self.pool: await self.pool.close(); print("Database connection pool closed.")
