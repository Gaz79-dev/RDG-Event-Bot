from fastapi import Request, HTTPException, status
from discord.ext import commands

# These dependencies are used by API endpoints to get access to shared resources.

def get_db(request: Request):
    """Dependency to get the database pool from the application state."""
    db = request.app.state.db
    if db is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database connection not available")
    return db

def get_bot(request: Request) -> commands.Bot:
    """Dependency to get the Discord bot instance from the application state."""
    bot = request.app.state.bot
    if bot is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Discord bot not available")
    return bot
