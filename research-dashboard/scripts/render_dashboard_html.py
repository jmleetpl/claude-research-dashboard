#!/usr/bin/env python3
"""Read scan cards (_workspace/scans/*.json) and render a self-contained visual HTML dashboard.

No external CDN / internet dependency — charts are pure CSS/SVG. Double-click to open in a browser.
The interface has a Korean/English (한/영) toggle: it switches all UI labels. Per-project text
(goal, next actions) stays in whatever language the scanner wrote it.
Usage: python render_dashboard_html.py [--scans <scans_dir>] [--out <dashboard.html>] [--date YYYY-MM-DD]

Defaults resolve from $RESEARCH_DASHBOARD_DIR (default ~/research-dashboard).
"""
import json
import glob
import os
import argparse
import html
from datetime import datetime, date

# status key -> (English label, Korean label, foreground, background)
STATUS_META = {
    "active":  ("Active",  "활성", "#16a34a", "#dcfce7"),
    "idle":    ("Idle",    "유휴", "#d97706", "#fef3c7"),
    "stalled": ("Stalled", "정체", "#dc2626", "#fee2e2"),
    "done":    ("Done",    "완료", "#2563eb", "#dbeafe"),
    "unknown": ("Unknown", "미상", "#6b7280", "#f3f4f6"),
}
TYPE_ORDER = ["paper", "data analysis", "tool development", "infra/meta", "admin/docs", "other"]
INFRA_TYPES = ("infra/meta", "인프라/메타")
STATUS_ORDER = ["active", "idle", "stalled", "done", "unknown"]

# English <-> Korean maps for free-text stage / type values coming from the cards.
STAGE_KO = {
    "tool development": "도구 개발", "submission/revision": "투고/리비전",
    "drafting": "초안 작성", "writing": "집필", "protocol/approval": "프로토콜/승인",
    "data collection": "데이터 수집", "data analysis": "데이터 분석",
    "analysis": "분석", "planning": "기획", "idea": "아이디어", "unknown": "미상",
}
STAGE_EN = {v: k for k, v in STAGE_KO.items()}
TYPE_KO = {
    "paper": "논문", "data analysis": "데이터 분석", "tool development": "도구 개발",
    "infra/meta": "인프라/메타", "admin/docs": "행정/문서", "other": "기타",
}
TYPE_EN = {v: k for k, v in TYPE_KO.items()}


def base_dir():
    return os.environ.get("RESEARCH_DASHBOARD_DIR") or os.path.join(
        os.path.expanduser("~"), "research-dashboard"
    )


def esc(s):
    return html.escape(str(s if s is not None else ""))


def t(en, ko):
    """Render a translatable label: shows English by default, swapped to Korean by the toggle."""
    en_s, ko_s = esc(en), esc(ko)
    return f'<span class="i18n" data-en="{en_s}" data-ko="{ko_s}">{en_s}</span>'


def tr(value, ko_map, en_map):
    """Translate a free-text value (stage/type) that may already be English or Korean."""
    if value is None or value == "":
        return t("", "")
    v = str(value)
    if v in ko_map:        # value is English -> we know its Korean
        return t(v, ko_map[v])
    if v in en_map:        # value is Korean -> we know its English
        return t(en_map[v], v)
    return t(v, v)         # unknown free text: same in both languages


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


def bar_row(label_html, count, total, color):
    pct = (count / total * 100) if total else 0
    return f"""<div class="bar-row">
      <span class="bar-label">{label_html}</span>
      <div class="bar-track"><div class="bar-fill" style="width:{pct:.1f}%;background:{color}"></div></div>
      <span class="bar-count">{count}</span>
    </div>"""


