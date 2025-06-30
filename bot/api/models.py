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

class SquadMember(BaseModel):
    user_id: int
    display_name: str
    assigned_role_name: str

class Squad(BaseModel):
    squad_id: int
    name: str
    squad_type: str
    members: List[SquadMember]
    
class SquadBuildRequest(BaseModel):
    infantry_squad_size: int = 6
    attack_squads: int = 0
    defence_squads: int = 0
    flex_squads: int = 0
    armour_squads: int = 0
    recon_squads: int = 0
    arty_squads: int = 0

class SendEmbedRequest(BaseModel):
    channel_id: int
    squads: List[Squad]
