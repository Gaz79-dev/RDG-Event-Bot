import discord
from discord.ext import commands
import os
import asyncio
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Adjust imports for the new structure
from .utils.database import Database
from .api.routers import events, users
from .api import auth
# Import the password hashing function for admin creation
from .api.auth import get_password_hash

# Load environment variables
load_dotenv()

# --- Define Base Directory ---
BASE_DIR = Path(__file__).resolve().parent

# --- Helper function to create initial admin ---
async def create_initial_admin_if_not_exists(db: Database):
    """
    Checks for and creates the initial admin user from the .env file if not present.
    """
    print("### Checking for initial admin user... ###")
    username = os.getenv("INITIAL_ADMIN_USER")
    password = os.getenv("INITIAL_ADMIN_PASSWORD")

    if not username or not password:
        print("!!! WARNING: INITIAL_ADMIN_USER and/or INITIAL_ADMIN_PASSWORD not set. Skipping admin creation. !!!")
        return

    try:
        existing_user = await db.get_user_by_username(username)
        if existing_user:
            print(f"Admin user '{username}' already exists. Skipping creation.")
        else:
            print(f"Admin user '{username}' not found, creating now...")
            hashed_password = get_password_hash(password)
            user_id = await db.create_user(
                username=username,
                hashed_password=hashed_password,
                is_admin=True
            )
            print(f"Successfully created admin user '{username}' with ID: {user_id}")
    except Exception as e:
        print(f"!!! ERROR: Could not create admin user. Reason: {e} !!!")
        traceback.print_exc()
    print("### Admin user check complete. ###")


# --- App State & Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup and shutdown events.
    """
    print("Application startup...")
    db_instance = Database()
    await db_instance.connect()
    
    # Create the admin user if it doesn't exist
    await create_initial_admin_if_not_exists(db_instance)
    
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True
    bot_instance = EventBot(db=db_instance, web_app=app, command_prefix="!", intents=intents)

    app.state.db = db_instance
    app.state.bot = bot_instance
    
    asyncio.create_task(bot_instance.start(os.getenv("DISCORD_TOKEN")))
    
    yield
    
    print("Application shutdown...")
    await bot_instance.close()
    await db_instance.close()


# --- FastAPI App Setup ---
app = FastAPI(lifespan=lifespan)
templates_dir = BASE_DIR / "web/templates"
app.mount("/static", StaticFiles(directory=BASE_DIR / "web/static"), name="static")
templates = Jinja2Templates(directory=templates_dir)

# Include API routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(events.router)

# --- Discord Bot Setup ---
class EventBot(commands.Bot):
    def __init__(self, db: Database, web_app: FastAPI, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = db
        self.web_app = web_app
        self.synced = False # Add a flag to prevent re-syncing on reconnect

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')

        # --- FIX: Move command syncing to on_ready ---
        # This ensures that syncing happens only after the bot is fully
        # connected and all cogs are loaded.
        if not self.synced:
            print("Syncing command tree...")
            try:
                guild_id = os.getenv("GUILD_ID")
                if guild_id:
                    guild_obj = discord.Object(id=int(guild_id))
                    # Copy global commands to the guild and sync.
                    self.tree.copy_global_to(guild=guild_obj)
                    synced = await self.tree.sync(guild=guild_obj)
                    print(f"Synced {len(synced)} command(s) to guild {guild_id}.")
                else:
                    synced = await self.tree.sync()
                    print(f"Synced {len(synced)} command(s) globally.")
                
                self.synced = True # Set the flag to true after a successful sync
            except Exception as e:
                print(f"Failed to sync commands: {e}")
                traceback.print_exc()


    async def setup_hook(self):
        print("Bot setup hook running...")
        cogs_to_load = [
            'bot.cogs.event_management',
            'bot.cogs.scheduler',
            'bot.cogs.squad_builder',
            'bot.cogs.setup'
        ]
        for cog in cogs_to_load:
            try:
                await self.load_extension(cog)
                print(f"Successfully loaded cog: {cog}")
            except Exception as e:
                print(f"Failed to load cog {cog}:")
                traceback.print_exc()
        
        # --- FIX: Command syncing is now removed from setup_hook ---

# --- Web Page Routes ---
@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/")
async def main_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/admin")
async def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})

if __name__ == "__main__":
    uvicorn.run("bot.main:app", host="0.0.0.0", port=8000, reload=True)
