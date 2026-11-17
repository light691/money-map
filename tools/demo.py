#!/usr/bin/env python3
"""Rebuild every README sample from a made-up budget.

Creates a throwaway sample database, runs the real `moneymap` commands a chat agent would run,
and renders: each card, three chat walkthroughs (question -> command -> card) and one overview
image. Every number and reply in the images is real command output.

    python3 tools/demo.py                 # writes docs/screenshots/
    python3 tools/demo.py --out /tmp/x    # somewhere else
"""
import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cards  # noqa: E402

FONT = cards.FONT


def mm(db, *argv):
    r = subprocess.run([sys.executable, os.path.join(HERE, "moneymap.py"), "--db", db, *map(str, argv)],
                       capture_output=True, text=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    if r.returncode:
        raise SystemExit(f"moneymap {' '.join(map(str, argv))} failed:\n{r.stderr}")
    return r.stdout.strip()


def build(db):
    """A believable month for someone paid on the 15th and 30th. Sample data only."""
    steps = [
        ["seed"],
        ["flow-set", "pay-15", "amount=16000", "lowAmount=15000"],
        ["flow-set", "pay-30", "amount=16000", "lowAmount=15000"],
        ["flow-add", "--id", "laptop", "--name", "Laptop installment", "--direction", "expense", "--schedule",
         "monthly", "--amount", "3500", "--day", "30", "--start", "2026-11-01", "--end", "2027-04-30",
         "--category", "Debt", "--confidence", "confirmed"],
        ["balance-add", "--id", "laptop-balance", "--name", "Laptop installment", "--kind", "debt",
         "--amount", "21000", "--as-of", "2026-11-01"],
        ["debt-link", "laptop", "laptop-balance"],
        ["flow-add", "--id", "netflix", "--name", "Netflix", "--direction", "expense", "--schedule", "monthly",
         "--amount", "549", "--day", "30", "--start", "2026-11-01", "--category", "Subscriptions"],
        ["flow-add", "--id", "reg", "--name", "Motorcycle registration", "--direction", "expense", "--schedule",
         "once", "--amount", "9800", "--date", "2026-12-12", "--category", "Transport"],
        ["flow-add", "--id", "xmas", "--name", "Christmas gifts", "--direction", "expense", "--schedule", "once",
         "--amount", "12000", "--date", "2026-12-20", "--category", "Gifts"],
        ["due", "rent", "5"], ["due", "internet", "25"], ["due", "card-pay", "22"],
        ["pay", "--flow", "rent", "--original-date", "2026-11-15", "--amount", "9000", "--paid-on", "2026-11-15"],
        ["pay", "--flow", "electric", "--original-date", "2026-11-15", "--amount", "2380", "--paid-on", "2026-11-16"],
        ["pay", "--flow", "card-pay", "--original-date", "2026-11-15", "--amount", "3000", "--paid-on", "2026-11-16"],
        ["cash", "7820", "--date", "2026-11-16"],
        ["spend", "640", "groceries", "top-up", "--category", "Food", "--date", "2026-11-17"],
        ["spend", "320", "coffee", "with", "friends", "--category", "Fun", "--date", "2026-11-17"],
        ["icon", "auto"],
    ]
    for s in steps:
        mm(db, *s)


def card(db, out, kind, name, on, *extra):
    res = mm(db, "card", kind, "--on", on, "--out", os.path.join(out, f"{name}.png"), *extra)
    return res.splitlines()[0]


def clean_reply(text):
    """What the agent says back: the command's line, minus internal ids."""
    return re.sub(r"\s*\((sp|pay)-[0-9a-f]{8}\)", "", text).strip()


# ---------------------------------------------------------------- chat mock
CHAT_CSS = """
@font-face{font-family:"InterMM";src:url("file://%(font)s") format("woff2");font-weight:100 900}
*{box-sizing:border-box;margin:0}
body{width:%(w)spx;background:#0b0d13;font-family:"InterMM","Noto Sans",sans-serif;color:#e9ebf2;
  -webkit-font-smoothing:antialiased}
.z{padding-bottom:14px;background:#0b0d13}
.bar{display:flex;align-items:center;gap:11px;padding:14px 16px;background:#141824;border-bottom:1px solid #1f2433}
.av{width:38px;height:38px;border-radius:50%%;background:linear-gradient(140deg,#8b5cf6,#3b82f6);display:grid;
  place-items:center;font-weight:800;color:#fff}
.bar b{display:block;font-size:15px} .bar span{font-size:12px;color:#7d86a0}
.scene{font-size:11px;letter-spacing:1.2px;text-transform:uppercase;color:#7d86a0;font-weight:700;
  text-align:center;margin:14px 0 4px}
.day{align-self:center;font-size:11.5px;color:#aab1c6;background:#171b27;border-radius:99px;padding:3px 10px;margin:6px 0}
.log{display:flex;flex-direction:column;gap:7px;padding:8px 12px}
.m{max-width:82%%;border-radius:16px;padding:8px 11px 6px;font-size:13.5px;line-height:1.42;position:relative}
.m small{display:block;text-align:right;font-size:10.5px;color:#8a92aa;margin-top:2px}
.me{align-self:flex-end;background:#3b3285;border-bottom-right-radius:5px}
.me small{color:#b9b2f0}
.bot{align-self:flex-start;background:#171b27;border-bottom-left-radius:5px}
.ph{padding:4px 4px 6px}
.ph img{display:block;width:250px;border-radius:12px}
.ph .cap{padding:6px 7px 0}
.cmd{align-self:flex-start;font:11px ui-monospace,"JetBrains Mono",monospace;color:#8fe3c0;background:#0f1a17;
  border:1px solid #1b3a2f;border-radius:8px;padding:4px 8px;margin:-2px 0 0 4px}
"""


def bubble(m):
    who, kind = m["who"], m.get("kind", "text")
    t = f'<small>{html.escape(m.get("time", ""))}</small>'
    if kind == "cmd":
        return f'<div class="cmd">$ {html.escape(m["text"])}</div>'
    if kind == "day":
        return f'<div class="day">{html.escape(m["text"])}</div>'
    if kind == "photo":
        return (f'<div class="m bot ph"><img src="file://{m["img"]}"><div class="cap">'
                f'{html.escape(m["text"])}{t}</div></div>')
    return f'<div class="m {who}">{html.escape(m["text"])}{t}</div>'


def chat_html(title, msgs, width=430):
    body = "".join(bubble(m) for m in msgs)
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{CHAT_CSS % {"font": FONT, "w": width}}'
            f'</style></head><body><div class="z"><div class="bar"><div class="av">M</div><div><b>Money Map</b>'
            f'<span>bot</span></div></div><div class="scene">{html.escape(title)}</div><div class="log">{body}</div>'
            '</div><script>document.fonts.ready.then(function(){Promise.all(Array.from(document.images).map('
            'function(i){return i.complete?1:new Promise(function(r){i.onload=i.onerror=r})})).then(function(){'
            'document.body.setAttribute("data-h",Math.ceil(document.querySelector(".z").getBoundingClientRect()'
            '.bottom))})})</script></body></html>')


