#!/bin/bash
# Run Both Backend and Frontend

cd "$(dirname "$0")/.."

echo "🚀 Starting RAG Pipeline (Backend + Frontend)..."

# Check if virtualenv exists
if [ ! -d ".venv" ]; then
    echo "❌ Virtualenv not found. Run: python -m venv .venv && source .venv/bin/activate && pip install -e ."
    exit 1
fi

# Activate virtualenv
source .venv/bin/activate

# Get ports
API_PORT=$(grep "^PORT=" .env 2>/dev/null | cut -d= -f2)
API_PORT=${API_PORT:-8000}
UI_PORT=$(grep "^STREAMLIT_SERVER_PORT=" .env 2>/dev/null | cut -d= -f2)
UI_PORT=${UI_PORT:-8501}

API_HOST=$(grep "^HOST=" .env 2>/dev/null | cut -d= -f2)
API_HOST=${API_HOST:-127.0.0.1}

echo "📡 Backend API: http://$API_HOST:$API_PORT"
echo "🎨 Frontend UI:  http://$API_HOST:$UI_PORT"
echo ""

# Start backend in background
uvicorn src.api.main:app --host $API_HOST --port $API_PORT &
BACKEND_PID=$!
echo "Started backend (PID: $BACKEND_PID)"

# Wait for backend to start
sleep 2

# Start frontend
streamlit run client/app.py --server.port $UI_PORT --server.address $API_HOST &
FRONTEND_PID=$!
echo "Started frontend (PID: $FRONTEND_PID)"

echo ""
echo "✅ Both services running!"
echo "📡 API:   http://$API_HOST:$API_PORT"
echo "🎨 UI:    http://$API_HOST:$UI_PORT"
echo ""
echo "Press Ctrl+C to stop both"

# Wait for any signal, then graceful shutdown
cleanup() {
    echo "🛑 Stopping services..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
    # Give processes time to shut down gracefully
    sleep 2
    # Force kill if still running
    kill -9 $BACKEND_PID $FRONTEND_PID 2>/dev/null
    echo "✅ Services stopped"
    exit 0
}

trap cleanup INT TERM
wait