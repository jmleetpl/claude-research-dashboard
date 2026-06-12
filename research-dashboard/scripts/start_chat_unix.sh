#!/usr/bin/env bash
# Launch the local research-dashboard chat server (macOS / Linux).
# Optional: export RESEARCH_DASHBOARD_DIR and RESEARCH_DASHBOARD_PORT before running.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$DIR/chat_server.py" "$@"
