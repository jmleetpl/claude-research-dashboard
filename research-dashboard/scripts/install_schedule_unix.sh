#!/usr/bin/env bash
# Install a weekly auto-refresh for the research dashboard (macOS launchd / Linux cron).
#
# Registers a job that runs every Wednesday 08:00, launching claude headless to run the
# research-dashboard skill in weekly mode.
#
# SECURITY / PERMISSIONS NOTE:
#   This job runs claude with --permission-mode bypassPermissions, UNATTENDED, as your user.
#   It can read your session logs and write/modify files under your dashboard dir without
#   prompting. Only install on a trusted machine that is yours. Review the runner before installing.
#
# Usage:  bash install_schedule_unix.sh          # auto-detects launchd (macOS) or cron (Linux)
#         bash install_schedule_unix.sh --cron    # force cron
#         bash install_schedule_unix.sh --print   # just print the runner + cron line, install nothing
set -euo pipefail

DASH_DIR="${RESEARCH_DASHBOARD_DIR:-$HOME/research-dashboard}"
RUN_DIR="$DASH_DIR/_workspace/cron-runs"
RUNNER="$DASH_DIR/run_weekly.sh"
mkdir -p "$RUN_DIR"

# Locate claude
CLAUDE="$(command -v claude || true)"
if [ -z "$CLAUDE" ]; then
  for c in "$HOME/.npm-global/bin/claude" "$HOME/.local/bin/claude" /usr/local/bin/claude /opt/homebrew/bin/claude; do
    [ -x "$c" ] && CLAUDE="$c" && break
  done
fi
if [ -z "$CLAUDE" ]; then
  echo "claude CLI not found. Install it (npm install -g @anthropic-ai/claude-code) and ensure it is on PATH." >&2
  exit 1
fi

# Write the self-contained weekly runner
cat > "$RUNNER" <<'RUNNER_EOF'
#!/usr/bin/env bash
set -uo pipefail
DASH_DIR="${RESEARCH_DASHBOARD_DIR:-$HOME/research-dashboard}"
RUN_DIR="$DASH_DIR/_workspace/cron-runs"
mkdir -p "$RUN_DIR"
CLAUDE="$(command -v claude || true)"
if [ -z "$CLAUDE" ]; then
  for c in "$HOME/.npm-global/bin/claude" "$HOME/.local/bin/claude" /usr/local/bin/claude /opt/homebrew/bin/claude; do
    [ -x "$c" ] && CLAUDE="$c" && break
  done
fi
STAMP="$(date +%Y-%m-%d_%H%M)"
LOG="$RUN_DIR/run_$STAMP.log"
PROMPT='Run the research-dashboard skill in "weekly mode". This is the weekly lab-meeting routine that runs automatically every Wednesday on the local machine. Use the system-provided today'"'"'s date; do not guess the date.

Tasks (skill Phases 1-4):
1. Run the bundled digest_sessions.py to refresh digests for all session logs under ~/.claude/projects.
2. Compare last_active in the previous scan cards (_workspace/scans/*.json) against the new digests to identify changed/new projects only.
3. Re-scan only the changed/new projects with the research-log-scanner agent (parallel; skip scanning if nothing changed).
4. Incrementally update DASHBOARD.md with the dashboard-curator agent (preserve the User notes section).
5. Per Phase 4, create releases/lab-meeting-{today}.md and prepend this round'"'"'s entry to the top of WEEKLY_LOG.md. Compute the delta vs. the previous release (new/progress/transitions), but always create the release even with no new research.
6. Finally run the bundled render_dashboard_html.py to regenerate dashboard.html from the latest scan cards.

Finish with a one-line summary (new K, progressed M, release file path).'
{
  echo "=== Research Dashboard Weekly Run: $STAMP ==="
  "$CLAUDE" -p "$PROMPT" --permission-mode bypassPermissions
  echo "=== exit code: $? ==="
} >> "$LOG" 2>&1
RUNNER_EOF
chmod +x "$RUNNER"
echo "Wrote weekly runner: $RUNNER"

CRON_LINE="0 8 * * 3 $RUNNER"

if [ "${1:-}" = "--print" ]; then
  echo "--- runner: $RUNNER ---"
  echo "--- cron line (every Wed 08:00) ---"
  echo "$CRON_LINE"
  exit 0
fi

OS="$(uname -s)"
USE_CRON=0
[ "${1:-}" = "--cron" ] && USE_CRON=1
[ "$OS" != "Darwin" ] && USE_CRON=1   # Linux -> cron

if [ "$USE_CRON" = "0" ]; then
  # macOS: launchd
  PLIST="$HOME/Library/LaunchAgents/com.research-dashboard.weekly.plist"
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.research-dashboard.weekly</string>
  <key>ProgramArguments</key>
    <array><string>/bin/bash</string><string>$RUNNER</string></array>
  <key>StartCalendarInterval</key>
    <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardErrorPath</key><string>$RUN_DIR/launchd.err</string>
  <key>StandardOutPath</key><string>$RUN_DIR/launchd.out</string>
</dict></plist>
PLIST_EOF
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST"
  echo "Loaded launchd agent: $PLIST (every Wed 08:00)."
  echo "Remove with:  launchctl unload \"$PLIST\" && rm \"$PLIST\""
else
  # Linux: cron
  ( crontab -l 2>/dev/null | grep -v -F "$RUNNER" ; echo "$CRON_LINE" ) | crontab -
  echo "Added cron line (every Wed 08:00):"
  echo "  $CRON_LINE"
  echo "Remove with:  crontab -e   (delete the line referencing $RUNNER)"
fi
