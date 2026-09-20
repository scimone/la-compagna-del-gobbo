#!/bin/bash

# Exit immediately if a command fails
set -e

# Navigate to the project directory
cd /home/ascimone/projects/la-compagna-del-gobbo || { echo "Directory not found"; exit 1; }

# Build the Docker images from the working tree as it is on disk - no `git pull`, so this needs
# no GitHub credentials; commit/push separately.
echo "Building Docker images..."
docker compose build

# Stop the specific containers
echo "Stopping container..."
docker compose down dnd-web

# Start the containers in detached mode
echo "Starting container..."
docker compose up -d dnd-web

echo "Update complete!"