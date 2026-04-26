#!/bin/bash
# Stop Frontend Streamlit UI

echo "🛑 Stopping Frontend..."

# Kill streamlit processes
pkill -f "streamlit run" 2>/dev/null

echo "✅ Frontend stopped"