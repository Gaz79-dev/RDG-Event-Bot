import os
import httpx
import datetime
import asyncio
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional

import discord

# Use absolute imports from the 'bot' package root
from bot.utils.database import Database, RsvpStatus
from bot.api import auth, squad_logic
from bot.api.dependencies import get_db
from bot.api.models import Event, Signup, Squad, SquadBuildRequest, RosterUpdateRequest, SendEmbedRequest, Channel, User, EventLockStatus, EventUpdate

# Import the emoji mapping for use in the embed
from bot.cogs.event_management import EMOJI_MAPPING

router = APIRouter(
    prefix="/api/events",
    tags=["events"],
    dependencies=[Depends(auth.get_current_active_user)],
)

# Load constants from environment variables
GUILD_ID = os.getenv("GUILD_ID")
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
LOCK_TIMEOUT_MINUTES = 15

# --- Locking Dependency ---
async def check_event_lock(event_id: int, current_user: User = Depends(auth.get_current_admin_user), db: Database = Depends(get_db)):
    """
    Dependency that checks if an event is locked.
    If it's locked by another user, it raises an HTTP 423 exception.
    If the lock is expired or orphaned, it allows the operation to proceed.
    """
    lock_status = await db.get_event_lock_status(event_id)
    
    # Proceed if the event is not locked
    if not lock_status or lock_status.get('locked_by_user_id') is None:
        return

    # Proceed if the lock belongs to the current user
    if lock_status.get('locked_by_user_id') == current_user.id:
        return
        
    # Check for an orphaned lock (user ID exists, but user record does not)
    # The LEFT JOIN in the DB query results in username being None if the user was deleted.
    if lock_status.get('locked_by_username') is None:
        await db.unlock_event(event_id) # Proactively clear the orphaned lock
        return

    # Check if the lock has expired
    if lock_status.get('locked_at'):
        lock_age = datetime.datetime.now(datetime.timezone.utc) - lock_status['locked_at']
        if lock_age.total_seconds() > LOCK_TIMEOUT_MINUTES * 60:
            return # Expired lock is treated as unlocked

    # If all checks fail, the event is actively locked by another user.
    raise HTTPException(
        status_code=status.HTTP_423_LOCKED,
        detail=f"Event is locked for editing by {lock_status.get('locked_by_username', 'another user')}.",
    )

# --- API Routes ---

@router.get("", response_model=List[Event])
async def get_events(db: Database = Depends(get_db)):
    """Gets all upcoming and recently passed events."""
    return await db.get_upcoming_events()

@router.get("/recurring", response_model=List[Event], dependencies=[Depends(auth.get_current_admin_user)])
async def get_recurring_events(db: Database = Depends(get_db)):
    """Gets all parent recurring event templates."""
    return await db.get_recurring_parent_events()

@router.get("/deleted", response_model=List[Event], dependencies=[Depends(auth.get_current_admin_user)])
async def get_deleted_events_for_restore(db: Database = Depends(get_db)):
    """Gets all soft-deleted events."""
    return await db.get_deleted_events()

@router.get("/{event_id}", response_model=Event, dependencies=[Depends(auth.get_current_admin_user)])
async def get_event_details(event_id: int, db: Database = Depends(get_db)):
    """Gets all details for a single event."""
    event = await db.get_event_by_id(event_id, include_deleted=True)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event

@router.put("/{event_id}", response_model=Event, dependencies=[Depends(auth.get_current_admin_user)])
async def update_event_details(event_id: int, event_data: EventUpdate, db: Database = Depends(get_db)):
    """Updates the details of a recurring event template."""
    # The Pydantic model automatically converts the dict to the right format
    await db.update_event(event_id, event_data.model_dump())
    return await get_event_details(event_id, db)

@router.get("/{event_id}/lock-status", response_model=EventLockStatus)
async def get_lock_status(event_id: int, db: Database = Depends(get_db)):
    """Checks who currently has the event locked."""
    lock_info = await db.get_event_lock_status(event_id)
    if not lock_info or not lock_info.get('locked_by_user_id') or not lock_info.get('locked_at'):
        return EventLockStatus(is_locked=False)
    
    lock_age = datetime.datetime.now(datetime.timezone.utc) - lock_info['locked_at']
    if lock_age.total_seconds() > LOCK_TIMEOUT_MINUTES * 60:
        return EventLockStatus(is_locked=False) # Expired lock is treated as not locked

    return EventLockStatus(
        is_locked=True,
        locked_by_user_id=lock_info['locked_by_user_id'],
        locked_by_username=lock_info.get('locked_by_username')
    )

