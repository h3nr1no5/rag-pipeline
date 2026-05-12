#!/bin/bash
# Stop All Services (Backend + Frontend)

echo "🛑 Stopping all services..."

# Kill uvicorn gracefully
pkill -f "uvicorn src.api.main" 2>/dev/null

# Kill streamlit gracefully
pkill -f "streamlit run" 2>/dev/null

# Wait for graceful shutdown to complete
sleep 2

# Get ports and kill anything using them
API_PORT=$(grep "^PORT=" .env 2>/dev/null | cut -d= -f2)
API_PORT=${API_PORT:-8000}
UI_PORT=$(grep "^STREAMLIT_SERVER_PORT=" .env 2>/dev/null | cut -d= -f2)
UI_PORT=${UI_PORT:-8501}

lsof -ti:$API_PORT 2>/dev/null | xargs kill 2>/dev/null
lsof -ti:$UI_PORT 2>/dev/null | xargs kill 2>/dev/null

# Give processes time to shut down gracefully
sleep 1

echo "✅ All services stopped"