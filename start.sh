#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# start.sh  —  Launch both backend and frontend in parallel
# Usage: bash start.sh
# ─────────────────────────────────────────────────────────────────────────────
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   Patna STC — Traffic Control Dashboard  ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── Backend ──────────────────────────────────────────────────────────────────
echo "▶ Starting FastAPI backend on http://localhost:8000 …"
cd "$ROOT/backend"

if ! command -v uvicorn &>/dev/null; then
  echo "  Installing backend dependencies…"
  pip install -r requirements.txt -q
fi

uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!

# ── Frontend ─────────────────────────────────────────────────────────────────
echo "▶ Starting Vite frontend on http://localhost:5173 …"
cd "$ROOT/frontend"

if [ ! -d node_modules ]; then
  echo "  Installing frontend dependencies…"
  npm install --silent
fi

npm run dev &
FRONTEND_PID=$!

# ── Cleanup on Ctrl-C ─────────────────────────────────────────────────────────
trap "echo ''; echo 'Shutting down…'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" SIGINT SIGTERM

echo ""
echo "  Dashboard → http://localhost:5173"
echo "  API docs  → http://localhost:8000/docs"
echo "  Press Ctrl+C to stop both servers."
echo ""

wait