def render_html(doc, png, width):
    """Same two-pass headless Chromium render the cards use, at any width."""
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as fh:
        fh.write(doc)
        src = fh.name
    try:
        url = "file://" + src
        dom = subprocess.run([cards.chromium(), *cards.BASE_FLAGS, f"--window-size={width},300", "--dump-dom", url],
                             capture_output=True, text=True, timeout=60).stdout
        m = re.search(r'data-h="(\d+)"', dom)
        h = int(m.group(1)) if m else 1600
        if os.path.exists(png):
            os.remove(png)
        subprocess.run([cards.chromium(), *cards.BASE_FLAGS, f"--window-size={width},{h}",
                        "--force-device-scale-factor=2", f"--screenshot={png}", url], capture_output=True, timeout=60)
    finally:
        os.remove(src)
    return png


OVERVIEW = """<!doctype html><html><head><meta charset="utf-8"><style>
@font-face{font-family:"InterMM";src:url("file://%(font)s") format("woff2");font-weight:100 900}
*{margin:0;box-sizing:border-box}
body{width:1400px;font-family:"InterMM",sans-serif;color:#f2f2f7;-webkit-font-smoothing:antialiased;
  background:radial-gradient(900px 420px at 10%% 0%%,rgba(139,92,246,.22),transparent 60%%),#07080d}
.z{padding:44px 44px 48px}
h1{font-size:40px;letter-spacing:-1.4px;margin-bottom:8px}
p{font-size:17px;color:#a3a8bd;margin-bottom:30px}
.row{display:grid;grid-template-columns:repeat(3,1fr);gap:28px;align-items:start}
.col h2{font-size:15px;margin-bottom:4px} .col span{display:block;font-size:13px;color:#8d93aa;margin-bottom:12px}
.col img{width:100%%;display:block;border-radius:20px;box-shadow:0 24px 60px -22px rgba(0,0,0,.9),0 0 0 1px rgba(255,255,255,.07)}
</style></head><body><div class="z">
<h1>Ask in chat. Get a card back.</h1>
<p>Plain words in. The agent runs one Money Map command. The reply is a picture made from your own numbers.</p>
<div class="row">%(cols)s</div></div>
<script>document.fonts.ready.then(function(){Promise.all(Array.from(document.images).map(function(i){return i.complete?1:
new Promise(function(r){i.onload=i.onerror=r})})).then(function(){document.body.setAttribute("data-h",
Math.ceil(document.querySelector(".z").getBoundingClientRect().bottom))})})</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.normpath(os.path.join(HERE, "..", "docs", "screenshots")))
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    work = tempfile.mkdtemp(prefix="mm-demo-")
    db = os.path.join(work, "demo.db")
    shots = os.path.join(work, "shots")
    os.makedirs(shots)
    build(db)
    D17, D29 = "2026-11-17", "2026-11-29"

    # 1. check in
    c_period = card(db, shots, "period", "chat-period", D17)
    spend = clean_reply(mm(db, "spend", "185", "jeep", "and", "lunch", "--category", "Transport", "--date", D17))
    chat1 = [
        {"who": "me", "text": "how am I this cutoff?", "time": "12:41"},
        {"who": "bot", "kind": "cmd", "text": "moneymap card period"},
        {"who": "bot", "kind": "photo", "img": os.path.join(shots, "chat-period.png"), "text": c_period, "time": "12:41"},
        {"who": "me", "text": "spent 185 jeep and lunch", "time": "12:58"},
        {"who": "bot", "kind": "cmd", "text": "moneymap spend 185 jeep and lunch --category Transport"},
        {"who": "bot", "text": spend, "time": "12:58"},
    ]
    # 2. plan ahead
    c_whatif = card(db, shots, "whatif", "chat-whatif", D17, "--amount", "2500", "--label", "Running shoes")
    c_runway = card(db, shots, "timeline", "chat-runway", D17)
    chat2 = [
        {"who": "me", "text": "kaya ko ba bumili ng ₱2,500 na running shoes?", "time": "19:05"},
        {"who": "bot", "kind": "cmd", "text": "moneymap card whatif --amount 2500 --label \"Running shoes\""},
        {"who": "bot", "kind": "photo", "img": os.path.join(shots, "chat-whatif.png"), "text": c_whatif, "time": "19:05"},
        {"who": "me", "text": "when do I run out?", "time": "19:06"},
        {"who": "bot", "kind": "cmd", "text": "moneymap card timeline"},
        {"who": "bot", "kind": "photo", "img": os.path.join(shots, "chat-runway.png"), "text": c_runway, "time": "19:06"},
    ]
    # gallery cards, same state as the chats above
    gallery = {"period": ("period", []), "runway": ("timeline", []), "bills": ("bills", ["--days", "14"]),
               "whatif": ("whatif", ["--amount", "2500", "--label", "Running shoes"])}
    for name, (kind, extra) in gallery.items():
        card(db, out, kind, name, D17, *extra)
    samples = [f"$ moneymap period --on {D17}", mm(db, "period", "--on", D17),
               f"$ moneymap timeline --periods 4 --on {D17}", mm(db, "timeline", "--periods", "4", "--on", D17)]
    # 3. stay on top: the 8:00 brief, then a payment
    brief = mm(db, "brief", "--on", D29).splitlines()
    brief_png = brief[-1].split("MEDIA:", 1)[1]
    shutil.copy(brief_png, os.path.join(shots, "chat-brief.png"))
    pay = clean_reply(mm(db, "pay", "--flow", "laptop", "--original-date", "2026-11-30", "--amount", "3500",
                         "--paid-on", D29))
    c_receipt = card(db, shots, "receipt", "chat-receipt", D29)
    chat3 = [
        {"who": "bot", "kind": "day", "text": "Sun, Nov 29 · 8:00 scheduled brief"},
        {"who": "bot", "kind": "cmd", "text": "moneymap brief"},
        {"who": "bot", "text": brief[0], "time": "08:00"},
        {"who": "bot", "kind": "photo", "img": os.path.join(shots, "chat-brief.png"), "text": brief[1], "time": "08:00"},
        {"who": "me", "text": "paid laptop 3,500", "time": "09:12"},
        {"who": "bot", "kind": "cmd", "text": "moneymap pay --flow laptop --original-date 2026-11-30 --amount 3500"},
        {"who": "bot", "kind": "photo", "img": os.path.join(shots, "chat-receipt.png"), "text": c_receipt, "time": "09:12"},
    ]
    for name, kind, extra, on in (("debts", "debts", [], D29), ("receipt", "receipt", [], D29), ("icons", "icons", [], D17)):
        card(db, out, kind, name, on, *extra)

    titles = [("chat-1-check-in", "Check in", "What's left this cutoff, and logging a spend.", chat1),
              ("chat-2-plan-ahead", "Plan ahead", "Can I afford it? When does cash run out?", chat2),
              ("chat-3-stay-on-top", "Stay on top", "A morning brief, then a payment and its receipt.", chat3)]
    cols = ""
    for fname, title, sub, msgs in titles:
        png = render_html(chat_html(title, msgs), os.path.join(out, f"{fname}.png"), 430)
        cols += f'<div class="col"><h2>{html.escape(title)}</h2><span>{html.escape(sub)}</span><img src="file://{png}"></div>'
    render_html(OVERVIEW % {"font": FONT, "cols": cols}, os.path.join(out, "how-it-works.png"), 1400)

    print("=== sample CLI output (for the README)")
    print("\n".join(samples))
    shutil.rmtree(work, ignore_errors=True)
    print("wrote", ", ".join(sorted(os.listdir(out))))


if __name__ == "__main__":
    main()
