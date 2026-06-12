#!/usr/bin/env python3
"""Research dashboard live chat server (local-only, standard library only).

Bridges browser <-> this server <-> claude (headless).
- Left: the visual dashboard (dashboard.html) in an iframe.
- Right: a chat panel. Pick the "lead" (orchestrator) persona or an individual
  per-project agent and talk to it.
- When you send a message the server runs claude headless as that persona to reply,
  applies any requested change (status/notes/priority) to the dashboard metadata,
  then regenerates the HTML.

Run:  python chat_server.py   (a browser opens automatically)
SECURITY: For write requests this server calls claude with --permission-mode acceptEdits,
          i.e. a chat message can modify local files (dashboard metadata). Run only on a
          trusted machine, as yourself. Do not expose the port to other hosts.

Config (environment variables):
- RESEARCH_DASHBOARD_DIR : dashboard root (default ~/research-dashboard)
- RESEARCH_DASHBOARD_PORT: server port (default 8765)
"""
import json
import os
import sys
import subprocess
import shutil
import webbrowser
import glob
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# Hybrid models: fast Haiku for reads, more accurate Sonnet for writes
MODEL_READ = "claude-haiku-4-5"
MODEL_WRITE = "claude-sonnet-4-6"
# Write-intent detection keywords (English + Korean)
WRITE_HINTS = [
    "edit", "change", "update", "refresh", "move", "set", "mark", "add", "remove",
    "delete", "note", "record", "priority", "done", "complete", "rename", "apply",
    "수정", "바꿔", "변경", "옮겨", "올려", "내려", "추가", "지워", "삭제",
    "메모", "표시", "완료", "반영", "업데이트", "갱신", "우선순위", "기록", "설정", "처리",
]


def base_dir():
    return os.environ.get("RESEARCH_DASHBOARD_DIR") or os.path.join(
        os.path.expanduser("~"), "research-dashboard"
    )


ROOT = base_dir()
SCANS = os.path.join(ROOT, "_workspace", "scans")
CHAT_DIR = os.path.join(ROOT, "_workspace", "chat")
DASHBOARD_HTML = os.path.join(ROOT, "dashboard.html")
RENDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "render_dashboard_html.py")
PORT = int(os.environ.get("RESEARCH_DASHBOARD_PORT", "8765"))
HISTORY_TURNS = 8


def find_claude():
    """Locate the claude CLI cross-platform: PATH first, then known fallbacks."""
    found = shutil.which("claude")
    if found:
        return found
    candidates = []
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", "")
        candidates += [
            os.path.join(appdata, "npm", "claude.cmd"),
            os.path.join(appdata, "npm", "claude.ps1"),
            os.path.join(appdata, "npm", "claude.exe"),
        ]
    else:
        home = os.path.expanduser("~")
        candidates += [
            os.path.join(home, ".npm-global", "bin", "claude"),
            os.path.join(home, ".local", "bin", "claude"),
            "/usr/local/bin/claude",
            "/opt/homebrew/bin/claude",
        ]
    for cand in candidates:
        if cand and os.path.exists(cand):
            return cand
    return None


CLAUDE = find_claude()


def load_cards():
    cards = []
    for f in sorted(glob.glob(os.path.join(SCANS, "*.json"))):
        try:
            cards.append(json.load(open(f, encoding="utf-8")))
        except Exception:
            pass
    return cards


def recipients():
    out = [{"id": "lead", "title": "Lead (orchestrator)", "type": "lead"}]
    for c in load_cards():
        out.append({"id": c["project_id"],
                    "title": c.get("title") or c["project_id"],
                    "type": c.get("type", ""),
                    "status": c.get("status", "")})
    return out


def thread_path(rid):
    os.makedirs(CHAT_DIR, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in rid)
    return os.path.join(CHAT_DIR, f"{safe}.jsonl")


def load_history(rid):
    p = thread_path(rid)
    if not os.path.exists(p):
        return []
    msgs = []
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                msgs.append(json.loads(line))
            except Exception:
                pass
    return msgs


def append_history(rid, role, text):
    with open(thread_path(rid), "a", encoding="utf-8") as f:
        f.write(json.dumps({"role": role, "text": text,
                            "ts": datetime.now().isoformat(timespec="seconds")},
                           ensure_ascii=False) + "\n")


