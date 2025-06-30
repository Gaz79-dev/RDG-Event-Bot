import os
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

# Load environment variables
load_dotenv()

# --- Define Base Directory ---
BASE_DIR = Path(__file__).resolve().parent

# --- App State & Lifespan for WEB ONLY ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup and shutdown events for the web server.
    """
    print("Web server startup...")
    db_instance = Database()
    await db_instance.connect()
    
    app.state.db = db_instance
    # The bot instance is no longer created or stored here
    app.state.bot = None 
    
    yield
    
    print("Web server shutdown...")
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

# The EventBot class is no longer defined here
# The __main__ block is also removed, as Uvicorn will be run via docker-compose
