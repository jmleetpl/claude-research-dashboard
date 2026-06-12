# Install a weekly auto-refresh for the research dashboard (Windows Task Scheduler).
#
# Registers a task that runs every Wednesday 08:00, launching claude headless to run
# the research-dashboard skill in weekly mode.
#
# SECURITY / PERMISSIONS NOTE:
#   This task runs claude with --permission-mode bypassPermissions, UNATTENDED, as your user.
#   That means it can read your session logs and write/modify files under your dashboard dir
#   without prompting. Only install on a trusted machine that is yours. Review the prompt below
#   before installing. To remove later:  schtasks /Delete /TN "ResearchDashboard-Weekly" /F
#
# Usage:  powershell -ExecutionPolicy Bypass -File install_schedule_win.ps1

$ErrorActionPreference = 'Stop'

# Locate claude on PATH, with fallback
$claude = (Get-Command claude -ErrorAction SilentlyContinue).Source
if (-not $claude) { $claude = Join-Path $env:APPDATA 'npm\claude.cmd' }
if (-not (Test-Path $claude)) {
    Write-Error "claude CLI not found. Install it (npm install -g @anthropic-ai/claude-code) and ensure it is on PATH."
    exit 1
}

# Dashboard dir: RESEARCH_DASHBOARD_DIR or ~/research-dashboard
$dashDir = $env:RESEARCH_DASHBOARD_DIR
if (-not $dashDir) { $dashDir = Join-Path $env:USERPROFILE 'research-dashboard' }
$runDir = Join-Path $dashDir '_workspace\cron-runs'
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

# The runner script written next to the dashboard dir (self-contained instruction for headless claude).
$runner = Join-Path $dashDir 'run_weekly.ps1'
$runnerBody = @'
$ErrorActionPreference = 'Continue'
$claude = (Get-Command claude -ErrorAction SilentlyContinue).Source
if (-not $claude) { $claude = Join-Path $env:APPDATA 'npm\claude.cmd' }
$dashDir = $env:RESEARCH_DASHBOARD_DIR
if (-not $dashDir) { $dashDir = Join-Path $env:USERPROFILE 'research-dashboard' }
$runDir = Join-Path $dashDir '_workspace\cron-runs'
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
$stamp = Get-Date -Format 'yyyy-MM-dd_HHmm'
$log = Join-Path $runDir "run_$stamp.log"

$prompt = @"
Run the research-dashboard skill in "weekly mode". This is the weekly lab-meeting routine that runs automatically every Wednesday on the local PC. Use the system-provided today's date; do not guess the date.

Tasks (skill Phases 1-4):
1. Run the bundled digest_sessions.py to refresh digests for all session logs under ~/.claude/projects.
2. Compare last_active in the previous scan cards (_workspace/scans/*.json) against the new digests to identify changed/new projects only.
3. Re-scan only the changed/new projects with the research-log-scanner agent (parallel; skip scanning if nothing changed).
4. Incrementally update DASHBOARD.md with the dashboard-curator agent (preserve the User notes section).
5. Per Phase 4, create releases/lab-meeting-{today}.md and prepend this round's entry to the top of WEEKLY_LOG.md. Compute the delta vs. the previous release (new/progress/transitions), but always create the release even with no new research.
6. Finally run the bundled render_dashboard_html.py to regenerate dashboard.html from the latest scan cards.

Finish with a one-line summary (new K, progressed M, release file path).
"@

"=== Research Dashboard Weekly Run: $stamp ===" | Out-File -FilePath $log -Encoding utf8
& $claude -p $prompt --permission-mode bypassPermissions *>> $log
"=== exit code: $LASTEXITCODE ===" | Out-File -FilePath $log -Append -Encoding utf8
'@
Set-Content -Path $runner -Value $runnerBody -Encoding utf8
Write-Host "Wrote weekly runner: $runner"

$action = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$runner`""
schtasks /Create /TN "ResearchDashboard-Weekly" /TR $action /SC WEEKLY /D WED /ST 08:00 /F
Write-Host "Registered scheduled task 'ResearchDashboard-Weekly' (every Wed 08:00)."
Write-Host "Remove with:  schtasks /Delete /TN `"ResearchDashboard-Weekly`" /F"
