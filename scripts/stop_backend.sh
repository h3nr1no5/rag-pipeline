#!/bin/bash
# Stop Backend API Server

echo "🛑 Stopping Backend API..."

# Kill uvicorn processes
pkill -f "uvicorn src.api.main" 2>/dev/null

# Also kill by port
lsof -ti:$PORT 2>/dev/null | xargs kill 2>/dev/null

echo "✅ Backend stopped"