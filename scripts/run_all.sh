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

echo "📡 Backend API: http://localhost:$API_PORT"
echo "🎨 Frontend UI:  http://localhost:$UI_PORT"
echo ""

# Start backend in background
uvicorn src.api.main:app --host 0.0.0.0 --port $API_PORT &
BACKEND_PID=$!
echo "Started backend (PID: $BACKEND_PID)"

# Wait for backend to start
sleep 2

# Start frontend
streamlit run client/app.py --server.port $UI_PORT --server.address 0.0.0.0 &
FRONTEND_PID=$!
echo "Started frontend (PID: $FRONTEND_PID)"

echo ""
echo "✅ Both services running!"
echo "📡 API:   http://localhost:$API_PORT"
echo "🎨 UI:    http://localhost:$UI_PORT"
echo ""
echo "Press Ctrl+C to stop both"

# Wait for any signal
trap "echo '🛑 Stopping...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait