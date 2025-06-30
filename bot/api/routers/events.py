import os
import traceback
from fastapi import APIRouter, Depends, HTTPException
from typing import List
import discord
from discord.ext import commands

from ...utils.database import Database
from .. import auth
from ..dependencies import get_db, get_bot
from ..models import Event, Signup, Channel, Squad, SquadBuildRequest, SendEmbedRequest, SquadMember

router = APIRouter(
    prefix="/api/events",
    tags=["events"],
    dependencies=[Depends(auth.get_current_active_user)],
    responses={404: {"description": "Not found"}},
)

GUILD_ID = int(os.getenv("GUILD_ID"))

@router.get("/", response_model=List[Event])
async def get_events(db: Database = Depends(get_db)):
    """
    Get a list of all upcoming, non-recurring events for the website dropdown.
    """
    # --- FIX: Changed this to call the new, correct database method ---
    events = await db.get_upcoming_events()
    return [dict(event) for event in events]


@router.get("/{event_id}/signups", response_model=List[Signup])
async def get_event_signups(event_id: int, db: Database = Depends(get_db), bot: commands.Bot = Depends(get_bot)):
    """
    Get the roster of accepted signups for a specific event.
    NOTE: This endpoint will not work correctly in the decoupled architecture
    as the 'bot' dependency is not available to the web service.
    This will need to be refactored later.
    """
    # For now, return an empty list to prevent crashes.
    return []

@router.get("/channels", response_model=List[Channel])
async def get_guild_channels(bot: commands.Bot = Depends(get_bot)):
    """
    Get a list of all text channels in the configured guild.
    NOTE: This endpoint will not work correctly in the decoupled architecture.
    """
    # For now, return an empty list to prevent crashes.
    return []

@router.post("/{event_id}/build-squads", response_model=List[Squad])
async def build_squads_for_event(
    event_id: int, 
    request: SquadBuildRequest,
    db: Database = Depends(get_db), 
    bot: commands.Bot = Depends(get_bot)
):
    """
    Triggers the squad building logic and returns the generated squads.
    NOTE: This endpoint will not work correctly in the decoupled architecture.
    """
    # For now, return an empty list to prevent crashes.
    return []

@router.post("/send-embed", status_code=204)
async def send_squad_embed(
    request: SendEmbedRequest,
    db: Database = Depends(get_db),
    bot: commands.Bot = Depends(get_bot)
):
    """
    Takes a generated squad composition and posts it as an embed to a specified channel.
    NOTE: This endpoint will not work correctly in the decoupled architecture.
    """
    # For now, return no content to prevent crashes.
    return