def portfolio_summary():
    lines = []
    for c in load_cards():
        lines.append(f"- [{c['project_id']}] {c.get('title')} | {c.get('type')} | "
                     f"{c.get('current_stage')} | {c.get('status')} | {c.get('last_active')}")
    return "\n".join(lines)


def build_prompt(rid, message, write):
    hist = load_history(rid)[-HISTORY_TURNS:]
    convo = ""
    for m in hist[:-1]:  # exclude the current message we just appended
        who = "User" if m["role"] == "user" else "Me"
        convo += f"{who}: {m['text']}\n"

    rules = (
        "Behavior rules (follow strictly):\n"
        "1) You are a chat partner. Reply briefly (3-6 sentences), like a person in a messenger. "
        "Match the user's language.\n"
        "2) Never auto-dump a full 'portfolio status report' or long tables. Answer only what is asked.\n"
        "3) For a lookup question, answer directly from the data provided below.\n"
        + ("4) The user asked for an edit/instruction/note. Actually modify the 'writable files' below "
           "with the Edit tool, and end your reply with one line '✏️ applied: ...' stating what you changed. "
           "Do not just describe it — actually edit the file.\n"
           if write else
           "4) This message is plain conversation/lookup. Do not modify any file.\n")
        + "5) Never touch the original research working folders (papers/data/code) — only the dashboard metadata."
    )

    if rid == "lead":
        persona = ("You are the 'lead' who oversees this user's entire project portfolio.\n\n"
                   "Current projects (project_id | title | type | stage | status | last active):\n"
                   + portfolio_summary())
        write_scope = (f"Writable files: {os.path.join(SCANS, '<project_id>.json')} "
                       f"(that card's status / next_actions / notes / progress_summary fields), "
                       f"or the 'User notes' section of {os.path.join(ROOT, 'DASHBOARD.md')}.")
    else:
        c = {x["project_id"]: x for x in load_cards()}.get(rid, {})
        persona = (f"You are the agent in charge of the '{c.get('title', rid)}' project.\n"
                   f"Stage: {c.get('current_stage','?')} / Status: {c.get('status','?')} / "
                   f"Last active: {c.get('last_active','?')}\n"
                   f"Goal: {c.get('goal','')}\n"
                   f"Progress: {c.get('progress_summary','')}\n"
                   f"Next actions: {c.get('next_actions')}\n"
                   f"Notes: {c.get('notes','')}")
        write_scope = (f"Writable files: only the status / next_actions / notes / progress_summary fields of "
                       f"{os.path.join(SCANS, rid + '.json')}.")

    return (persona + "\n\n" + rules + ("\n" + write_scope if write else "") + "\n\n"
            + ("Recent conversation:\n" + convo + "\n" if convo else "")
            + "User's new message: " + message)


def is_write_intent(message):
    low = message.lower()
    return any(k in message or k in low for k in WRITE_HINTS)


def call_claude(prompt, write=False, timeout=600):
    """Headless claude call.

    Key: --disable-slash-commands turns off all skills. Without it, a global CLAUDE.md +
    the research-dashboard skill would auto-trigger every time, dropping into 'scan -> report'
    mode and ignoring the actual edit/conversation instruction (a known past bug).
    Reads: Read-only + Haiku (fast). Writes: Read,Edit,Write + Sonnet + acceptEdits."""
    if not CLAUDE:
        return ("[error] could not find the claude CLI. Install it and ensure it is on PATH "
                "(npm install -g @anthropic-ai/claude-code).")
    if write:
        model, tools, perm = MODEL_WRITE, "Read,Edit,Write", "acceptEdits"
    else:
        model, tools, perm = MODEL_READ, "Read", "default"
    cmd = [CLAUDE, "-p", prompt,
           "--model", model,
           "--tools", tools,
           "--permission-mode", perm,
           "--disable-slash-commands",
           "--no-session-persistence"]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=ROOT, timeout=timeout,
        )
        out = (proc.stdout or "").strip()
        if not out:
            out = "[empty response] " + (proc.stderr or "")[:500]
        return out
    except subprocess.TimeoutExpired:
        return "[timeout] The response took too long. Try splitting your message into smaller parts."
    except Exception as e:
        return f"[error] {e}"


