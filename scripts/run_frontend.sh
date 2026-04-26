#!/bin/bash
# Run Frontend Streamlit UI

cd "$(dirname "$0")/.."

echo "🎨 Starting RAG Pipeline Frontend..."

# Check if virtualenv exists
if [ ! -d ".venv" ]; then
    echo "❌ Virtualenv not found. Run: python -m venv .venv && source .venv/bin/activate && pip install -e ."
    exit 1
fi

# Activate virtualenv
source .venv/bin/activate

# Get port from .env or use default
PORT=$(grep "^STREAMLIT_SERVER_PORT=" .env 2>/dev/null | cut -d= -f2)
PORT=${PORT:-8501}

# Run streamlit
echo "🎨 Frontend running at http://localhost:$PORT"

streamlit run client/app.py --server.port $PORT --server.address 0.0.0.0