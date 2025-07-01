import os
import httpx
from fastapi import APIRouter, Depends, HTTPException
from typing import List

from bot.utils.database import Database, RsvpStatus
from bot.api import auth, squad_logic
from bot.api.dependencies import get_db
from bot.api.models import Event, Signup, Squad, SquadBuildRequest, RosterUpdateRequest, SendEmbedRequest, Channel

router = APIRouter(prefix="/api/events", tags=["events"], dependencies=[Depends(auth.get_current_active_user)])

GUILD_ID = os.getenv("GUILD_ID")
BOT_TOKEN = os.getenv("DISCORD_TOKEN")

@router.get("/", response_model=List[Event])
async def get_events(db: Database = Depends(get_db)):
    return await db.get_upcoming_events()

@router.get("/{event_id}/squads", response_model=List[Squad])
async def get_event_squads(event_id: int, db: Database = Depends(get_db)):
    return await db.get_squads_with_members(event_id)

@router.get("/{event_id}/signups", response_model=List[Signup])
async def get_event_signups(event_id: int, db: Database = Depends(get_db)):
    # ... This function remains the same ...

@router.post("/{event_id}/build-squads", response_model=List[Squad])
async def build_squads_for_event(event_id: int, request: SquadBuildRequest, db: Database = Depends(get_db)):
    try:
        return await squad_logic.run_web_draft(db, event_id, request)
    except Exception as e:
        print(f"Error during squad build process: {e}")
        raise HTTPException(status_code=500, detail="An internal error occurred during squad drafting.")

@router.post("/{event_id}/refresh-roster", response_model=List[Squad])
async def refresh_event_roster(event_id: int, request: RosterUpdateRequest, db: Database = Depends(get_db)):
    # ... This function remains the same ...

@router.get("/channels", response_model=List[Channel])
async def get_guild_channels():
    # ... This function remains the same ...

@router.post("/send-embed", status_code=204)
async def send_squad_embed(request: SendEmbedRequest):
    # ... This function remains the same ...
