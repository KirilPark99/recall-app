#!/usr/bin/env bash
# Полная проверка: backend-тесты, typecheck, build frontend.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

echo "==> Backend tests (pytest)"
"$ROOT/.venv/bin/python" -m pytest "$ROOT/backend/app/tests" -q

echo "==> Frontend typecheck"
(cd "$ROOT/frontend" && npx tsc -b --noEmit)

echo "==> Frontend build"
(cd "$ROOT/frontend" && npm run build)

echo "==> Проверки пройдены"
