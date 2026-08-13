#!/bin/sh
# Railway / Docker entrypoint — expand PORT in a real shell (never pass literal $PORT).
set -e
export WEOS_DATA_DIR="${WEOS_DATA_DIR:-/tmp/weos-data}"
mkdir -p "$WEOS_DATA_DIR/projects" "$WEOS_DATA_DIR/output"
PORT="${PORT:-8000}"
# Keep-alive 75s so 40–100 page Quote PDFs are not cut by idle proxy timeouts.
exec uvicorn WEOS.api.main:app --host 0.0.0.0 --port "$PORT" --timeout-keep-alive 75