def is_broadcast(message):
    """Is this a portfolio-wide question to the lead (-> parallel fan-out to agents)?"""
    low = message.lower()
    kws = ["each project", "all projects", "everyone", "every project", "one line",
           "one-line", "briefing", "per project", "all of them",
           "각 연구", "전체", "모든", "모두", "한줄", "한 줄", "브리핑", "전부",
           "프로젝트별", "각각", "각 프로젝트"]
    return any(k in message or k in low for k in kws)


def broadcast(message):
    """Ask every project agent for a one-line report simultaneously (parallel, Haiku)."""
    cards = [c for c in load_cards() if c.get("type") not in ("infra/meta", "인프라/메타")]

    def ask(c):
        pid = c["project_id"]
        p = (f"You are in charge of the '{c.get('title', pid)}' project. Card summary:\n"
             f"- Stage: {c.get('current_stage')}, Status: {c.get('status')}, "
             f"Last active: {c.get('last_active')}\n"
             f"- Progress: {c.get('progress_summary', '')[:600]}\n"
             f"- Next actions: {c.get('next_actions')}\n\n"
             f"The lead asks: \"{message}\"\n"
             f"Answer about THIS project only, in exactly one line (under 100 chars), key point only, "
             f"no preamble. Do not read files or use tools — answer from the summary above.")
        ans = call_claude(p, write=False, timeout=180).strip().replace("\n", " ")
        return c.get("title", pid), ans

    results = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for title, ans in ex.map(ask, cards):
            results.append(f"- **{title}**: {ans}")
    return "Lead here — each project agent reported in parallel:\n\n" + "\n".join(results)


def regen_dashboard():
    try:
        subprocess.run([sys.executable, RENDER, "--date", datetime.now().date().isoformat()],
                       capture_output=True, timeout=120)
    except Exception:
        pass


