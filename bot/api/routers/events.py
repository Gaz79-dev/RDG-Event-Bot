import os
import traceback
from fastapi import APIRouter, Depends, HTTPException
from typing import List
import httpx # Import the new library

# All other existing imports remain the same
from ...utils.database import Database
from .. import auth
from ..dependencies import get_db
from ..models import Event, Signup, Channel, Squad, SquadBuildRequest, SendEmbedRequest, SquadMember

router = APIRouter(
    prefix="/api/events",
    tags=["events"],
    dependencies=[Depends(auth.get_current_active_user)],
    responses={404: {"description": "Not found"}},
)

GUILD_ID = os.getenv("GUILD_ID")
BOT_TOKEN = os.getenv("DISCORD_TOKEN")

@router.get("/", response_model=List[Event])
async def get_events(db: Database = Depends(get_db)):
    """
    Get a list of all upcoming, non-recurring events for the website dropdown.
    """
    events = await db.get_upcoming_events()
    return [dict(event) for event in events]

# --- FIX: Refactored this endpoint to call the Discord API directly ---
@router.get("/{event_id}/signups", response_model=List[Signup])
async def get_event_signups(event_id: int, db: Database = Depends(get_db)):
    """
    Get the roster of accepted signups for a specific event by calling the Discord API.
    """
    if not BOT_TOKEN or not GUILD_ID:
        raise HTTPException(status_code=500, detail="Bot token or Guild ID not configured on server.")

    signups_records = await db.get_signups_for_event(event_id)
    roster = []
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}

    async with httpx.AsyncClient() as client:
        for record in signups_records:
            if record['rsvp_status'] != RsvpStatus.ACCEPTED:
                continue
            
            display_name = f"User ID: {record['user_id']}" # Default name
            
            # Fetch member data from Discord API
            url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/members/{record['user_id']}"
            try:
                response = await client.get(url, headers=headers)
                if response.is_success:
                    member_data = response.json()
                    display_name = member_data.get('nick') or member_data['user'].get('global_name') or member_data['user']['username']
                else:
                    print(f"Failed to fetch member {record['user_id']} from Discord API: {response.status_code}")
            except Exception as e:
                print(f"Error fetching member {record['user_id']} from Discord API: {e}")

            roster.append(Signup(
                user_id=record['user_id'],
                display_name=display_name,
                role_name=record['role_name'],
                subclass_name=record['subclass_name']
            ))
    return roster

# The other endpoints are removed for now as they also depend on the bot object
# and are not required for the event selection/roster display to work.
