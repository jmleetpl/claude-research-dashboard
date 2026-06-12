---
name: research-dashboard
description: Unified orchestrator that manages all of your Claude Code research/work projects in a single dashboard. Scans session logs (~/.claude/projects) to determine per-project progress, generates and updates a Markdown dashboard plus a consistently-styled visual HTML view (dashboard.html, rendered by a deterministic script on every run) under RESEARCH_DASHBOARD_DIR (default ~/research-dashboard), and produces optional weekly release notes and change logs. Use this skill for any request about the status, organization, cross-project management, or weekly reporting of multiple research/work projects. Trigger keywords (English): "research status", "project overview", "dashboard", "show my progress", "what was I working on", "where did I leave off", "update/refresh/rescan the dashboard", "find stalled projects", "what's next", "weekly research update", "lab-meeting dashboard", "this week's new projects", "weekly release". Trigger keywords (Korean): "연구 현황", "프로젝트 정리", "대시보드", "진행상황 보여줘", "내 연구 뭐 있었지", "어디까지 했더라", "대시보드 업데이트/갱신/다시 스캔", "멈춘 연구 찾아줘", "다음 할 일", "주간 연구 업데이트", "랩미팅 대시보드/자료", "이번 주 새로 생긴 연구", "주간 릴리스". This skill is for managing projects ACROSS folders — single-paper writing/revision or single-folder cleanup belong to other skills. This skill handles cross-project consolidation only.
---

# Research Dashboard — Cross-Project Orchestrator

Scans and consolidates the progress of research/work scattered across many Claude Code projects into a single dashboard.

**Execution mode: sub-agents (fan-out / fan-in).** Scanners do not need to talk to each other (each analyzes one project independently); only their results are collected. So this uses parallel `Agent` tool calls without team overhead.

## Paths

This plugin resolves paths at runtime — nothing is hardcoded.

| Item | Path |
|------|------|
| Session log root | `~/.claude/projects/` |
| Dashboard root | `RESEARCH_DASHBOARD_DIR` (default `~/research-dashboard`) |
| Main dashboard | `<dashboard_root>/DASHBOARD.md` |
| Workspace | `<dashboard_root>/_workspace/` |
| Digests | `<dashboard_root>/_workspace/digests/{project_id}.json` |
| Status cards | `<dashboard_root>/_workspace/scans/{project_id}.json` |
| Plugin scripts | `${CLAUDE_PLUGIN_ROOT}/scripts/...` |

> The dashboard output directory is `RESEARCH_DASHBOARD_DIR` if set, otherwise `~/research-dashboard`. The scripts create all needed directories automatically. Plugin-bundled scripts are referenced via the `${CLAUDE_PLUGIN_ROOT}` environment variable that Claude Code exposes for the plugin root.

## Phase 0: Context check (determine execution mode)

1. Check whether `DASHBOARD.md` exists in the dashboard root:
   - **Absent** → initial full scan (Phases 1–3).
   - **Present + an "update/refresh/rescan" request** → incremental update: compare `last_active` in `_workspace/digests/_index.json` against the actual mtime of each log directory, and run Phases 1–3 **only for changed projects**.
   - **Present + only a specific project mentioned** → re-run that project only.
   - **Present + a simple query** ("show status", "what's next") → answer by reading `DASHBOARD.md` without scanning. If the last refresh was more than 7 days ago, suggest a refresh.
2. If the user manually corrects a project's status in the dashboard → edit the dashboard and that status card directly (no scan needed).

## Phase 1: Build digests (deterministic preprocessing)

Raw logs are tens of MB, so agents must not read them directly. Run the bundled script:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/digest_sessions.py" --out "<dashboard_root>/_workspace/digests"
```

On Windows use `python`; on macOS/Linux use `python3`. Resolve `<dashboard_root>` from `RESEARCH_DASHBOARD_DIR` (default `~/research-dashboard`). For incremental updates, pass `--only <project_id> ...` to process only changed directories. Use the emitted `_index.json` to get the list of targets (including directories with 0 sessions).

## Phase 2: Project scan (fan-out)

For each project with at least one session, spawn a `research-log-scanner` agent **in parallel** (this plugin provides it as `subagent_type: research-log-scanner`, built on the built-in `general-purpose` agent; send the independent calls in a single message).

Include in each scanner prompt:
- An instruction to first read the `research-log-scanner` agent definition and follow its protocol.
- The `project_id`, `digest_file`, and `output_file` paths.
- The digest's `working_dir` (for cross-checking the actual working folder).

If a scanner fails, retry once; if it fails again, proceed without that card but note the omission in Phase 3.

## Phase 3: Dashboard consolidation (fan-in)

After all scanners complete, spawn one `dashboard-curator` agent (`subagent_type: dashboard-curator`). Include in the prompt:
- An instruction to first read the `dashboard-curator` agent definition and follow its protocol.
- The `scans_dir` and `dashboard_dir` paths.
- The list of failed / zero-session projects.

Report the curator's returned summary (stats + items needing attention) to the user. Keep it concise: N active, M stalled, the 2–3 most urgent actions, and the dashboard file path — do not copy the whole table.

## Phase 3.5: Render the visual HTML — ALWAYS, every run

`dashboard.html` is the **canonical visual view**, and it is produced by a **deterministic** script (`render_dashboard_html.py`). The same script yields the **same design on every machine and every run** — only the data differs. The Markdown `DASHBOARD.md` is written by an LLM (the curator) and naturally varies in wording/structure run to run; the HTML does not. So **always run this at the end of every build/update** (initial, incremental, and weekly alike) — this is what keeps the look consistent across computers and over time:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/render_dashboard_html.py" --scans "<dashboard_root>/_workspace/scans" --out "<dashboard_root>/dashboard.html" --date {today}
```

