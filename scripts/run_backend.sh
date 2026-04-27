#!/bin/bash
# Run Backend API Server

SCRIPT_DIR="$(dirname "$0")"
cd "$SCRIPT_DIR/.."

# Create logs directory if it doesn't exist
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/backend.log"

echo "🚀 Starting RAG Pipeline Backend API..."
echo "📝 Logging to $LOG_FILE"

# Check if virtualenv exists
if [ ! -d ".venv" ]; then
    echo "❌ Virtualenv not found. Run: python -m venv .venv && source .venv/bin/activate && pip install -e ."
    exit 1
fi

# Activate virtualenv and run
source .venv/bin/activate

# Get port from .env or use default
PORT=$(grep "^PORT=" .env 2>/dev/null | cut -d= -f2)
PORT=${PORT:-8000}

# Get host from .env or use default
API_HOST=$(grep "^HOST=" .env 2>/dev/null | cut -d= -f2)
API_HOST=${API_HOST:-127.0.0.1}

# Run uvicorn with logging
echo "📡 API running at http://$API_HOST:$PORT"
echo "📖 Docs at http://$API_HOST:$PORT/docs"

uvicorn src.api.main:app --host $API_HOST --port $PORT --reload 2>&1 | tee "$LOG_FILE"