INDEX = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Research Dashboard + Chat</title>
<style>
 *{box-sizing:border-box} html,body{margin:0;height:100%;font-family:"Segoe UI",system-ui,-apple-system,"Noto Sans CJK KR",sans-serif}
 .layout{display:flex;height:100vh}
 .dash{flex:2;border:0;min-width:0}
 .chat{flex:1;min-width:360px;max-width:460px;display:flex;flex-direction:column;
       border-left:1px solid #e2e8f0;background:#f8fafc}
 .chat-head{padding:12px 16px;background:#1e293b;color:#fff}
 .chat-head h2{margin:0 0 8px;font-size:15px}
 .chat-head select{width:100%;padding:7px;border-radius:8px;border:0;font-size:13px}
 .msgs{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px}
 .m{max-width:85%;padding:9px 13px;border-radius:13px;font-size:13px;line-height:1.5;white-space:pre-wrap;word-break:break-word}
 .m.user{align-self:flex-end;background:#2563eb;color:#fff;border-bottom-right-radius:3px}
 .m.agent{align-self:flex-start;background:#fff;border:1px solid #e2e8f0;border-bottom-left-radius:3px}
 .m.sys{align-self:center;background:#fef3c7;color:#92400e;font-size:12px}
 .ts{display:block;font-size:10px;opacity:.6;margin-top:3px}
 .compose{display:flex;gap:8px;padding:12px;border-top:1px solid #e2e8f0;background:#fff}
 .compose textarea{flex:1;resize:none;height:46px;padding:9px;border:1px solid #cbd5e1;border-radius:9px;font-size:13px;font-family:inherit}
 .compose button{padding:0 18px;border:0;border-radius:9px;background:#1e293b;color:#fff;cursor:pointer;font-size:13px}
 .compose button:disabled{opacity:.5;cursor:default}
 .hint{font-size:11px;color:#94a3b8;padding:0 12px 8px;background:#fff}
</style></head><body>
<div class="layout">
  <iframe id="dash" class="dash" src="/dashboard.html"></iframe>
  <div class="chat">
    <div class="chat-head">
      <h2>💬 Research chat</h2>
      <select id="rcpt" onchange="loadHist()"></select>
    </div>
    <div class="msgs" id="msgs"></div>
    <div class="hint">Enter to send · Shift+Enter for newline · replies can take seconds to minutes</div>
    <div class="compose">
      <textarea id="inp" placeholder="Type a message..." onkeydown="kd(event)"></textarea>
      <button id="send" onclick="send()">Send</button>
    </div>
  </div>
</div>
<script>
let rcpts=[];
async function init(){
  rcpts=await (await fetch('/api/recipients')).json();
  const sel=document.getElementById('rcpt');
  sel.innerHTML=rcpts.map(r=>`<option value="${r.id}">${r.title}</option>`).join('');
  loadHist();
}
async function loadHist(){
  const id=document.getElementById('rcpt').value;
  const h=await (await fetch('/api/history?thread='+encodeURIComponent(id))).json();
  const box=document.getElementById('msgs'); box.innerHTML='';
  if(!h.length){ addMsg('sys','First conversation with this recipient. Ask a question or give an instruction.'); }
  h.forEach(m=>addMsg(m.role==='user'?'user':'agent',m.text,m.ts));
}
function addMsg(cls,text,ts){
  const box=document.getElementById('msgs');
  const d=document.createElement('div'); d.className='m '+cls;
  d.textContent=text;
  if(ts){const s=document.createElement('span');s.className='ts';s.textContent=ts.replace('T',' ');d.appendChild(s);}
  box.appendChild(d); box.scrollTop=box.scrollHeight; return d;
}
function kd(e){ if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();} }
async function send(){
  const inp=document.getElementById('inp'), btn=document.getElementById('send');
  const text=inp.value.trim(); if(!text) return;
  const id=document.getElementById('rcpt').value;
  addMsg('user',text); inp.value=''; btn.disabled=true;
  const wait=addMsg('sys','● generating reply...');
  try{
    const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({recipient:id,message:text})});
    const j=await r.json();
    wait.remove(); addMsg('agent',j.reply);
    document.getElementById('dash').contentWindow.location.reload();
  }catch(err){ wait.remove(); addMsg('sys','send failed: '+err); }
  btn.disabled=false; inp.focus();
}
init();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            self._send(200, INDEX, "text/html")
        elif u.path == "/dashboard.html":
            try:
                self._send(200, open(DASHBOARD_HTML, "rb").read(), "text/html")
            except Exception:
                self._send(404, "<h1>dashboard.html missing — run render_dashboard_html.py first</h1>", "text/html")
        elif u.path == "/api/recipients":
            self._send(200, json.dumps(recipients(), ensure_ascii=False))
        elif u.path == "/api/history":
            tid = parse_qs(u.query).get("thread", ["lead"])[0]
            self._send(200, json.dumps(load_history(tid), ensure_ascii=False))
        else:
            self._send(404, "{}")

    def do_POST(self):
        if urlparse(self.path).path != "/api/chat":
            self._send(404, "{}")
            return
        n = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            self._send(400, json.dumps({"reply": "[error] bad request"}))
            return
        rid = req.get("recipient", "lead")
        msg = (req.get("message") or "").strip()
        if not msg:
            self._send(400, json.dumps({"reply": "[error] empty message"}))
            return
        append_history(rid, "user", msg)
        write = is_write_intent(msg)
        if rid == "lead" and not write and is_broadcast(msg):
            reply = broadcast(msg)            # lead + portfolio-wide question -> parallel fan-out
        else:
            reply = call_claude(build_prompt(rid, msg, write), write=write)
        append_history(rid, "agent", reply)
        if write:
            regen_dashboard()                 # regenerate HTML only when there was a write
        self._send(200, json.dumps({"reply": reply, "write": write}, ensure_ascii=False))


def main():
    os.makedirs(SCANS, exist_ok=True)
    os.makedirs(CHAT_DIR, exist_ok=True)
    if not os.path.exists(DASHBOARD_HTML):
        regen_dashboard()
    url = f"http://localhost:{PORT}/"
    print(f"Research dashboard + chat server running: {url}")
    print(f"claude path: {CLAUDE}")
    print("Stop: Ctrl+C")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