On Windows use `python`; on macOS/Linux use `python3`. Then tell the user to open `<dashboard_root>/dashboard.html`. **Never hand-write HTML or vary the design per run — the script owns the design.** If you only answered a simple query in Phase 0 (no scan), skip this step.

## Phase 4: Weekly lab-meeting release (weekly routine)

On a weekly-update request ("weekly update", "lab-meeting materials", "weekly release") or a scheduled weekly run, do the following after Phases 1–3. **Always produce a release even if there are no new projects this week** — "no change" is still worth reporting at a lab meeting.

### 4-1. Compute the change delta

Compute what changed since the most recent release (newest file in `releases/`):
- **New projects**: project_ids not present before (newly created scan cards).
- **Progress**: projects whose `last_active` was updated after the previous release date.
- **Status transitions**: projects whose `status`/`current_stage` changed vs. the previous card (e.g. idle→active, drafting→submitted).
- **No change**: everything else.

Exclude infrastructure/meta (non-research) projects from the delta, but mention any new infrastructure item in a single line at the bottom of the release. A lab-meeting audience wants research progress.

### 4-2. Release artifacts

**`releases/lab-meeting-{YYYY-MM-DD}.md`** (today's date):
- Header: weekly round number, date, one-line summary (the single key sentence for the week).
- `## This week at a glance` — active/idle/stalled/done counts + delta vs. previous release (e.g. `active 6 (+1)`).
- `## New / progressed this week` — only new, progressed, or transitioned items. Each: project name · what changed · the next single step. **If nothing changed, state "No new or progressed research this week."**
- `## Needs discussion (lab-meeting agenda)` — items blocked on a user decision/input (the research items from the dashboard's attention section). For each, state what decision/input unblocks it — so it can be decided live at the meeting.
- `## Full research status` — research projects only (exclude infra/meta), compact table: Project | Stage | Status | Last active | Next action.
- `## Unchanged in-progress research` — one line each (just a reminder they exist).

This is for the lab meeting, so keep the tone concise and presentation-oriented. Its role differs from `DASHBOARD.md` (operational detail).

**Visual HTML:** `dashboard.html` is already regenerated by Phase 3.5 (which runs on every build). Just confirm it ran for this release; no separate render is needed.

### 4-3. Append the weekly log

Prepend one block for this round to the top of **`WEEKLY_LOG.md`** (reverse-chronological; append, preserving existing content):

```markdown
## {YYYY-MM-DD} (weekly)
- Scan: total N / changes detected M / new K
- New research: {list or "none"}
- Progress: {project: what / or "none"}
- Status transitions: {project: A→B / or "none"}
- Release: releases/lab-meeting-{YYYY-MM-DD}.md
```

### 4-4. Report

Report only the release path and this week's delta summary (new K, progressed M, number of agenda items).

> Never guess the date — use the system-provided today's date. The date in the release filename, log, and header must all match.

## Optional: live chat server

A local-only chat server (`scripts/chat_server.py`) lets the user talk to a "lead" orchestrator persona or per-project agent personas alongside the visual dashboard. See the README for launch instructions and the security warning. Set `RESEARCH_DASHBOARD_PORT` to override the default port (8765).

## Data flow

```
session logs (.jsonl) ──[digest_sessions.py]──> digests/*.json
  ──[scanner ×N parallel]──> scans/*.json ──┬─[curator ×1]──────────> DASHBOARD.md + projects/*.md   (LLM, varies)
                                            └─[render_dashboard_html.py]─> dashboard.html             (deterministic, fixed design)
```

All handoffs are **file-based** (agreed-upon paths). Intermediate artifacts (`_workspace/`) are the baseline for incremental updates, so do not delete them.

## Error handling

| Situation | Response |
|-----------|----------|
| digest script fails | Check stderr, retry once. If a specific jsonl fails to parse, skip that file, proceed, and note it. |
| some scanners fail | Retry once → if still failing, mark the row "scan failed" in the dashboard (no silent omission). |
| working folder inaccessible (external drive, etc.) | Build the card from logs only, `confidence: low`. |
| user manual edit conflicts with a card | User edit wins, annotate with `(per log: ...)`. |

## Test scenarios

**Normal (initial build):** "Organize all my research into a dashboard" → Phase 0 sees no DASHBOARD.md → full digest → N scanners in parallel → curator consolidation → DASHBOARD.md created, summary reported.

**Normal (incremental):** "Update the dashboard" → identify 2 projects with mtime changes vs. `_index.json` → digest with `--only` → only 2 scanners → curator merge → add one history line.

**Error:** one scanner fails after retry → pass the failure list to the curator → mark that row "scan failed (retry needed)" in the dashboard table → include it in the user report.
