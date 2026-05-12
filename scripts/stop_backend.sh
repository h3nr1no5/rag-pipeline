#!/bin/bash
# Stop Backend API Server

echo "🛑 Stopping Backend API..."

# Get port from .env or use default
PORT=$(grep "^PORT=" .env 2>/dev/null | cut -d= -f2)
PORT=${PORT:-8000}

# Kill uvicorn processes gracefully
pkill -f "uvicorn src.api.main" 2>/dev/null

# Wait for graceful shutdown
sleep 1

# Also kill by port
lsof -ti:$PORT 2>/dev/null | xargs kill 2>/dev/null

# Give time to shut down
sleep 1

echo "✅ Backend stopped"