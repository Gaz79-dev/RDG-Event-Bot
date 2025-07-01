import asyncpg
from typing import Optional, List, Dict, Any
from datetime import datetime
import os

class RsvpStatus:
    ACCEPTED = "Accepted"
    DECLINED = "Declined"
    TENTATIVE = "Tentative"

# Example role/subclass structure for reference
ROLES = [
    "Commander", "Officer", "Infantry", "Armour", "Recon", "Support", "Medic", "Engineer", "Anti-Tank", "Automatic Rifleman", "Machine Gunner", "Rifleman", "Assault", "Tank Commander", "Crewman", "Spotter", "Sniper"
]
SUBCLASSES = {
    "Infantry": ["Officer", "Rifleman", "Medic", "Engineer", "Anti-Tank", "Automatic Rifleman", "Machine Gunner", "Assault", "Support"],
    "Armour": ["Tank Commander", "Crewman"],
    "Recon": ["Spotter", "Sniper"]
}

class Database:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(dsn=self.dsn)

    async def close(self):
        if self.pool:
            await self.pool.close()

    # ------- EVENT CREATION & FETCH -------
    async def create_event(
        self,
        guild_id: int,
        channel_id: int,
        creator_id: int,
        data: dict
    ) -> int:
        """
        Creates a new event and returns its event_id.
        Expects data to have: title, start_datetime, finish_datetime, description, recurring, mention_role_ids, restrict_role_ids, timezone
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO events (
                    guild_id, channel_id, creator_id, title, event_time, finish_time, description, recurring, mention_role_ids, restrict_role_ids, timezone
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                RETURNING event_id
                """,
                guild_id,
                channel_id,
                creator_id,
                data.get("title"),
                data.get("start_datetime"),
                data.get("finish_datetime"),
                data.get("description"),
                data.get("recurring", False),
                data.get("mention_role_ids", []),
                data.get("restrict_role_ids", []),
                data.get("timezone"),
            )
            return row["event_id"]

    async def get_event_by_id(self, event_id: int) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM events WHERE event_id = $1", event_id
            )
            return dict(row) if row else None

    async def get_upcoming_events(self) -> List[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM events WHERE event_time > NOW() - INTERVAL '7 days' ORDER BY event_time ASC"
            )
            return [dict(r) for r in rows]

    # ------- SQUADS -------
    async def create_squad(self, event_id: int, name: str, squad_type: str) -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO squads (event_id, name, squad_type) VALUES ($1, $2, $3) RETURNING squad_id",
                event_id,
                name,
                squad_type,
            )
            return row["squad_id"]

    async def delete_squads_for_event(self, event_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM squads WHERE event_id = $1", event_id)

    async def get_squads_for_event(self, event_id: int) -> List[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM squads WHERE event_id = $1", event_id)
            return [dict(r) for r in rows]

    async def get_squad_by_name(self, event_id: int, name: str) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM squads WHERE event_id = $1 AND name = $2", event_id, name
            )
            return dict(row) if row else None

    async def get_squad_by_id(self, squad_id: int) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM squads WHERE squad_id = $1", squad_id
            )
            return dict(row) if row else None

    async def add_squad_member(self, squad_id: int, user_id: int, assigned_role_name: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO squad_members (squad_id, user_id, assigned_role_name)
                VALUES ($1, $2, $3)
                ON CONFLICT (squad_id, user_id) DO UPDATE SET assigned_role_name = EXCLUDED.assigned_role_name
                """,
                squad_id,
                user_id,
                assigned_role_name,
            )

    async def remove_user_from_all_squads(self, event_id: int, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM squad_members
                WHERE squad_id IN (SELECT squad_id FROM squads WHERE event_id = $1)
                AND user_id = $2
                """,
                event_id,
                user_id,
            )

    async def get_squads_with_members(self, event_id: int) -> List[dict]:
        async with self.pool.acquire() as conn:
            squads = await conn.fetch("SELECT * FROM squads WHERE event_id = $1", event_id)
            squads = [dict(s) for s in squads]
            for squad in squads:
                members = await conn.fetch(
                    "SELECT * FROM squad_members WHERE squad_id = $1", squad["squad_id"]
                )
                squad["members"] = [dict(m) for m in members]
            return squads

    async def get_squad_members(self, squad_id: int) -> List[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM squad_members WHERE squad_id = $1", squad_id
            )
            return [dict(r) for r in rows]

    # ------- SIGNUPS -------
    async def get_signups_for_event(self, event_id: int) -> List[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM signups WHERE event_id = $1", event_id
            )
            return [dict(r) for r in rows]

    async def get_signup(self, event_id: int, user_id: int) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM signups WHERE event_id = $1 AND user_id = $2",
                event_id,
                user_id,
            )
            return dict(row) if row else None

    # ------- CONFIGURATION -------
    async def get_squad_config_roles(self, guild_id: int) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM squad_config WHERE guild_id = $1
                """,
                guild_id,
            )
            return dict(row) if row else {}

    # ------- USERS (minimal) -------
    async def get_user_by_id(self, user_id: int) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
            return dict(row) if row else None

    async def add_user(self, user_id: int, username: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO users (user_id, username)
                VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username
                """,
                user_id,
                username,
            )