def card_html(c):
    st = c.get("status", "unknown")
    label_en, label_ko, fg, bg = STATUS_META[st]
    da = days_ago(c.get("last_active"))
    da_txt = f"{da}{t('d ago', '일 전')}" if da is not None else "—"
    nexts = c.get("next_actions") or []
    next_items = "".join(f"<li>{esc(n)}</li>" for n in nexts[:3]) or "<li class='muted'>—</li>"
    conf = c.get("confidence", "")
    conf_badge = f"<span class='conf conf-{esc(conf)}'>{t('confidence', '신뢰도')} {esc(conf)}</span>" if conf else ""
    rel = c.get("related_projects") or []
    rel_txt = f"<div class='rel'>🔗 {t('related', '관련')}: {esc(', '.join(rel))}</div>" if rel else ""
    return f"""<article class="card" data-status="{esc(st)}" data-type="{esc(c.get('type',''))}">
      <div class="card-top">
        <span class="status-badge" style="color:{fg};background:{bg}">{t(label_en, label_ko)}</span>
        <span class="type-tag">{tr(c.get('type',''), TYPE_KO, TYPE_EN)}</span>
      </div>
      <h3>{esc(c.get('title') or c.get('project_id'))}</h3>
      <div class="meta">
        <span>📍 {tr(c.get('current_stage',''), STAGE_KO, STAGE_EN)}</span>
        <span>🕒 {da_txt} <span class="muted">({esc(c.get('last_active',''))})</span></span>
        <span>💬 {esc(c.get('n_sessions',0))} {t('sessions', '세션')}</span>
        {conf_badge}
      </div>
      <p class="goal">{esc(c.get('goal',''))}</p>
      <div class="next"><b>{t('Next actions', '다음 할 일')}</b><ul>{next_items}</ul></div>
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
        f"<div class='chip' style='--c:{STATUS_META[s][2]}'><span class='chip-n'>{status_counts[s]}</span>"
        f"<span class='chip-l'>{t(STATUS_META[s][0], STATUS_META[s][1])}</span></div>"
        for s in STATUS_ORDER if status_counts[s] > 0
    )
    status_bars = "".join(bar_row(t(STATUS_META[s][0], STATUS_META[s][1]), status_counts[s], total, STATUS_META[s][2])
                          for s in STATUS_ORDER if status_counts[s] > 0)
    stage_bars = "".join(bar_row(tr(k, STAGE_KO, STAGE_EN), v, total, "#6366f1")
                         for k, v in sorted(stage_counts.items(), key=lambda kv: -kv[1]))
    type_bars = "".join(bar_row(tr(k, TYPE_KO, TYPE_EN), type_counts.get(k, 0), total, "#0ea5e9")
                        for k in TYPE_ORDER if type_counts.get(k))

    attention_html = "".join(
        f"<li><span class='dot dot-{esc(c.get('status'))}'></span>"
        f"<b>{esc(c.get('title'))}</b> "
        f"<span class='muted'>({tr(c.get('current_stage'), STAGE_KO, STAGE_EN)} · {esc(c.get('last_active'))})</span>"
        f"<div class='att-next'>→ {esc((c.get('next_actions') or ['—'])[0])}</div></li>"
        for c in attention[:6]
    ) or f"<li class='muted'>{t('Nothing needs attention', '주의가 필요한 항목 없음')}</li>"

    cards_html = "".join(card_html(c) for c in cards_sorted)

    sub_en = f"{total} total · {len(research)} research (papers/analysis) · generated {esc(generated)}"
    sub_ko = f"전체 {total}개 · 연구 {len(research)}개(논문/분석) · {esc(generated)} 생성"
    foot_en = "research-dashboard · auto-refreshed weekly · this file is dashboard.html (Markdown source: DASHBOARD.md)"
    foot_ko = "research-dashboard · 매주 자동 갱신 · 이 파일은 dashboard.html (Markdown 원본: DASHBOARD.md)"

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
  header {{ background:linear-gradient(135deg,#1e293b,#334155); color:#fff; padding:28px 32px;
           display:flex; justify-content:space-between; align-items:flex-start; gap:16px; }}
  header h1 {{ margin:0 0 4px; font-size:24px; }}
  header .sub {{ color:#cbd5e1; font-size:14px; }}
  .lang-btn {{ flex-shrink:0; background:rgba(255,255,255,.12); color:#fff; border:1px solid rgba(255,255,255,.35);
              padding:7px 16px; border-radius:20px; cursor:pointer; font-size:13px; font-weight:600; }}
  .lang-btn:hover {{ background:rgba(255,255,255,.22); }}
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
  <div>
    <h1>🧪 {t('Research Dashboard', '연구 대시보드')}</h1>
    <div class="sub i18n" data-en="{esc(sub_en)}" data-ko="{esc(sub_ko)}">{sub_en}</div>
  </div>
  <button id="langtoggle" class="lang-btn" onclick="toggleLang()">한국어</button>
</header>
<div class="wrap">
  <div class="chips">{chips}</div>

  <div class="grid2">
    <div class="panel"><h2>{t('Status distribution', '상태 분포')}</h2>{status_bars}</div>
    <div class="panel"><h2>{t('Stage distribution', '단계 분포')}</h2>{stage_bars}</div>
  </div>
  <div class="grid2">
    <div class="panel"><h2>{t('Type distribution', '유형 분포')}</h2>{type_bars}</div>
    <div class="panel attention"><h2>🔥 {t('Needs attention (agenda)', '주의 필요 (안건)')}</h2><ul>{attention_html}</ul></div>
  </div>

  <div class="filters">
    <button class="on" onclick="flt(this,'all')">{t('All', '전체')}</button>
    <button onclick="flt(this,'active')">{t('Active', '활성')}</button>
    <button onclick="flt(this,'idle')">{t('Idle', '유휴')}</button>
    <button onclick="flt(this,'stalled')">{t('Stalled', '정체')}</button>
    <button onclick="flt(this,'done')">{t('Done', '완료')}</button>
  </div>
  <div class="cards">{cards_html}</div>

  <footer class="i18n" data-en="{esc(foot_en)}" data-ko="{esc(foot_ko)}">{foot_en}</footer>
</div>
<script>
function flt(btn, s) {{
  document.querySelectorAll('.filters button').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on');
  document.querySelectorAll('.card').forEach(c=>{{
    c.style.display = (s==='all'||c.dataset.status===s) ? '' : 'none';
  }});
}}
function setLang(lang) {{
  if (lang !== 'ko') lang = 'en';
  document.documentElement.lang = lang;
  document.querySelectorAll('.i18n').forEach(function(el){{
    var v = el.getAttribute('data-' + lang);
    if (v !== null) el.textContent = v;
  }});
  document.title = (lang === 'ko') ? '연구 대시보드' : 'Research Dashboard';
  var btn = document.getElementById('langtoggle');
  if (btn) btn.textContent = (lang === 'ko') ? 'EN' : '한국어';
  try {{ localStorage.setItem('rd_lang', lang); }} catch (e) {{}}
}}
function toggleLang() {{
  setLang(document.documentElement.lang === 'ko' ? 'en' : 'ko');
}}
(function(){{
  var saved = null;
  try {{ saved = localStorage.getItem('rd_lang'); }} catch (e) {{}}
  if (!saved) {{
    var nav = (navigator.language || '').toLowerCase();
    saved = nav.indexOf('ko') === 0 ? 'ko' : 'en';
  }}
  setLang(saved);
}})();
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
