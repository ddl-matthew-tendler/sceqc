#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   PORT=8501 bash app.sh
#   or: bash app.sh 8501

PORT="${PORT:-${1:-8888}}"
DOMINO_DOMAIN="${DOMINO_DOMAIN:-https://ksm.domino.tech}"

echo "========================================="
echo "Starting Flask application"
echo "Port: ${PORT}"
echo "========================================="

# ------------------------------------------------------------
# 1) Kill anything already listening on this port (best effort)
# ------------------------------------------------------------
if command -v fuser &>/dev/null; then
  echo "Killing any process listening on port ${PORT}..."
  fuser -k "${PORT}/tcp" || true
  sleep 1
else
  echo "fuser not available, skipping port cleanup."
fi

# Also clean up common stray processes (best effort)
pkill -f "flask run"   2>/dev/null || true
pkill -f "python app.py" 2>/dev/null || true

# ------------------------------------------------------------
# 2) Print the Domino proxy URL (this is the one to open)
# ------------------------------------------------------------
if [ -n "${DOMINO_RUN_HOST_PATH:-}" ]; then
  CLEAN_PATH="$(echo "${DOMINO_RUN_HOST_PATH}" | sed 's|/r||g')"
  URL="${DOMINO_DOMAIN}${CLEAN_PATH}proxy/${PORT}/"
  echo
  echo "========================================="
  echo "Flask URL (open this in your browser):"
  echo "${URL}"
  echo "========================================="
  echo
else
  echo "DOMINO_RUN_HOST_PATH not set."
  echo "App will be available locally at: http://0.0.0.0:${PORT}"
fi

# ------------------------------------------------------------
# 3) Launch Flask (THIS is the critical missing piece)
# ------------------------------------------------------------
export FLASK_APP=app.py
export FLASK_ENV=development

echo "Launching Flask on 0.0.0.0:${PORT} ..."
exec python -m flask run \
  --host=0.0.0.0 \
  --port="${PORT}"