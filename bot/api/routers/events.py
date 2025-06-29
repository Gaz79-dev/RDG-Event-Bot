import os
import traceback
from fastapi import APIRouter, Depends, HTTPException
from typing import List
import discord
from discord.ext import commands

# Adjust imports for the new structure
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
async def get_upcoming_events(db: Database = Depends(get_db)):
    """
    Get a list of all upcoming, non-recurring events.
    """
    events = await db.get_upcoming_events()
    return events

@router.get("/{event_id}/signups", response_model=List[Signup])
async def get_event_signups(event_id: int, db: Database = Depends(get_db), bot: commands.Bot = Depends(get_bot)):
    """
    Get the roster of accepted signups for a specific event.
    """
    signups_records = await db.get_signups_for_event(event_id)
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        raise HTTPException(status_code=500, detail="Bot is not in the configured guild.")

    roster = []
    for record in signups_records:
        if record['rsvp_status'] != 'Accepted':
            continue
        
        member = guild.get_member(record['user_id'])
        display_name = member.display_name if member else f"User ID: {record['user_id']}"
        
        roster.append(Signup(
            user_id=record['user_id'],
            display_name=display_name,
            role_name=record['role_name'],
            subclass_name=record['subclass_name']
        ))
    return roster

@router.get("/channels", response_model=List[Channel])
async def get_guild_channels(bot: commands.Bot = Depends(get_bot)):
    """
    Get a list of all text channels in the configured guild.
    """
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        raise HTTPException(status_code=500, detail="Bot is not in the configured guild.")
    
    text_channels = [
        Channel(id=str(c.id), name=c.name) 
        for c in guild.text_channels
    ]
    return sorted(text_channels, key=lambda c: c.name)

@router.post("/{event_id}/build-squads", response_model=List[Squad])
async def build_squads_for_event(
    event_id: int, 
    request: SquadBuildRequest,
    db: Database = Depends(get_db), 
    bot: commands.Bot = Depends(get_bot)
):
    """
    Triggers the squad building logic and returns the generated squads.
    This re-uses the logic from the squad_builder cog.
    """
    squad_builder_cog = bot.get_cog('SquadBuilder')
    if not squad_builder_cog:
        raise HTTPException(status_code=500, detail="SquadBuilder cog not loaded.")

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        raise HTTPException(status_code=500, detail="Bot is not in the configured guild.")

    # Create a mock modal object to pass to the drafting function
    class MockModal:
        def __init__(self, req: SquadBuildRequest):
            self.infantry_squad_size_val = req.infantry_squad_size
            self.attack_squads_val = req.attack_squads
            self.defence_squads_val = req.defence_squads
            self.flex_squads_val = req.flex_squads
            self.armour_squads_val = req.armour_squads
            self.recon_squads_val = req.recon_squads
            self.arty_squads_val = req.arty_squads
    
    mock_modal = MockModal(request)

    try:
        await squad_builder_cog._run_automated_draft(guild, event_id, mock_modal)
    except Exception as e:
        print(f"Error during API squad build: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"An internal error occurred during squad drafting: {e}")

    # Fetch the generated squads from the database
    squad_records = await db.get_squads_for_event(event_id)
    response_squads = []
    for s_record in squad_records:
        member_records = await db.get_squad_members(s_record['squad_id'])
        members = []
        for m_record in member_records:
            member = guild.get_member(m_record['user_id'])
            members.append(SquadMember(
                user_id=m_record['user_id'],
                display_name=member.display_name if member else f"ID: {m_record['user_id']}",
                assigned_role_name=m_record['assigned_role_name']
            ))
        response_squads.append(Squad(
            squad_id=s_record['squad_id'],
            name=s_record['name'],
            squad_type=s_record['squad_type'],
            members=members
        ))

    return response_squads

@router.post("/send-embed", status_code=204)
async def send_squad_embed(
    request: SendEmbedRequest,
    db: Database = Depends(get_db),
    bot: commands.Bot = Depends(get_bot)
):
    """
    Takes a generated squad composition and posts it as an embed to a specified channel.
    """
    channel = bot.get_channel(request.channel_id)
    if not channel or not isinstance(channel, discord.TextChannel):
        raise HTTPException(status_code=404, detail="Channel not found or is not a text channel.")

    embed = discord.Embed(
        title=f"🛠️ Finalized Team Composition",
        description="The following squads have been finalized for the event.",
        color=discord.Color.gold()
    )

    for squad in request.squads:
        member_list = [f"**{m.assigned_role_name}:** {m.display_name}" for m in squad.members]
        value = "\n".join(member_list) or "Empty"
        embed.add_field(name=f"__**{squad.name}**__ ({squad.squad_type})", value=value, inline=True)
    
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        raise HTTPException(status_code=403, detail="Bot does not have permission to send messages in that channel.")
    
    return
