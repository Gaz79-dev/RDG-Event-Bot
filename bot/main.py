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

from .utils.database import Database
from .api.routers import events, users
from .api import auth
from .api.auth import get_password_hash

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent

async def create_initial_admin_if_not_exists(db: Database):
    print("### Checking for initial admin user... ###")
    username, password = os.getenv("INITIAL_ADMIN_USER"), os.getenv("INITIAL_ADMIN_PASSWORD")
    if not username or not password:
        return print("!!! WARNING: INITIAL_ADMIN_USER and/or INITIAL_ADMIN_PASSWORD not set. Skipping admin creation. !!!")
    try:
        if await db.get_user_by_username(username):
            print(f"Admin user '{username}' already exists. Skipping creation.")
        else:
            print(f"Admin user '{username}' not found, creating now...")
            user_id = await db.create_user(username=username, hashed_password=get_password_hash(password), is_admin=True)
            print(f"Successfully created admin user '{username}' with ID: {user_id}")
    except Exception as e:
        print(f"!!! ERROR: Could not create admin user. Reason: {e} !!!"), traceback.print_exc()
    print("### Admin user check complete. ###")

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Application startup...")
    db_instance = Database()
    await db_instance.connect()
    await create_initial_admin_if_not_exists(db_instance)
    
    intents = discord.Intents.default()
    intents.members, intents.message_content = True, True
    bot_instance = EventBot(db=db_instance, web_app=app, command_prefix="!", intents=intents)

    app.state.db, app.state.bot = db_instance, bot_instance
    asyncio.create_task(bot_instance.start(os.getenv("DISCORD_TOKEN")))
    yield
    print("Application shutdown...")
    await bot_instance.close(), await db_instance.close()

app = FastAPI(lifespan=lifespan)
templates_dir = BASE_DIR / "web/templates"
app.mount("/static", StaticFiles(directory=BASE_DIR / "web/static"), name="static")
templates = Jinja2Templates(directory=templates_dir)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(events.router)

class EventBot(commands.Bot):
    def __init__(self, db: Database, web_app: FastAPI, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db, self.web_app = db, web_app
    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})\n------')
    async def setup_hook(self):
        print("Bot setup hook running...")
        # --- FIX: Add the new setup cog to the list of cogs to load ---
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
                print(f"Failed to load cog {cog}:"), traceback.print_exc()
        try:
            if guild_id := os.getenv("GUILD_ID"):
                synced = await self.tree.sync(guild=discord.Object(id=int(guild_id)))
                print(f"Synced {len(synced)} command(s) to guild {guild_id}.")
            else:
                synced = await self.tree.sync()
                print(f"Synced {len(synced)} command(s) globally.")
        except Exception as e: print(f"Failed to sync commands: {e}")

@app.get("/login")
async def login_page(request: Request): return templates.TemplateResponse("login.html", {"request": request})
@app.get("/")
async def main_page(request: Request): return templates.TemplateResponse("index.html", {"request": request})
@app.get("/admin")
async def admin_page(request: Request): return templates.TemplateResponse("admin.html", {"request": request})

if __name__ == "__main__":
    uvicorn.run("bot.main:app", host="0.0.0.0", port=8000, reload=True)
