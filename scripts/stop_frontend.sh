#!/bin/bash
# Stop Frontend Streamlit UI

cd "$(dirname "$0")/.."

echo "🛑 Stopping Frontend..."

# Get port from .env or use default
PORT=$(grep "^STREAMLIT_SERVER_PORT=" .env 2>/dev/null | cut -d= -f2)
PORT=${PORT:-8501}

# Kill streamlit processes gracefully
pkill -f "streamlit run" 2>/dev/null

# Wait for graceful shutdown
sleep 2

# Force kill if still running
lsof -ti:$PORT 2>/dev/null | xargs kill -9 2>/dev/null

echo "✅ Frontend stopped"