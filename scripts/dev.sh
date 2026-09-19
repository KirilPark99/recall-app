#!/usr/bin/env bash
# Dev-запуск: backend (uvicorn) + frontend (vite). Останавливает только свои дочерние процессы.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

if [ ! -d "$ROOT/.venv" ]; then
  echo "Создаю venv…"
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -q --upgrade pip
  "$ROOT/.venv/bin/pip" install -q -e "$ROOT/backend[dev]"
fi

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
export VITE_API_TARGET="http://127.0.0.1:$BACKEND_PORT"

cleanup() {
  # Завершаем только процессы, запущенные этим скриптом.
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "==> Миграции"
(cd "$ROOT/backend" && "$ROOT/.venv/bin/alembic" upgrade head)

echo "==> Backend: http://127.0.0.1:$BACKEND_PORT"
(cd "$ROOT/backend" && "$ROOT/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" --reload) &
BACKEND_PID=$!

echo "==> Frontend: http://127.0.0.1:$FRONTEND_PORT (proxy /api → $BACKEND_PORT)"
(cd "$ROOT/frontend" && npx vite --port "$FRONTEND_PORT" --strictPort) &
FRONTEND_PID=$!

wait
