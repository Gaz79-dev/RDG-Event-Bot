import discord
from discord.ext import commands
import os
import asyncio
from dotenv import load_dotenv
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Adjust imports for the new structure
from .utils.database import Database
from .api.routers import events, users
from .api import auth

# Load environment variables
load_dotenv()

# --- FastAPI App Setup ---
app = FastAPI()

# Mount static files for the web interface
app.mount("/static", StaticFiles(directory="bot/web/static"), name="static")

# Include API routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(events.router)

# --- Discord Bot Setup ---
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

class EventBot(commands.Bot):
    """Custom Bot class to hold the database connection and FastAPI app."""
    def __init__(self, db: Database, web_app: FastAPI, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = db
        self.web_app = web_app
        # Make the bot instance available to the FastAPI app state
        self.web_app.state.bot = self

    async def setup_hook(self):
        """The setup_hook is called when the bot logs in."""
        print("Running setup hook...")
        # Load cogs
        cogs_to_load = [
            'bot.cogs.event_management',
            'bot.cogs.scheduler',
            'bot.cogs.squad_builder'
        ]
        for cog in cogs_to_load:
            try:
                await self.load_extension(cog)
                print(f"Successfully loaded cog: {cog}")
            except Exception as e:
                print(f"Failed to load cog {cog}: {e}")
        
        # Sync commands
        try:
            synced = await self.tree.sync(guild=discord.Object(id=int(os.getenv("GUILD_ID"))))
            print(f"Synced {len(synced)} command(s) to the specified guild.")
        except Exception as e:
            print(f"Failed to sync commands: {e}")

# --- Main Execution ---
async def run_bot(bot: EventBot):
    """Starts the Discord bot."""
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("Error: DISCORD_TOKEN not found in .env file.")
        return
    await bot.start(token)

async def run_web_server():
    """Starts the FastAPI web server."""
    config = uvicorn.Config("bot.main:app", host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    # This will run the web server without blocking the event loop
    await server.serve()

@app.on_event("startup")
async def startup_event():
    """This event runs when the FastAPI app starts up."""
    print("Web server starting up...")
    # Initialize database
    db = Database()
    await db.connect()
    app.state.db = db
    
    # Initialize and run the Discord bot in the background
    bot = EventBot(db=db, web_app=app, command_prefix="!", intents=intents)
    asyncio.create_task(bot.start(os.getenv("DISCORD_TOKEN")))

@app.on_event("shutdown")
async def shutdown_event():
    """This event runs when the FastAPI app shuts down."""
    print("Web server shutting down...")
    if hasattr(app.state, 'db'):
        await app.state.db.close()
    if hasattr(app.state, 'bot'):
        await app.state.bot.close()
