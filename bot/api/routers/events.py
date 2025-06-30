import os
import httpx
from fastapi import APIRouter, Depends, HTTPException
from typing import List

# --- FIX: Import new squad logic and models ---
from bot.api import squad_logic
from bot.utils.database import Database, RsvpStatus
from bot.api import auth
from bot.api.dependencies import get_db
from bot.api.models import Event, Signup, Squad, SquadBuildRequest

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
    events = await db.get_upcoming_events()
    return [dict(event) for event in events]

@router.get("/{event_id}/signups", response_model=List[Signup])
async def get_event_signups(event_id: int, db: Database = Depends(get_db)):
    if not BOT_TOKEN or not GUILD_ID:
        raise HTTPException(status_code=500, detail="Bot token or Guild ID not configured on server.")
    signups_records = await db.get_signups_for_event(event_id)
    roster, headers = [], {"Authorization": f"Bot {BOT_TOKEN}"}
    async with httpx.AsyncClient() as client:
        for record in signups_records:
            if record['rsvp_status'] != RsvpStatus.ACCEPTED: continue
            display_name = f"User ID: {record['user_id']}"
            url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/members/{record['user_id']}"
            try:
                response = await client.get(url, headers=headers)
                if response.is_success:
                    member_data = response.json()
                    display_name = member_data.get('nick') or member_data['user'].get('global_name') or member_data['user']['username']
            except Exception as e: print(f"Error fetching member {record['user_id']}: {e}")
            roster.append(Signup(user_id=record['user_id'], display_name=display_name, role_name=record['role_name'], subclass_name=record['subclass_name']))
    return roster

# --- FIX: Added the build-squads endpoint with new logic ---
@router.post("/{event_id}/build-squads", response_model=List[Squad])
async def build_squads_for_event(
    event_id: int, 
    request: SquadBuildRequest,
    db: Database = Depends(get_db)
):
    """
    Triggers the squad building logic and returns the generated squads.
    """
    try:
        squads_with_members = await squad_logic.run_web_draft(db, event_id, request)
        return squads_with_members
    except Exception as e:
        print(f"Error during squad build process: {e}")
        raise HTTPException(status_code=500, detail="An internal error occurred during squad drafting.")
