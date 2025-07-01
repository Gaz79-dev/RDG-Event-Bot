import os
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Use absolute imports from the 'bot' package root
from bot.utils.database import Database
from bot.api.routers import events, users, squads, auth

# Load environment variables
load_dotenv()

# --- Define Base Directory ---
BASE_DIR = Path(__file__).resolve().parent

# --- App State & Lifespan for the Web Server ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup and shutdown events for the web server.
    """
    print("Web server startup...")
    db_instance = Database()
    await db_instance.connect()
    
    # Store the database connection in the app's state
    app.state.db = db_instance
    # Explicitly set the bot to None, as it runs in a separate process
    app.state.bot = None 
    
    yield
    
    print("Web server shutdown...")
    await db_instance.close()

# --- FastAPI App Setup ---
app = FastAPI(lifespan=lifespan)
templates_dir = BASE_DIR / "web/templates"
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "web/static")), name="static")
templates = Jinja2Templates(directory=str(templates_dir))

# Include all the API routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(events.router)
app.include_router(squads.router)

# --- Web Page Routes ---
@app.get("/login", tags=["HTML"])
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/", tags=["HTML"])
async def main_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/admin", tags=["HTML"])
async def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})
