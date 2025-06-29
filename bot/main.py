import discord
from discord.ext import commands
import os
import asyncio
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

# --- FastAPI App Setup ---
app = FastAPI()

# Mount static files and templates
app.mount("/static", StaticFiles(directory="bot/web/static"), name="static")
templates = Jinja2Templates(directory="bot/web/templates")

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
        # Make the bot instance and db available to the FastAPI app state
        self.web_app.state.bot = self
        self.web_app.state.db = db

    async def setup_hook(self):
        """The setup_hook is called when the bot logs in."""
        print("Bot setup hook running...")
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
                traceback.print_exc()
        
        # Sync commands
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


# --- Main Application Logic ---
db_instance = Database()
bot_instance = EventBot(db=db_instance, web_app=app, command_prefix="!", intents=intents)

async def run_bot():
    """Coroutine to run the Discord bot."""
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("Error: DISCORD_TOKEN not found in .env file.")
        return
    await bot_instance.start(token)

async def run_web_server():
    """Coroutine to run the FastAPI web server."""
    config = uvicorn.Config("bot.main:app", host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    """Main entry point to run both bot and web server concurrently."""
    print("Connecting to database...")
    await db_instance.connect()
    
    # Run both tasks concurrently
    await asyncio.gather(
        run_web_server(),
        run_bot()
    )

if __name__ == "__main__":
    # This part is crucial for running with `python -m bot.main`
    # but uvicorn will handle the loop when run from docker-compose.
    # The main() function is defined for clarity and potential direct execution.
    pass

# The uvicorn command in docker-compose.yml will target `app`, 
# which is the FastAPI instance. The bot will be started via the `run_bot`
# coroutine which we will now launch from the main script body.

# To ensure the bot starts when uvicorn runs the app, we need a startup event.
# However, a simple startup event can be blocking. The `main` function with `gather`
# is the most robust way. We need to adjust the docker-compose command.

# Let's redefine the startup logic to be simpler and non-blocking for uvicorn.

@app.on_event("startup")
async def startup():
    asyncio.create_task(db_instance.connect())
    asyncio.create_task(bot_instance.start(os.getenv("DISCORD_TOKEN")))

# With this new startup event, the `main` function and `gather` are not needed for Docker.
# The `uvicorn` command in your docker-compose will now work as intended.
# I'll remove the more complex `main` function to avoid confusion.
