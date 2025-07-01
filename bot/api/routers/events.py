import os
import httpx
from fastapi import APIRouter, Depends, HTTPException
from typing import List

# Use absolute imports from the 'bot' package root
from bot.utils.database import Database, RsvpStatus
from bot.api import auth
from bot.api.dependencies import get_db
from bot.api.models import Event, Signup, Squad, SquadBuildRequest, RosterUpdateRequest, SendEmbedRequest, Channel
from bot.api import squad_logic

router = APIRouter(
    prefix="/api/events",
    tags=["events"],
    dependencies=[Depends(auth.get_current_active_user)],
    responses={404: {"description": "Not found"}},
)

# Load constants from environment variables
GUILD_ID = os.getenv("GUILD_ID")
BOT_TOKEN = os.getenv("DISCORD_TOKEN")

@router.get("/", response_model=List[Event])
async def get_events(db: Database = Depends(get_db)):
    """Gets all upcoming and recently passed events."""
    events = await db.get_upcoming_events()
    return events

@router.get("/{event_id}/squads", response_model=List[Squad])
async def get_event_squads(event_id: int, db: Database = Depends(get_db)):
    """Gets any previously built squads for an event to persist the layout."""
    squads = await db.get_squads_with_members(event_id)
    return squads

@router.get("/{event_id}/signups", response_model=List[Signup])
async def get_event_signups(event_id: int, db: Database = Depends(get_db)):
    """Gets the roster of accepted signups for an event from the database and Discord."""
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
            except Exception as e:
                print(f"Error fetching member {record['user_id']}: {e}")
                
            roster.append(Signup(
                user_id=record['user_id'],
                display_name=display_name,
                role_name=record['role_name'],
                subclass_name=record['subclass_name']
            ))
    return roster

@router.post("/{event_id}/build-squads", response_model=List[Squad])
async def build_squads_for_event(event_id: int, request: SquadBuildRequest, db: Database = Depends(get_db)):
    """Triggers the squad building logic and returns the generated squads."""
    try:
        squads_with_members = await squad_logic.run_web_draft(db, event_id, request)
        return squads_with_members
    except Exception as e:
        print(f"Error during squad build process: {e}")
        raise HTTPException(status_code=500, detail="An internal error occurred during squad drafting.")

@router.post("/{event_id}/refresh-roster", response_model=List[Squad])
async def refresh_event_roster(event_id: int, request: RosterUpdateRequest, db: Database = Depends(get_db)):
    """Refreshes the roster, removing unavailable players and adding new ones to reserves."""
    current_member_ids = {member.user_id for squad in request.squads for member in squad.members}
    latest_signups = await db.get_signups_for_event(event_id)
    accepted_user_ids = {s['user_id'] for s in latest_signups if s['rsvp_status'] == RsvpStatus.ACCEPTED}
    
    users_to_remove = current_member_ids - accepted_user_ids
    for user_id in users_to_remove:
        await db.remove_user_from_all_squads(event_id, user_id)
        
    new_users = accepted_user_ids - current_member_ids
    if new_users:
        reserves_squad = await db.get_squad_by_name(event_id, "Reserves")
        if reserves_squad:
            for user_id in new_users:
                signup = await db.get_signup(event_id, user_id)
                if signup:
                    role_name = signup.get('subclass_name') or signup.get('role_name', 'Unassigned')
                    await db.add_squad_member(reserves_squad['squad_id'], user_id, role_name)
                
    return await db.get_squads_with_members(event_id)

@router.get("/channels", response_model=List[Channel])
async def get_guild_channels():
    """Gets a list of text channels from the Discord server."""
    if not BOT_TOKEN or not GUILD_ID:
        raise HTTPException(status_code=500, detail="Bot token or Guild ID not configured on server.")
    
    url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/channels"
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            all_channels = response.json()
            text_channels = [Channel(id=c['id'], name=c['name']) for c in all_channels if c['type'] == 0]
            return sorted(text_channels, key=lambda c: c.name)
        except Exception as e:
            print(f"Error fetching channels from Discord API: {e}")
            raise HTTPException(status_code=502, detail="Failed to fetch channels from Discord.")

@router.post("/send-embed", status_code=204)
async def send_squad_embed(request: SendEmbedRequest):
    """Sends the finalized squad composition as an embed to a Discord channel."""
    if not BOT_TOKEN:
        raise HTTPException(status_code=500, detail="Bot token not configured on server.")

    url = f"https://discord.com/api/v10/channels/{request.channel_id}/messages"
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    
    fields = []
    for squad in request.squads:
        if squad.squad_type == "Reserves": continue # Don't include reserves in the final embed
        member_list = [f"**{m.assigned_role_name}:** {m.display_name}" for m in squad.members]
        value = "\n".join(member_list) or "Empty"
        fields.append({"name": f"__**{squad.name}**__ ({squad.squad_type})", "value": value, "inline": True})
        
    embed_payload = {
        "embeds": [{
            "title": "🛠️ Finalized Team Composition",
            "description": "The following squads have been finalized for the event.",
            "color": 15844367,
            "fields": fields
        }]
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=embed_payload)
            response.raise_for_status()
        except Exception as e:
            print(f"Error sending embed to Discord API: {e}")
            raise HTTPException(status_code=502, detail="Failed to send embed to Discord.")
    return
