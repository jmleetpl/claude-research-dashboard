#!/usr/bin/env python3
"""Read scan cards (_workspace/scans/*.json) and render a self-contained visual HTML dashboard.

No external CDN / internet dependency — charts are pure CSS/SVG. Double-click to open in a browser.
Usage: python render_dashboard_html.py [--scans <scans_dir>] [--out <dashboard.html>] [--date YYYY-MM-DD]

Defaults resolve from $RESEARCH_DASHBOARD_DIR (default ~/research-dashboard).
"""
import json
import glob
import os
import argparse
import html
from datetime import datetime, date

STATUS_META = {
    "active":  ("Active",   "#16a34a", "#dcfce7"),
    "idle":    ("Idle",     "#d97706", "#fef3c7"),
    "stalled": ("Stalled",  "#dc2626", "#fee2e2"),
    "done":    ("Done",     "#2563eb", "#dbeafe"),
    "unknown": ("Unknown",  "#6b7280", "#f3f4f6"),
}
TYPE_ORDER = ["paper", "data analysis", "tool development", "infra/meta", "admin/docs", "other"]
INFRA_TYPES = ("infra/meta", "인프라/메타")
STATUS_ORDER = ["active", "idle", "stalled", "done", "unknown"]


def base_dir():
    return os.environ.get("RESEARCH_DASHBOARD_DIR") or os.path.join(
        os.path.expanduser("~"), "research-dashboard"
    )


def esc(s):
    return html.escape(str(s if s is not None else ""))


def load_cards(scans_dir):
    cards = []
    for f in sorted(glob.glob(os.path.join(scans_dir, "*.json"))):
        try:
            c = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        c.setdefault("status", "unknown")
        if c.get("status") not in STATUS_META:
            c["status"] = "unknown"
        cards.append(c)
    return cards


def days_ago(d):
    if not d:
        return None
    try:
        dt = datetime.fromisoformat(str(d)[:10]).date()
        return (date.today() - dt).days
    except Exception:
        return None


def bar_row(label, count, total, color):
    pct = (count / total * 100) if total else 0
    return f"""<div class="bar-row">
      <span class="bar-label">{esc(label)}</span>
      <div class="bar-track"><div class="bar-fill" style="width:{pct:.1f}%;background:{color}"></div></div>
      <span class="bar-count">{count}</span>
    </div>"""


def card_html(c):
    st = c.get("status", "unknown")
    label, fg, bg = STATUS_META[st]
    da = days_ago(c.get("last_active"))
    da_txt = f"{da}d ago" if da is not None else "—"
    nexts = c.get("next_actions") or []
    next_items = "".join(f"<li>{esc(n)}</li>" for n in nexts[:3]) or "<li class='muted'>—</li>"
    conf = c.get("confidence", "")
    conf_badge = f"<span class='conf conf-{esc(conf)}'>confidence {esc(conf)}</span>" if conf else ""
    rel = c.get("related_projects") or []
    rel_txt = f"<div class='rel'>🔗 related: {esc(', '.join(rel))}</div>" if rel else ""
    return f"""<article class="card" data-status="{esc(st)}" data-type="{esc(c.get('type',''))}">
      <div class="card-top">
        <span class="status-badge" style="color:{fg};background:{bg}">{label}</span>
        <span class="type-tag">{esc(c.get('type',''))}</span>
      </div>
      <h3>{esc(c.get('title') or c.get('project_id'))}</h3>
      <div class="meta">
        <span>📍 {esc(c.get('current_stage',''))}</span>
        <span>🕒 {da_txt} <span class="muted">({esc(c.get('last_active',''))})</span></span>
        <span>💬 {esc(c.get('n_sessions',0))} sessions</span>
        {conf_badge}
      </div>
      <p class="goal">{esc(c.get('goal',''))}</p>
      <div class="next"><b>Next actions</b><ul>{next_items}</ul></div>
      {rel_txt}
    </article>"""


