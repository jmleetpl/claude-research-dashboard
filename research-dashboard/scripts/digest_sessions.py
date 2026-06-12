#!/usr/bin/env python3
"""Convert Claude Code session logs (.jsonl) into compact per-project digests (JSON).

Raw logs can be tens of MB, so agents must not read them directly.
This script deterministically extracts:
- Session metadata: cwd, git branch, start/end time, size
- summary lines (the session summary Claude Code records)
- User messages (first 3 + last 3, truncated to 300 chars)
- Last assistant text (truncated to 500 chars)
- File paths created/edited via Write/Edit, and the list of skills used

Usage:
  python digest_sessions.py [--out <output_dir>] [--projects-dir <log_root>] [--only <dir_name>...]

If --out is omitted, digests are written under
  $RESEARCH_DASHBOARD_DIR/_workspace/digests  (default ~/research-dashboard/_workspace/digests).
"""
import json
import os
import re
import argparse
from pathlib import Path
from datetime import datetime

MAX_TEXT = 300


def base_dir():
    return os.environ.get("RESEARCH_DASHBOARD_DIR") or os.path.join(
        os.path.expanduser("~"), "research-dashboard"
    )


def extract_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts)
    return ""


def is_noise(text):
    t = text.strip()
    if not t:
        return True
    return t.startswith(("<command-", "<local-command", "<system-reminder", "Caveat:"))


def truncate(t, n=MAX_TEXT):
    t = re.sub(r"\s+", " ", t).strip()
    return t[:n] + ("…" if len(t) > n else "")


def digest_session(path):
    info = {
        "session_file": path.name,
        "mtime": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        "size_kb": round(path.stat().st_size / 1024, 1),
    }
    cwd = branch = None
    first_ts = last_ts = None
    summaries = []
    user_msgs = []
    last_assistant = None
    files_touched = set()
    skills_used = set()
    n_lines = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            n_lines += 1
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            t = obj.get("type")
            if cwd is None and obj.get("cwd"):
                cwd = obj["cwd"]
            if obj.get("gitBranch"):
                branch = obj["gitBranch"]
            ts = obj.get("timestamp")
            if ts:
                first_ts = first_ts or ts
                last_ts = ts
            if t == "summary":
                s = obj.get("summary")
                if s and s not in summaries:
                    summaries.append(s)
            elif t == "user" and not obj.get("isMeta"):
                msg = obj.get("message", {})
                content = msg.get("content")
                # user lines that just carry a tool_result are not real user utterances
                if isinstance(content, list) and any(
                    isinstance(b, dict) and b.get("type") == "tool_result" for b in content
                ):
                    continue
                text = extract_text(content)
                if not is_noise(text):
                    user_msgs.append(truncate(text))
            elif t == "assistant":
                msg = obj.get("message", {})
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text" and block.get("text", "").strip():
                        last_assistant = truncate(block["text"], 500)
                    elif block.get("type") == "tool_use":
                        name = block.get("name", "")
                        inp = block.get("input") or {}
                        if name in ("Write", "Edit", "NotebookEdit") and inp.get("file_path"):
                            files_touched.add(inp["file_path"])
                        elif name == "Skill" and inp.get("skill"):
                            skills_used.add(inp["skill"])
    info.update({
        "cwd": cwd,
        "git_branch": branch,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "lines": n_lines,
        "summaries": summaries[:10],
        "first_user_messages": user_msgs[:3],
        "last_user_messages": user_msgs[-3:] if len(user_msgs) > 6 else user_msgs[3:],
        "last_assistant_text": last_assistant,
        "files_written": sorted(files_touched)[:25],
        "n_files_written": len(files_touched),
        "skills_used": sorted(skills_used),
        "n_user_messages": len(user_msgs),
    })
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--projects-dir", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--out", default=os.path.join(base_dir(), "_workspace", "digests"))
    ap.add_argument("--only", nargs="*", help="process only these directory names")
    args = ap.parse_args()

    projects_dir = Path(args.projects_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not projects_dir.is_dir():
        print(f"[error] session log root not found: {projects_dir}")
        (out_dir / "_index.json").write_text("[]", encoding="utf-8")
        return
    index = []
    for proj in sorted(projects_dir.iterdir()):
        if not proj.is_dir():
            continue
        if args.only and proj.name not in args.only:
            continue
        # agent-*.jsonl are sub-agent transcripts; collect main sessions only
        sessions = sorted(
            (p for p in proj.glob("*.jsonl") if not p.name.startswith("agent-")),
            key=lambda p: p.stat().st_mtime,
        )
        if not sessions:
            index.append({"project_id": proj.name, "working_dir": None,
                          "n_sessions": 0, "last_active": None, "digest_file": None})
            continue
        digest = {
            "project_id": proj.name,
            "n_sessions": len(sessions),
            "sessions": [digest_session(s) for s in sessions],
        }
        cwds = [s.get("cwd") for s in digest["sessions"] if s.get("cwd")]
        digest["working_dir"] = max(set(cwds), key=cwds.count) if cwds else None
        digest["last_active"] = max((s["mtime"] for s in digest["sessions"]), default=None)
        out_file = out_dir / f"{proj.name}.json"
        out_file.write_text(json.dumps(digest, ensure_ascii=False, indent=1), encoding="utf-8")
        index.append({
            "project_id": proj.name,
            "working_dir": digest["working_dir"],
            "n_sessions": len(sessions),
            "last_active": digest["last_active"],
            "digest_file": str(out_file),
        })
    (out_dir / "_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(index, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
