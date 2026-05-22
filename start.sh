#!/bin/bash
set -e
cd "$(dirname "$0")"
echo "Starting LeadFlow AI..."

# Check .env exists
if [ ! -f .env ]; then
  cp .env.example .env
  echo "WARNING: Created .env from template. Add your GROQ_API_KEY and restart."
  exit 1
fi

# Create data dir
mkdir -p data

# Set up Python venv if not present
if [ ! -f venv/bin/activate ]; then
  echo "Creating Python virtual environment..."
  python3 -m venv venv
fi
source venv/bin/activate

# Install Python deps into venv
echo "Installing Python dependencies..."
pip install -r requirements.txt -q

# Install Node deps
echo "Installing Node dependencies..."
cd whatsapp && npm install --silent && cd ..

# Start Node WhatsApp server in background
echo "Starting WhatsApp bridge server on port 3001..."
node whatsapp/server.js &
WA_PID=$!
echo "WhatsApp server started (PID $WA_PID)"

# Give Node server a moment to start
sleep 2

# Start FastAPI using venv uvicorn
echo "Starting FastAPI on http://localhost:8000"
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload &
FASTAPI_PID=$!

# Cleanup on exit
trap "echo 'Shutting down...'; kill $WA_PID 2>/dev/null; kill $FASTAPI_PID 2>/dev/null" EXIT INT TERM

wait $FASTAPI_PID
