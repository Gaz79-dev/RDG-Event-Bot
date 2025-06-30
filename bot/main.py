import discord
from discord.ext import commands
import os
import asyncio
import traceback
from contextlib import asynccontextmanager
from pathlib import Path # Import the Path object
from dotenv import load_dotenv
import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Adjust imports for the new structure
from .utils.database import Database
from .api.routers import events, users
from .api import auth

# Load environment variables
load_dotenv()

# --- Define Base Directory ---
# This makes file paths robust by creating absolute paths
# from this file's location.
BASE_DIR = Path(__file__).resolve().parent


# --- App State & Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup and shutdown events.
    Connects to the database and starts the Discord bot.
    """
    print("Application startup...")
    db_instance = Database()
    await db_instance.connect()
    
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

# --- DEBUGGING: Check for templates directory and its contents ---
templates_dir = BASE_DIR / "web/templates"
print("--- Sanity Check for Templates ---")
print(f"Attempting to use templates directory: {templates_dir}")
if templates_dir.is_dir():
    print("Directory exists. Files found:")
    files = [f.name for f in templates_dir.iterdir()]
    if files:
        for f in files:
            print(f"  - {f}")
    else:
        print("  - Directory is empty.")
else:
    print("!!! ERROR: Templates directory does not exist or is not a directory. !!!")
print("---------------------------------")


# Mount static files and templates using absolute paths
app.mount("/static", StaticFiles(directory=BASE_DIR / "web/static"), name="static")
templates = Jinja2Templates(directory=templates_dir) # Use the path we just checked

# Include API routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(events.router)

# --- Discord Bot Setup ---
class EventBot(commands.Bot):
    """Custom Bot class to hold the database connection and FastAPI app."""
    def __init__(self, db: Database, web_app: FastAPI, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = db
        self.web_app = web_app

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')

    async def setup_hook(self):
        """The setup_hook is called when the bot logs in."""
        print("Bot setup hook running...")
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
                print(f"Failed to load cog {cog}:")
                traceback.print_exc()
        
        try:
            guild_id = os.getenv("GUILD_ID")
            if guild_id:
                synced = await self.tree.sync(guild=discord.Object(id=int(guild_id)))
                print(f"Synced {len(synced)} command(s) to guild {guild_id}.")
            else:
                synced = await self.tree.sync()
                print(f"Synced {len(synced)} command(s) globally.")
        except Exception as e:
            print(f"Failed to sync commands: {e}")


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

# This check allows running with `python -m bot.main` for local dev if needed
if __name__ == "__main__":
    uvicorn.run("bot.main:app", host="0.0.0.0", port=8000, reload=True)
