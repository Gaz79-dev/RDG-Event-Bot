# The 'version' attribute is obsolete in modern Docker Compose and has been removed.
services:
  # The Discord Bot Service
  bot:
    # Build the image from the Dockerfile in the current directory
    build: .
    # Name for the container
    container_name: discord-event-bot
    # Automatically restart the container if it stops
    restart: always
    # Mount the .env file into the container for environment variables
    env_file:
      - .env
    # This service depends on the 'db' service. 
    # Docker Compose will start 'db' before starting 'bot'.
    depends_on:
      - db
    # Command to keep the container running and wait for the database
    # This is a simple wait script. For production, a more robust solution like wait-for-it.sh is recommended.
    command: >
      sh -c "
        echo 'Waiting for PostgreSQL to be ready...' &&
        while ! nc -z db 5432; do   
          sleep 1
        done
        echo 'PostgreSQL is ready, starting bot.' &&
        python bot/bot.py
      "

  # The PostgreSQL Database Service
  db:
    # Use the official PostgreSQL 14 image from Docker Hub
    image: postgres:14
    # Name for the container
    container_name: postgres-db
    # Automatically restart the container if it stops
    restart: always
    # Load environment variables from the .env file for database configuration
    env_file:
      - .env
    # Map a local directory to the container's data directory for persistence
    # This ensures your data survives container restarts.
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
    # Expose the PostgreSQL port to a DIFFERENT port on the host machine
    ports:
      - "5433:5432"

volumes:
  # Define the volume for persistent data
  postgres_data:
