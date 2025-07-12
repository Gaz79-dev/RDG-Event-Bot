from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime

# --- Token Models ---
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

# --- User Models ---
class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)

class UserCreate(UserBase):
    password: str = Field(..., min_length=8)
    is_admin: bool = False

class UserUpdate(BaseModel):
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None

class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)

class AdminPasswordChange(BaseModel):
    new_password: str = Field(..., min_length=8)

class User(UserBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_active: bool
    is_admin: bool

class UserInDB(User):
    hashed_password: str

# --- Event & Squad Models ---
class Event(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    event_id: int
    title: str
    event_time: datetime

class Signup(BaseModel):
    user_id: int
    display_name: str
    role_name: Optional[str] = "Unassigned"
    subclass_name: Optional[str] = "N/A"

class Channel(BaseModel):
    id: str
    name: str
    category: Optional[str] = None

class SquadMember(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra='ignore')
    squad_member_id: int
    user_id: int
    assigned_role_name: str
    display_name: Optional[str] = None
    startup_task: Optional[str] = None

class Squad(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    squad_id: int
    name: str
    squad_type: str
    members: List[SquadMember]
    
class EventLockStatus(BaseModel):
    is_locked: bool
    locked_by_user_id: Optional[int] = None
    locked_by_username: Optional[str] = None

class SquadBuildRequest(BaseModel):
    infantry_squad_size: int = 6
    attack_squads: int = 0
    defence_squads: int = 0
    flex_squads: int = 0
    pathfinder_squads: int = 0
    armour_squads: int = 0
    recon_squads: int = 0
    arty_squads: int = 0

class SendEmbedRequest(BaseModel):
    channel_id: str
    squads: List[Squad]

class RoleUpdateRequest(BaseModel):
    new_role_name: str
    event_id: int

class SquadMoveRequest(BaseModel):
    new_squad_id: int

class RosterUpdateRequest(BaseModel):
    squads: List[Squad]

class StartupTaskUpdateRequest(BaseModel):
    task: Optional[str] = None

# --- Player Statistics Models ---
class PlayerStats(BaseModel):
    user_id: str
    display_name: str
    accepted_count: int
    tentative_count: int
    declined_count: int
    last_signup_date: Optional[datetime] = None
    days_since_last_signup: Optional[int] = None

class AcceptedEvent(BaseModel):
    # FIX: Changed 'title' to 'event_title' to match the database query result.
    event_title: str
    event_time: datetime
