from fastapi import APIRouter, Depends
from typing import Dict, Optional

from bot.api import auth
from bot.api.dependencies import get_db
from bot.utils.database import Database, ROLES, SUBCLASSES
from bot.api.models import RoleUpdateRequest, SquadMoveRequest
from bot.cogs.event_management import EMOJI_MAPPING

router = APIRouter(prefix="/api/squads", tags=["squads"], dependencies=[Depends(auth.get_current_active_user)])

@router.get("/roles", response_model=Dict)
async def get_all_roles(db: Database = Depends(get_db)):
    return await db.get_all_roles_and_subclasses()

@router.get("/emojis", response_model=Dict[str, str])
async def get_emojis():
    return EMOJI_MAPPING

@router.put("/members/{squad_member_id}/role", status_code=204)
async def update_member_role(squad_member_id: int, request: RoleUpdateRequest, db: Database = Depends(get_db)):
    await db.update_squad_member_role(squad_member_id, request.new_role_name)
    member_details = await db.get_squad_member_details(squad_member_id)
    if not member_details: return

    user_id, new_primary_role, new_subclass_name = member_details['user_id'], None, None
    for role, subclasses in SUBCLASSES.items():
        if request.new_role_name in subclasses:
            new_primary_role, new_subclass_name = role, request.new_role_name
            break
    if not new_primary_role and request.new_role_name in ROLES:
        new_primary_role = request.new_role_name
    
    if new_primary_role:
        await db.update_signup_role(request.event_id, user_id, new_primary_role, new_subclass_name)

@router.put("/members/{squad_member_id}/move", status_code=204)
async def move_member_to_squad(squad_member_id: int, request: SquadMoveRequest, db: Database = Depends(get_db)):
    await db.move_squad_member(squad_member_id, request.new_squad_id)
