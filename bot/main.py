import os
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# --- FIX: Changed to absolute imports ---
from bot.utils.database import Database
from bot.api.routers import events, users
from bot.api import auth
from bot.api.auth import get_password_hash

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Web server startup...")
    db_instance = Database()
    await db_instance.connect()
    app.state.db = db_instance
    app.state.bot = None 
    yield
    print("Web server shutdown...")
    await db_instance.close()

app = FastAPI(lifespan=lifespan)
templates_dir = BASE_DIR / "web/templates"
app.mount("/static", StaticFiles(directory=BASE_DIR / "web/static"), name="static")
templates = Jinja2Templates(directory=str(templates_dir))

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(events.router)

@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/")
async def main_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/admin")
async def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})
