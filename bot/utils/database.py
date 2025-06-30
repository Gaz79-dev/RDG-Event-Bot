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
        # ... The _initial_setup method remains the same ...
        pass
    
    # --- FIX: Added the correct database method to fetch events for the website ---
    async def get_upcoming_events(self) -> List[Dict]:
        """
        Fetches events that are active or upcoming.
        This includes events that have ended within the last 12 hours to allow for late squad building.
        """
        query = """
            SELECT event_id, title, event_time 
            FROM events
            WHERE COALESCE(end_time, event_time + INTERVAL '2 hours') > (NOW() AT TIME ZONE 'utc' - INTERVAL '12 hours')
            ORDER BY event_time DESC;
        """
        async with self.pool.acquire() as connection:
            return await connection.fetch(query)

    # --- All other database methods remain the same ---
    # ... (get_events_for_thread_creation, create_squad, etc.) ...
