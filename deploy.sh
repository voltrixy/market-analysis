#!/bin/bash

# Build and deploy the application
echo "Building and deploying Market Analysis Tool..."

# Stop any existing containers
docker-compose down

# Build new images
docker-compose build

# Start the services
docker-compose up -d

# Show logs
docker-compose logs -f 