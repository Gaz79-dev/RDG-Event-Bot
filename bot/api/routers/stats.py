import os
import httpx
import datetime
from fastapi import APIRouter, Depends, HTTPException
from typing import List

from bot.utils.database import Database
from bot.api import auth
from bot.api.dependencies import get_db
from bot.api.models import PlayerStats, AcceptedEvent

router = APIRouter(
    prefix="/api/stats",
    tags=["stats"],
    dependencies=[Depends(auth.get_current_admin_user)],
)

GUILD_ID = os.getenv("GUILD_ID")
BOT_TOKEN = os.getenv("DISCORD_TOKEN")

@router.get("/engagement", response_model=List[PlayerStats])
async def get_engagement_stats(db: Database = Depends(get_db)):
    """
    Retrieves and returns engagement statistics for all players.
    """
    if not GUILD_ID or not BOT_TOKEN:
        raise HTTPException(status_code=500, detail="Bot token or Guild ID not configured on server.")

    all_player_stats = await db.get_all_player_stats()
    player_stats_list = []
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}

    async with httpx.AsyncClient() as client:
        for stats in all_player_stats:
            user_id = stats['user_id']
            
            display_name = f"User ID: {user_id}"
            url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/members/{user_id}"
            try:
                response = await client.get(url, headers=headers)
                if response.is_success:
                    member_data = response.json()
                    display_name = member_data.get('nick') or member_data['user'].get('global_name') or member_data['user']['username']
                elif response.status_code == 404:
                    display_name = f"Left Server ({user_id})"
            except Exception as e:
                print(f"Error fetching member {user_id} for stats: {e}")

            days_since = None
            if stats.get('last_signup_date'):
                days_since = (datetime.datetime.now(datetime.timezone.utc) - stats['last_signup_date']).days

            player_stats_list.append(PlayerStats(
                user_id=str(user_id), # Ensure it's a string for the model
                display_name=display_name,
                accepted_count=stats.get('accepted_count', 0),
                tentative_count=stats.get('tentative_count', 0),
                declined_count=stats.get('declined_count', 0),
                last_signup_date=stats.get('last_signup_date'),
                days_since_last_signup=days_since
            ))
            
    return player_stats_list

@router.get("/player/{user_id}/accepted-events", response_model=List[AcceptedEvent])
async def get_player_accepted_events(user_id: str, db: Database = Depends(get_db)): # CHANGED: Accept user_id as a string
    """Gets a list of all events a specific player has accepted from the permanent history log."""
    # The database function still expects an integer, so we convert it here.
    return await db.get_accepted_events_for_user(int(user_id))