def render(cards, generated):
    research = [c for c in cards if c.get("type") not in INFRA_TYPES]
    total = len(cards)
    status_counts = {s: sum(1 for c in cards if c.get("status") == s) for s in STATUS_ORDER}
    type_counts = {}
    for c in cards:
        type_counts[c.get("type", "other")] = type_counts.get(c.get("type", "other"), 0) + 1
    stage_counts = {}
    for c in cards:
        stg = c.get("current_stage", "unknown")
        stage_counts[stg] = stage_counts.get(stg, 0) + 1

    # needs attention: idle/stalled research, or submission/revision stage
    attention = [c for c in research if c.get("status") in ("idle", "stalled")
                 or c.get("current_stage") in ("submission/revision", "투고/리비전")]
    attention.sort(key=lambda c: (c.get("status") != "stalled", c.get("status") != "idle",
                                  -(days_ago(c.get("last_active")) or 0)))

    cards_sorted = sorted(cards, key=lambda c: (STATUS_ORDER.index(c.get("status", "unknown")),
                                                days_ago(c.get("last_active")) if days_ago(c.get("last_active")) is not None else 9999))

    chips = "".join(
        f"<div class='chip' style='--c:{STATUS_META[s][1]}'><span class='chip-n'>{status_counts[s]}</span>"
        f"<span class='chip-l'>{STATUS_META[s][0]}</span></div>"
        for s in STATUS_ORDER if status_counts[s] > 0
    )
    status_bars = "".join(bar_row(STATUS_META[s][0], status_counts[s], total, STATUS_META[s][1])
                          for s in STATUS_ORDER if status_counts[s] > 0)
    stage_bars = "".join(bar_row(k, v, total, "#6366f1")
                         for k, v in sorted(stage_counts.items(), key=lambda kv: -kv[1]))
    type_bars = "".join(bar_row(k, type_counts.get(k, 0), total, "#0ea5e9")
                        for k in TYPE_ORDER if type_counts.get(k))

    attention_html = "".join(
        f"<li><span class='dot dot-{esc(c.get('status'))}'></span>"
        f"<b>{esc(c.get('title'))}</b> "
        f"<span class='muted'>({esc(c.get('current_stage'))} · {esc(c.get('last_active'))})</span>"
        f"<div class='att-next'>→ {esc((c.get('next_actions') or ['—'])[0])}</div></li>"
        for c in attention[:6]
    ) or "<li class='muted'>Nothing needs attention</li>"

    cards_html = "".join(card_html(c) for c in cards_sorted)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Research Dashboard</title>
