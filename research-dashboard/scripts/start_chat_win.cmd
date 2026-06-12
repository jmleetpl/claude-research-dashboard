@echo off
REM Launch the local research-dashboard chat server (Windows).
REM Optional: set RESEARCH_DASHBOARD_DIR and RESEARCH_DASHBOARD_PORT before running.
setlocal
python "%~dp0chat_server.py" %*
endlocal
