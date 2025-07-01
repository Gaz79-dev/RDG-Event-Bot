from fastapi import APIRouter, Depends
from typing import Dict

from bot.api import auth
from bot.api.dependencies import get_db
from bot.utils.database import Database
from pydantic import BaseModel

class RoleUpdateRequest(BaseModel):
    new_role_name: str

class SquadMoveRequest(BaseModel):
    new_squad_id: int

router = APIRouter(
    prefix="/api/squads",
    tags=["squads"],
    dependencies=[Depends(auth.get_current_active_user)],
)

@router.get("/roles", response_model=Dict)
async def get_all_roles(db: Database = Depends(get_db)):
    return await db.get_all_roles_and_subclasses()

@router.put("/members/{squad_member_id}/role", status_code=204)
async def update_member_role(squad_member_id: int, request: RoleUpdateRequest, db: Database = Depends(get_db)):
    await db.update_squad_member_role(squad_member_id, request.new_role_name)
    return

@router.put("/members/{squad_member_id}/move", status_code=204)
async def move_member_to_squad(squad_member_id: int, request: SquadMoveRequest, db: Database = Depends(get_db)):
    await db.move_squad_member(squad_member_id, request.new_squad_id)
    return
