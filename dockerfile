# Stage 1: Build dependencies
# We use a lightweight Alpine-based Node.js image for smaller final image size.
FROM node:18-alpine as builder

# Set the working directory inside the container for the build stage.
# This is where npm install will run.
WORKDIR /app

# Copy package.json and package-lock.json (or yarn.lock if you use yarn)
# first. This allows Docker to cache this layer, so if only source code
# changes, npm install won't re-run.
COPY package*.json ./

# Install Node.js dependencies. Use --production to install only production
# dependencies, making the final image smaller.
RUN npm install --production

# Stage 2: Create the final production-ready image
FROM node:18-alpine

# Set the working directory inside the container to the specified path.
WORKDIR /opt/rdg-event-bot

# Define build arguments for user and group IDs. These can be passed during
# the build process (e.g., `docker build --build-arg NODE_UID=$(id -u) .`)
# to match your host user's UID/GID, which helps with volume permissions.
ARG NODE_UID=1000
ARG NODE_GID=1000

# Create a non-root user and group with the specified IDs.
# Running as a non-root user is a security best practice.
RUN addgroup -g ${NODE_GID} appgroup && \
    adduser -u ${NODE_UID} -G appgroup -D appuser

# Copy the installed node_modules from the builder stage.
COPY --from=builder /app/node_modules ./node_modules

# Copy the rest of your application's source code into the working directory.
# Ensure the copied files are owned by the new non-root user.
COPY --chown=appuser:appgroup . .

# Create the logs directory and set its ownership to the non-root user.
# The Node.js application will write logs here.
# This step ensures the directory exists and has correct permissions before the app starts.
RUN mkdir -p logs && chown appuser:appgroup logs

# Switch to the non-root user. All subsequent commands (including CMD)
# will run as this user.
USER appuser

# Define the command to run your application when the container starts.
# Assuming your main bot file is `index.js`.
CMD ["node", "index.js"]