@router.post("/{event_id}/lock", status_code=204, dependencies=[Depends(check_event_lock)])
async def lock_event(event_id: int, current_user: User = Depends(auth.get_current_admin_user), db: Database = Depends(get_db)):
    """Acquires or refreshes a lock on an event for the current user."""
    await db.lock_event(event_id, current_user.id)

@router.post("/{event_id}/unlock", status_code=204)
async def unlock_event(event_id: int, current_user: User = Depends(auth.get_current_admin_user), db: Database = Depends(get_db)):
    """Releases the lock on an event if the current user holds it."""
    lock_status = await db.get_event_lock_status(event_id)
    if lock_status and lock_status.get('locked_by_user_id') == current_user.id:
        await db.unlock_event(event_id)

@router.post("/force-unlock-all", status_code=204, dependencies=[Depends(auth.get_current_admin_user)])
async def force_unlock_all_events_endpoint(db: Database = Depends(get_db)):
    """
    FOR DEBUGGING: A global override to forcibly unlock all locked events.
    """
    await db.force_unlock_all_events()
    print("ADMIN ACTION: All events were force-unlocked.")
    return

@router.get("/{event_id}/squads", response_model=List[Squad])
async def get_event_squads(event_id: int, db: Database = Depends(get_db)):
    """Gets any previously built squads for an event to persist the layout."""
    return await db.get_squads_with_members(event_id)

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

@router.post("/{event_id}/build-squads", response_model=List[Squad], dependencies=[Depends(check_event_lock)])
async def build_squads_for_event(event_id: int, request: SquadBuildRequest, db: Database = Depends(get_db)):
    """Triggers the squad building logic and returns the generated squads."""
    try:
        return await squad_logic.run_web_draft(db, event_id, request)
    except Exception as e:
        print(f"Error during squad build process: {e}")
        raise HTTPException(status_code=500, detail="An internal error occurred during squad drafting.")

@router.post("/{event_id}/refresh-roster", response_model=List[Squad], dependencies=[Depends(check_event_lock)])
async def refresh_event_roster(event_id: int, request: RosterUpdateRequest, db: Database = Depends(get_db)):
    """
    Refreshes the roster, removing unavailable players and adding new ones to reserves.
    """
    current_member_ids = {member.user_id for squad in request.squads for member in squad.members}
    latest_signups = await db.get_signups_for_event(event_id)
    accepted_user_ids = {s['user_id'] for s in latest_signups if s['rsvp_status'] == RsvpStatus.ACCEPTED}

    users_to_remove = current_member_ids - accepted_user_ids
    for user_id in users_to_remove:
        await db.remove_user_from_all_squads(event_id, user_id)

    squads_with_members = await db.get_squads_with_members(event_id)
    all_current_db_member_ids = {member['user_id'] for squad in squads_with_members for member in squad.get('members', [])}

    new_users = accepted_user_ids - all_current_db_member_ids
    if new_users:
        reserves_squad = await db.get_squad_by_name(event_id, "Reserves")
        if reserves_squad:
            for user_id in new_users:
                signup = await db.get_signup(event_id, user_id)
                if signup:
                    role_name = signup.get('subclass_name') or signup.get('role_name', 'Unassigned')
                    await db.add_squad_member(reserves_squad['squad_id'], user_id, role_name)

    return await db.get_squads_with_members(event_id)

# In bot/api/routers/events.py
@router.get("/channels", response_model=List[Channel])
async def get_guild_channels():
    """Gets a list of text channels and active threads from the Discord server."""
    if not BOT_TOKEN or not GUILD_ID:
        raise HTTPException(status_code=500, detail="Bot token or Guild ID not configured on server.")
    
    url_channels = f"https://discord.com/api/v10/guilds/{GUILD_ID}/channels"
    url_threads = f"https://discord.com/api/v10/guilds/{GUILD_ID}/threads/active"
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    
    async with httpx.AsyncClient() as client:
        try:
            # Fetch both channels and active threads in parallel
            res_channels_task = client.get(url_channels, headers=headers)
            res_threads_task = client.get(url_threads, headers=headers)
            res_channels, res_threads = await asyncio.gather(res_channels_task, res_threads_task)

            res_channels.raise_for_status()
            res_threads.raise_for_status()

            all_channels = res_channels.json()
            active_threads = res_threads.json().get('threads', [])

            # Create a map of category IDs to names
            categories = {c['id']: c['name'] for c in all_channels if c['type'] == 4}

            processed_list = []
            # Process standard text channels
            for c in all_channels:
                if c['type'] == 0: # GUILD_TEXT
                    category_name = categories.get(c.get('parent_id'))
                    processed_list.append(Channel(id=c['id'], name=c['name'], category=category_name))
            
            # Process active threads
            for t in active_threads:
                if t['type'] in [11, 12]: # PUBLIC_THREAD or PRIVATE_THREAD
                    category_name = categories.get(t.get('parent_id'))
                    # Add a prefix to distinguish threads in the list
                    thread_name = f"└ Thread: {t['name']}"
                    processed_list.append(Channel(id=t['id'], name=thread_name, category=category_name))

            # Sort the list: top-level channels first, then by category, then by name
            return sorted(processed_list, key=lambda c: (c.category or ' ', c.name))
            
        except Exception as e:
            print(f"Error fetching channels from Discord API: {e}")
            raise HTTPException(status_code=502, detail="Failed to fetch channels from Discord.")

