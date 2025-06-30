from fastapi import APIRouter, Depends, HTTPException, status
from typing import List

# Adjust imports for the new structure
from ...utils.database import Database
from .. import auth
from ..models import User, UserCreate, UserUpdate, PasswordChange, UserInDB

router = APIRouter(
    prefix="/api/users",
    tags=["users"],
    dependencies=[Depends(auth.get_current_active_user)],
    responses={404: {"description": "Not found"}},
)

@router.get("/", response_model=List[User], dependencies=[Depends(auth.get_current_admin_user)])
async def read_users(db: Database = Depends(auth.get_db)):
    """
    Retrieve all users. Only accessible by admin users.
    """
    users_records = await db.get_all_users()
    # Explicitly convert database records to Pydantic models to avoid validation errors.
    return [User.model_validate(user) for user in users_records]

@router.post("/", response_model=User, status_code=status.HTTP_201_CREATED, dependencies=[Depends(auth.get_current_admin_user)])
async def create_user(user: UserCreate, db: Database = Depends(auth.get_db)):
    """
    Create a new user. Only accessible by admin users.
    """
    db_user = await db.get_user_by_username(user.username)
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    hashed_password = auth.get_password_hash(user.password)
    user_id = await db.create_user(username=user.username, hashed_password=hashed_password, is_admin=user.is_admin)
    
    created_user_record = await db.get_user_by_id(user_id)
    if not created_user_record:
         raise HTTPException(status_code=500, detail="Failed to retrieve created user")
    # Explicitly convert the database record to a Pydantic model.
    return User.model_validate(created_user_record)


@router.get("/me", response_model=User)
async def read_users_me(current_user: User = Depends(auth.get_current_active_user)):
    """
    Get the current logged-in user's details.
    """
    return current_user

@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_own_password(
    password_data: PasswordChange,
    current_user: UserInDB = Depends(auth.get_current_active_user),
    db: Database = Depends(auth.get_db)
):
    """
    Allow the current logged-in user to change their own password.
    """
    if not auth.verify_password(password_data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect current password")
    
    new_hashed_password = auth.get_password_hash(password_data.new_password)
    await db.update_user_password(user_id=current_user.id, new_hashed_password=new_hashed_password)
    return

@router.put("/{user_id}", response_model=User, dependencies=[Depends(auth.get_current_admin_user)])
async def update_user(
    user_id: int, 
    user_update: UserUpdate, 
    db: Database = Depends(auth.get_db)
):
    """
    Update a user's status (is_active, is_admin). Only accessible by admin users.
    """
    db_user = await db.get_user_by_id(user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
        
    await db.update_user_status(user_id=user_id, is_active=user_update.is_active, is_admin=user_update.is_admin)
    updated_user_record = await db.get_user_by_id(user_id)
    if not updated_user_record:
         raise HTTPException(status_code=500, detail="Failed to retrieve updated user")
    # Explicitly convert the database record to a Pydantic model.
    return User.model_validate(updated_user_record)

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(auth.get_current_admin_user)])
async def delete_user(user_id: int, db: Database = Depends(auth.get_db)):
    """
    Delete a user. Only accessible by admin users.
    """
    db_user = await db.get_user_by_id(user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    await db.delete_user(user_id=user_id)
    return
