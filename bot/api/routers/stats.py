import os
import httpx
import datetime
from fastapi import APIRouter, Depends, HTTPException
from typing import List

# Use absolute imports from the 'bot' package root
from bot.utils.database import Database
from bot.api import auth
from bot.api.dependencies import get_db
from bot.api.models import PlayerStats

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
    Calculates and returns engagement statistics for all players who have ever signed up.
    """
    if not GUILD_ID or not BOT_TOKEN:
        raise HTTPException(status_code=500, detail="Bot token or Guild ID not configured on server.")

    unique_users = await db.get_all_unique_signup_users()
    player_stats_list = []
    headers = {"Authorization": f"Bot {BOT_TOKEN}"}

    async with httpx.AsyncClient() as client:
        for user_record in unique_users:
            user_id = user_record['user_id']
            
            # Fetch user's display name from Discord
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

            # Get RSVP stats from the database
            stats = await db.get_stats_for_user(user_id)
            
            # Calculate days since last signup
            days_since = None
            if stats.get('last_signup_date'):
                days_since = (datetime.datetime.now(datetime.timezone.utc) - stats['last_signup_date']).days

            player_stats_list.append(PlayerStats(
                user_id=user_id,
                display_name=display_name,
                accepted_count=stats.get('accepted_count', 0),
                tentative_count=stats.get('tentative_count', 0),
                declined_count=stats.get('declined_count', 0),
                last_signup_date=stats.get('last_signup_date'),
                days_since_last_signup=days_since
            ))
            
    return player_stats_list