@router.post("/send-embed", status_code=204, dependencies=[Depends(check_event_lock)])
async def send_squad_embed(request: SendEmbedRequest, db: Database = Depends(get_db)):
    """Sends the finalized squad composition as an embed to a Discord channel."""
    BOT_TOKEN = os.getenv("DISCORD_TOKEN")
    if not BOT_TOKEN:
        raise HTTPException(status_code=500, detail="Bot token not configured on server.")

    url = f"https://discord.com/api/v10/channels/{request.channel_id}/messages"
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}
    
    event_id = None
    if request.squads:
        first_squad = await db.get_squad_by_id(request.squads[0].squad_id)
        if first_squad:
            event_id = first_squad['event_id']

    event_details = await db.get_event_by_id(event_id) if event_id else None
    
    # --- MODIFIED: Logic to build the new title ---
    title_str = "Team Composition"
    event_time_str = ""
    if event_details:
        event_timestamp = int(event_details['event_time'].timestamp())
        event_time_str = f" - <t:{event_timestamp}:F>"
        title_str = f"Team Composition - {event_details['title']}"

    reserves_list = []
    for squad in request.squads:
        if squad.squad_type == "Reserves":
            reserves_list = [m.display_name for m in squad.members]
            break

    fields = []
    for squad in request.squads:
        if squad.squad_type == "Reserves":
            continue
        member_list = []
        for m in squad.members:
            emoji = EMOJI_MAPPING.get(m.assigned_role_name, "❔")
            member_line = f"{emoji} {m.display_name}"
            if m.startup_task:
                member_line += f" - **{m.startup_task}**"
            member_list.append(member_line)
        value = "\n".join(member_list) or "Empty"
        fields.append({
            "name": f"__**{squad.name}**__",
            "value": value,
            "inline": True
        })

    embed_payload = {
        "embeds": [{
            # --- MODIFIED: Use the new title format ---
            "title": f"{title_str}{event_time_str}",
            "description": "The following squads have been finalized for the event.",
            "color": 15844367,
            "fields": fields,
            "footer": {
                "text": f"Reserves: {', '.join(reserves_list) if reserves_list else 'None'}"
            }
        }]
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=embed_payload)
            response.raise_for_status()
        except Exception as e:
            print(f"Error sending embed to Discord API: {e}")
            raise HTTPException(status_code=502, detail="Failed to send embed to Discord.")

@router.get("/{event_id}/debug-lock", response_model=dict, dependencies=[Depends(auth.get_current_admin_user)])
async def debug_lock_status(event_id: int, db: Database = Depends(get_db)):
    """FOR DEBUGGING: Gets the raw lock status from the database."""
    lock_info = await db.get_event_lock_status(event_id)
    current_time_utc = datetime.datetime.now(datetime.timezone.utc)
    
    if lock_info and lock_info.get("locked_at"):
        lock_age_seconds = (current_time_utc - lock_info["locked_at"]).total_seconds()
        lock_info["lock_age_seconds"] = lock_age_seconds
        lock_info["is_expired"] = lock_age_seconds > (LOCK_TIMEOUT_MINUTES * 60)

    return {"raw_lock_info": lock_info, "current_server_time_utc": current_time_utc}

@router.post("/{event_id}/force-unlock", status_code=204, dependencies=[Depends(auth.get_current_admin_user)])
async def force_unlock_event(event_id: int, db: Database = Depends(get_db)):
    """FOR DEBUGGING: Forcibly removes a lock from an event, regardless of owner."""
    await db.unlock_event(event_id)
    print(f"ADMIN ACTION: Event {event_id} was force-unlocked.")
    return
