# research-dashboard

A Claude Code plugin that scans your session logs across **all** projects and builds one unified research/work dashboard — Markdown + a visual HTML view — with an optional live chat panel and weekly auto-refresh.

## What it does

Claude Code writes a session log for every project you work in (`~/.claude/projects`). Over time these scatter across dozens of folders and it gets hard to remember what you have, where each thing stands, and what's next. This plugin:

1. **Digests** every project's session logs into a compact JSON (deterministic preprocessing — agents never read the raw multi-MB logs).
2. **Scans** each project in parallel with a `research-log-scanner` sub-agent to produce a status card (goal, stage, status, next actions, confidence).
3. **Consolidates** all cards with a `dashboard-curator` sub-agent into:
   - `DASHBOARD.md` — the operational dashboard (overview table, "needs attention", groups, your own notes section that is never overwritten),
   - `dashboard.html` — a self-contained visual view (no internet/CDN needed),
   - per-project detail cards under `projects/`.
4. Optionally produces a **weekly lab-meeting release** (`releases/lab-meeting-YYYY-MM-DD.md`) and a `WEEKLY_LOG.md` change log, computing the delta vs. the previous week.

Output goes to `~/research-dashboard` by default (override with the `RESEARCH_DASHBOARD_DIR` environment variable).

## Install

```
/plugin marketplace add jmleetpl/claude-research-dashboard
/plugin install research-dashboard
```

## Usage

Just ask, in English or Korean:

- "build my dashboard" / "대시보드 만들어줘"
- "show my research status" / "연구 현황 보여줘"
- "update the dashboard" / "대시보드 갱신해줘" (incremental — only rescans changed projects)
- "what's next?" / "다음 할 일 뭐야?"
- "find stalled projects" / "멈춘 연구 찾아줘"
- "give me the weekly lab-meeting release" / "주간 랩미팅 자료 만들어줘"

The skill auto-detects whether to do a full scan, an incremental update, or just answer from the existing dashboard.

## Output location

| Item | Path |
|------|------|
| Dashboard root | `RESEARCH_DASHBOARD_DIR` (default `~/research-dashboard`) |
| Main dashboard | `<root>/DASHBOARD.md` |
| Visual view | `<root>/dashboard.html` |
| Workspace (digests, scan cards, chat threads) | `<root>/_workspace/` |
| Weekly releases | `<root>/releases/` |

Set `RESEARCH_DASHBOARD_DIR` to put output anywhere you like.

## Optional: live chat

A local-only chat server lets you talk to a "lead" orchestrator persona or per-project agents next to the visual dashboard.

```
# Windows
research-dashboard\scripts\start_chat_win.cmd
# macOS / Linux
bash research-dashboard/scripts/start_chat_unix.sh
```

It opens `http://localhost:8765` (override with `RESEARCH_DASHBOARD_PORT`). Lookups use a fast model; edits use a more capable model and a parallel "ask every project" broadcast is available.

> ⚠️ **Security warning.** For write requests the chat server invokes `claude` with `--permission-mode acceptEdits`, meaning a chat message can **modify local files** (your dashboard metadata) without prompting. The weekly scheduler runs `claude` **unattended** with `bypassPermissions`. Run these only on a **trusted machine, as yourself**, and never expose the chat port to other hosts. The server binds to `127.0.0.1` only.

## Optional: weekly auto-refresh

Register a job that refreshes the dashboard and builds a lab-meeting release every Wednesday 08:00:

```
# Windows (Task Scheduler)
powershell -ExecutionPolicy Bypass -File research-dashboard\scripts\install_schedule_win.ps1
# macOS (launchd) / Linux (cron)
bash research-dashboard/scripts/install_schedule_unix.sh
```

Both scripts print how to remove the job and carry an unattended-execution warning (see the security note above).

## Requirements

- **Python 3.9+** (standard library only — no pip install needed).
- **claude CLI** on your `PATH` (`npm install -g @anthropic-ai/claude-code`). Required for the optional chat server and weekly scheduler; the core scan/curate flow runs inside Claude Code itself.

## Privacy

Everything stays on your machine. The plugin reads your local session logs and writes only to your dashboard directory. No data is sent anywhere except the normal model calls Claude Code already makes on your behalf.

## License

MIT — see [LICENSE](LICENSE).

---

## 한국어 안내

여러 Claude Code 프로젝트에 흩어진 세션 로그를 스캔해 **하나의 통합 연구/작업 대시보드**(Markdown + 시각화 HTML)를 만드는 플러그인입니다. 선택적으로 라이브 채팅과 주간 자동 갱신을 제공합니다.

### 무엇을 하나
- 모든 프로젝트의 세션 로그(`~/.claude/projects`)를 압축 다이제스트로 전처리합니다.
- 각 프로젝트를 `research-log-scanner` 서브에이전트로 병렬 스캔해 상태 카드를 만듭니다.
- `dashboard-curator` 서브에이전트가 이를 통합해 `DASHBOARD.md`, 시각화 `dashboard.html`, 프로젝트별 상세 카드를 생성합니다.
- 선택적으로 주간 랩미팅 릴리스(`releases/lab-meeting-YYYY-MM-DD.md`)와 변경 로그를 만듭니다.

출력 기본 위치는 `~/research-dashboard`이며 `RESEARCH_DASHBOARD_DIR` 환경변수로 바꿀 수 있습니다.

### 설치
```
/plugin marketplace add jmleetpl/claude-research-dashboard
/plugin install research-dashboard
```

### 사용법
"대시보드 만들어줘", "연구 현황 보여줘", "대시보드 갱신해줘", "다음 할 일 뭐야?", "주간 랩미팅 자료 만들어줘" 등으로 요청하면 됩니다(영어도 동일).

### 보안 경고
채팅 서버는 쓰기 요청 시 `claude`를 `acceptEdits`로 호출해 **로컬 대시보드 파일을 수정**할 수 있고, 주간 스케줄러는 `bypassPermissions`로 **무인 실행**됩니다. **신뢰하는 본인 PC에서 본인만** 사용하고, 채팅 포트를 외부에 노출하지 마세요(서버는 `127.0.0.1`에만 바인딩됩니다).

### 요구사항
- Python 3.9+ (표준 라이브러리만 사용)
- `PATH`에 `claude` CLI (채팅/스케줄러용)

### 개인정보
모든 데이터는 사용자의 로컬에만 머무릅니다. 플러그인은 로컬 세션 로그를 읽고 대시보드 디렉토리에만 씁니다.
