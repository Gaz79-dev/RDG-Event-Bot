# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /usr/src/app

# --- Install System Dependencies (including netcat) ---
# Install netcat-openbsd to allow the startup script to check the database connection
RUN apt-get update && apt-get install -y netcat-openbsd && rm -rf /var/lib/apt/lists/*

# --- Install Python Dependencies ---
# Copy the requirements file into the container
COPY requirements.txt ./

# Install any needed packages specified in requirements.txt
# --no-cache-dir: Disables the cache, which is good for keeping image sizes down.
# -r requirements.txt: Specifies the file to install from.
RUN pip install --no-cache-dir -r requirements.txt

# --- Copy Application Code ---
# Copy the 'bot' directory from your local machine to the container's working directory
COPY ./bot ./bot

# --- Run the application ---
# The command to run your bot when the container launches.
CMD ["python", "bot/bot.py"]