<style>
  :root {{ --bg:#0f172a; --panel:#fff; --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:"Segoe UI",system-ui,-apple-system,"Noto Sans CJK KR","Malgun Gothic",sans-serif;
         background:#f1f5f9; color:var(--ink); line-height:1.5; }}
  header {{ background:linear-gradient(135deg,#1e293b,#334155); color:#fff; padding:28px 32px; }}
  header h1 {{ margin:0 0 4px; font-size:24px; }}
  header .sub {{ color:#cbd5e1; font-size:14px; }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:24px 32px 60px; }}
  .chips {{ display:flex; gap:14px; flex-wrap:wrap; margin:20px 0 8px; }}
  .chip {{ background:var(--panel); border-radius:14px; padding:16px 22px; min-width:96px;
          box-shadow:0 1px 3px rgba(0,0,0,.08); border-left:5px solid var(--c); }}
  .chip-n {{ display:block; font-size:30px; font-weight:700; color:var(--c); line-height:1; }}
  .chip-l {{ display:block; font-size:13px; color:var(--muted); margin-top:4px; }}
  .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; margin:24px 0; }}
  @media(max-width:820px){{ .grid2 {{ grid-template-columns:1fr; }} }}
  .panel {{ background:var(--panel); border-radius:14px; padding:20px 22px;
           box-shadow:0 1px 3px rgba(0,0,0,.06); }}
  .panel h2 {{ margin:0 0 14px; font-size:15px; color:#334155; }}
  .bar-row {{ display:flex; align-items:center; gap:10px; margin:7px 0; font-size:13px; }}
  .bar-label {{ width:120px; color:#475569; flex-shrink:0; }}
  .bar-track {{ flex:1; background:#f1f5f9; border-radius:6px; height:18px; overflow:hidden; }}
  .bar-fill {{ height:100%; border-radius:6px; transition:width .4s; }}
  .bar-count {{ width:26px; text-align:right; font-weight:600; color:#334155; }}
  .attention li {{ list-style:none; margin:0 0 12px; padding-left:4px; }}
  .attention ul {{ padding:0; margin:0; }}
  .att-next {{ font-size:13px; color:#475569; margin-top:2px; }}
  .dot {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:7px; }}
  .dot-idle{{background:#d97706}} .dot-stalled{{background:#dc2626}}
  .dot-active{{background:#16a34a}} .dot-done{{background:#2563eb}}
  .filters {{ display:flex; gap:8px; flex-wrap:wrap; margin:28px 0 16px; }}
  .filters button {{ border:1px solid var(--line); background:#fff; padding:7px 16px;
                    border-radius:20px; cursor:pointer; font-size:13px; color:#475569; }}
  .filters button.on {{ background:#1e293b; color:#fff; border-color:#1e293b; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(330px,1fr)); gap:18px; }}
  .card {{ background:var(--panel); border-radius:14px; padding:18px 20px;
          box-shadow:0 1px 3px rgba(0,0,0,.07); display:flex; flex-direction:column; gap:8px; }}
  .card-top {{ display:flex; justify-content:space-between; align-items:center; }}
  .status-badge {{ font-size:12px; font-weight:700; padding:3px 11px; border-radius:20px; }}
  .type-tag {{ font-size:12px; color:var(--muted); }}
  .card h3 {{ margin:2px 0; font-size:16px; }}
  .meta {{ display:flex; flex-wrap:wrap; gap:10px; font-size:12px; color:#475569; }}
  .goal {{ font-size:13px; color:#334155; margin:4px 0; }}
  .next {{ font-size:13px; }}
  .next b {{ font-size:12px; color:#64748b; }}
  .next ul {{ margin:4px 0 0; padding-left:18px; }}
  .next li {{ margin:2px 0; }}
  .rel {{ font-size:12px; color:#0369a1; }}
  .muted {{ color:#94a3b8; }}
  .conf {{ font-size:11px; padding:1px 7px; border-radius:10px; background:#f1f5f9; color:#64748b; }}
  .conf-high{{background:#dcfce7;color:#166534}} .conf-low{{background:#fee2e2;color:#991b1b}}
  footer {{ text-align:center; color:#94a3b8; font-size:12px; margin-top:40px; }}
</style>
</head>
<body>
<header>
  <h1>🧪 Research Dashboard</h1>
  <div class="sub">{total} total · {len(research)} research (papers/analysis) · generated {esc(generated)}</div>
</header>
<div class="wrap">
  <div class="chips">{chips}</div>

  <div class="grid2">
    <div class="panel"><h2>Status distribution</h2>{status_bars}</div>
    <div class="panel"><h2>Stage distribution</h2>{stage_bars}</div>
  </div>
  <div class="grid2">
    <div class="panel"><h2>Type distribution</h2>{type_bars}</div>
    <div class="panel attention"><h2>🔥 Needs attention (agenda)</h2><ul>{attention_html}</ul></div>
  </div>

  <div class="filters">
    <button class="on" onclick="flt(this,'all')">All</button>
    <button onclick="flt(this,'active')">Active</button>
    <button onclick="flt(this,'idle')">Idle</button>
    <button onclick="flt(this,'stalled')">Stalled</button>
    <button onclick="flt(this,'done')">Done</button>
  </div>
  <div class="cards">{cards_html}</div>

  <footer>research-dashboard · auto-refreshed weekly · this file is dashboard.html (Markdown source: DASHBOARD.md)</footer>
</div>
<script>
function flt(btn, s) {{
  document.querySelectorAll('.filters button').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on');
  document.querySelectorAll('.card').forEach(c=>{{
    c.style.display = (s==='all'||c.dataset.status===s) ? '' : 'none';
  }});
}}
</script>
</body>
</html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scans", default=os.path.join(base_dir(), "_workspace", "scans"))
    ap.add_argument("--out", default=os.path.join(base_dir(), "dashboard.html"))
    ap.add_argument("--date", default=None, help="generation date (YYYY-MM-DD), today if omitted")
    args = ap.parse_args()
    os.makedirs(args.scans, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    cards = load_cards(args.scans)
    generated = args.date or date.today().isoformat()
    htmlout = render(cards, generated)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(htmlout)
    print(f"OK: {args.out} ({len(cards)} cards)")


if __name__ == "__main__":
    main()
