# Use official Node.js image as the base image
FROM node:16

# Set the working directory inside the container
WORKDIR /app

# Copy package.json and package-lock.json (if present)
COPY package*.json ./

# Install the necessary npm dependencies
RUN npm install

# Copy the rest of your bot code
COPY . .

# Expose the port (if your bot uses a port, else you can omit)
EXPOSE 3000

# Start the bot
CMD ["node", "index.js"]
