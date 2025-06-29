import os
import asyncio
from dotenv import load_dotenv

# We need to adjust the python path to import from the bot directory
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from bot.utils.database import Database
from bot.api.auth import get_password_hash

# Load environment variables from .env file
load_dotenv()

async def create_initial_admin():
    """
    Connects to the database and creates the initial admin user
    based on the values in the .env file.
    """
    db = Database()
    await db.connect()

    username = os.getenv("INITIAL_ADMIN_USER")
    password = os.getenv("INITIAL_ADMIN_PASSWORD")

    if not username or not password:
        print("Error: INITIAL_ADMIN_USER and INITIAL_ADMIN_PASSWORD must be set in the .env file.")
        await db.close()
        return

    print(f"Attempting to create admin user: {username}")

    # Check if the user already exists
    existing_user = await db.get_user_by_username(username)
    if existing_user:
        print(f"User '{username}' already exists. Skipping creation.")
    else:
        hashed_password = get_password_hash(password)
        user_id = await db.create_user(
            username=username,
            hashed_password=hashed_password,
            is_admin=True
        )
        print(f"Successfully created admin user '{username}' with ID: {user_id}")
        print("IMPORTANT: You should change this password after your first login!")

    await db.close()

if __name__ == "__main__":
    asyncio.run(create_initial_admin())
