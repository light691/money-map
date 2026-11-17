"""Money Map summary cards: engine data -> HTML template -> PNG (headless Chromium).

Every number on a card comes from moneymap's period engine; nothing is typed by the agent.
`moneymap card <type>` prints a one-line caption and `MEDIA:<png>` for Hermes to send.
"""
import html
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date, timedelta

import icons
import moneymap as mm

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.normpath(os.path.join(HERE, "..", "dist", "assets", "inter.woff2"))
WIDTH = 430          # CSS px (phone width); rendered at 2x
SCALE = 2

_LOOKS = {}


def looks(st):
    """Icon + colour table for this state (computed once per state object)."""
    k = id(st)
    if k not in _LOOKS:
        _LOOKS.clear()
        _LOOKS[k] = icons.assign(st)
    return _LOOKS[k]


def plural(n, word, many=None):
    return f"{n} {word if n == 1 else (many or word + 's')}"


def esc(s):
    return html.escape(str(s if s is not None else ""))


def peso(v, dec=True, sign=False):
    if v is None:
        return "—"
    s = f"{abs(v):,.2f}" if dec else f"{abs(v):,.0f}"
    pre = "−" if v < 0 else ("+" if sign and v > 0 else "")
    return f"{pre}₱{s}"


def short_date(iso):
    dt = mm.d(iso)
    return f"{mm.MONTHS[dt.month]} {dt.day}"


def clean_name(n):
    n = re.sub(r"\s*placeholder$", "", n, flags=re.I)
    return n


# ---------------------------------------------------------------- base styles
CSS = """
@font-face{font-family:"InterMM";src:url("file://%(font)s") format("woff2");font-weight:100 900}
:root{--bg:#08080c;--card:#101017;--card2:#15151e;--line:#22222e;--line2:#2c2c3a;
  --ink:#f5f5f8;--mute:#9a9aae;--dim:#62627a;--violet:#8b5cf6;--blue:#3b82f6;--pink:#f472b6;
  --amber:#fbbf24;--cyan:#22d3ee;--green:#4ade80;--red:#f87171}
*{box-sizing:border-box;margin:0;padding:0}
html{background:var(--bg)}
body{width:%(w)spx;background:var(--bg);color:var(--ink);padding:0 0 22px;
  font-family:"InterMM","Noto Sans",sans-serif;font-feature-settings:"tnum" 1,"cv11" 1;
  -webkit-font-smoothing:antialiased;position:relative;overflow:hidden}
.glow{position:absolute;top:-130px;left:-70px;width:520px;height:420px;pointer-events:none;
  background:radial-gradient(circle at 40%% 40%%,rgba(139,92,246,.28),transparent 62%%);filter:blur(18px)}
.glow.red{background:radial-gradient(circle at 40%% 40%%,rgba(248,113,113,.22),transparent 62%%)}
.glow.green{background:radial-gradient(circle at 40%% 40%%,rgba(74,222,128,.18),transparent 62%%)}
.z{position:relative;z-index:1}
.top{display:flex;align-items:center;justify-content:space-between;padding:18px 20px 0}
.brand{display:flex;align-items:center;gap:8px}
.mark{width:24px;height:24px;border-radius:8px;background:linear-gradient(140deg,var(--violet),var(--blue));
  display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;color:#fff}
.brand span{font-size:12.5px;font-weight:600;color:var(--mute);letter-spacing:.2px}
.when{font-size:11px;color:var(--dim);font-weight:600}
h1{font-size:28px;font-weight:750;letter-spacing:-1px;line-height:1.1;padding:14px 20px 0}
.sub{font-size:12.5px;color:var(--mute);margin-top:5px;padding:0 20px}
.warn{margin:12px 20px 0;display:flex;gap:8px;align-items:center;font-size:11.5px;color:#fcd34d;
  background:rgba(251,191,36,.08);border:1px solid rgba(251,191,36,.25);border-radius:11px;padding:8px 11px}
.hero{margin:14px 20px 0;border-radius:22px;padding:18px 20px 18px;
  background:linear-gradient(155deg,#1d1a33 0%%,#131320 55%%,#0f0f18 100%%);border:1px solid rgba(139,92,246,.28);
  box-shadow:0 1px 0 rgba(255,255,255,.05) inset,0 18px 40px -18px rgba(88,60,200,.55)}
.hero.bad{background:linear-gradient(155deg,#33191d 0%%,#1c1216 55%%,#120e10 100%%);border-color:rgba(248,113,113,.35);
  box-shadow:0 1px 0 rgba(255,255,255,.05) inset,0 18px 40px -18px rgba(200,60,60,.5)}
.hero.good{background:linear-gradient(155deg,#132a20 0%%,#111a16 55%%,#0e1210 100%%);border-color:rgba(74,222,128,.3)}
.hero .k{font-size:11px;letter-spacing:1.1px;text-transform:uppercase;color:var(--mute);font-weight:650;
  display:flex;justify-content:space-between;align-items:center}
.pill{font-size:10px;font-weight:700;letter-spacing:.6px;border-radius:99px;padding:3px 8px;text-transform:uppercase}
.pill.red{color:#fecaca;background:rgba(248,113,113,.18)} .pill.green{color:#bbf7d0;background:rgba(74,222,128,.16)}
.pill.amber{color:#fde68a;background:rgba(251,191,36,.16)} .pill.mute{color:var(--mute);background:#1d1d29}
.n{font-size:46px;font-weight:760;letter-spacing:-2.2px;line-height:1;margin-top:12px;
  background:linear-gradient(180deg,#fff,#c9c6e6);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hero.bad .n{background:linear-gradient(180deg,#fff,#fca5a5);-webkit-background-clip:text}
.hero.good .n{background:linear-gradient(180deg,#fff,#86efac);-webkit-background-clip:text}
.eq{margin-top:10px;font-size:11.5px;color:var(--mute);line-height:1.5}
.eq b{color:var(--ink);font-weight:650}
.seg{display:flex;height:8px;border-radius:99px;overflow:hidden;margin-top:16px;gap:2px;background:#1b1b26}
.seg i{display:block;height:100%%}
.legend{display:flex;flex-wrap:wrap;gap:6px 13px;margin-top:12px}
.lg{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--mute)}
.dot{width:7px;height:7px;border-radius:2.5px;flex:0 0 auto}
.stats{display:grid;grid-template-columns:repeat(%(cols)s,1fr);gap:8px;margin:10px 20px 0}
.st{background:var(--card);border:1px solid var(--line);border-radius:15px;padding:12px 13px}
.st .k{font-size:9.5px;letter-spacing:1px;text-transform:uppercase;color:var(--dim);font-weight:700}
.st .v{font-size:16.5px;font-weight:700;letter-spacing:-.5px;margin-top:5px;white-space:nowrap}
.st .m{font-size:10.5px;color:var(--dim);margin-top:2px}
.lab{display:flex;justify-content:space-between;align-items:baseline;margin:20px 22px 8px}
.lab .t{font-size:10.5px;letter-spacing:1.3px;text-transform:uppercase;color:var(--dim);font-weight:700}
.lab .r{font-size:11px;color:var(--mute);font-weight:600}
.list{margin:0 20px;background:var(--card);border:1px solid var(--line);border-radius:18px;overflow:hidden}
.row{display:flex;align-items:center;gap:11px;padding:11px 14px;position:relative}
.row+.row::before{content:"";position:absolute;left:14px;right:14px;top:0;height:1px;
  background:linear-gradient(90deg,transparent,var(--line) 15%%,var(--line) 85%%,transparent)}
.sq{width:32px;height:32px;border-radius:10px;flex:0 0 auto;display:flex;align-items:center;justify-content:center}
.sq svg{display:block}
.row.done .sq{opacity:.42;filter:saturate(.5)}
.warn svg,.pill svg{flex:0 0 auto;display:inline-block;vertical-align:-2px}
.mid{flex:1;min-width:0}
.nm{font-size:14px;font-weight:560;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mt{font-size:10.5px;color:var(--dim);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.amt{font-size:14px;font-weight:700;letter-spacing:-.3px;text-align:right;white-space:nowrap}
.amt small{display:block;font-size:10px;font-weight:600;color:var(--dim);margin-top:2px;letter-spacing:0}
.row.done .nm,.row.done .amt{color:var(--dim)} .row.done .amt{text-decoration:line-through;text-decoration-color:#3a3a4a}
.ok{color:var(--green)!important} .bad{color:var(--red)!important} .amb{color:var(--amber)!important}
.prog{display:flex;align-items:center;gap:10px;margin:10px 20px 0;background:var(--card);border:1px solid var(--line);
  border-radius:14px;padding:11px 14px}
.prog .tr{flex:1;height:5px;border-radius:99px;background:#1d1d29;overflow:hidden}
.prog .tr i{display:block;height:100%%;background:linear-gradient(90deg,var(--violet),var(--blue))}
.prog .tx{font-size:10.5px;color:var(--mute);font-weight:600;white-space:nowrap}
.tiles{margin:0 20px;display:flex;flex-direction:column;gap:7px}
.tile{display:flex;align-items:center;justify-content:space-between;background:var(--card2);border:1px solid var(--line);
  border-radius:14px;padding:12px 14px}
.tile .w{font-size:13px;font-weight:600} .tile .m{font-size:10.5px;color:var(--dim);margin-top:2px}
.tile .v{font-size:15px;font-weight:700;letter-spacing:-.4px;text-align:right}
.tl{margin:0 20px;background:var(--card);border:1px solid var(--line);border-radius:18px;padding:6px 0}
.tlr{display:grid;grid-template-columns:96px 1fr 92px;align-items:center;gap:10px;padding:10px 14px}
.tlr .p{font-size:12.5px;font-weight:620} .tlr .p small{display:block;font-size:10px;color:var(--dim);font-weight:600;margin-top:2px}
.bar{position:relative;height:22px}
.bar .axis{position:absolute;top:0;bottom:0;width:1px;background:var(--line2)}
.bar i{position:absolute;top:5px;height:12px;border-radius:4px}
.tlr .v{font-size:13.5px;font-weight:700;text-align:right;letter-spacing:-.3px}
.tlr .v small{display:block;font-size:10px;color:var(--dim);font-weight:600;margin-top:2px}
.tlr.low{background:rgba(248,113,113,.06)}
.cmp{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:10px 20px 0}
.cmp .c{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px}
.cmp .c .k{font-size:10px;letter-spacing:1px;text-transform:uppercase;color:var(--dim);font-weight:700}
.cmp .c .v{font-size:22px;font-weight:740;letter-spacing:-.8px;margin-top:6px}
.cmp .c .m{font-size:10.5px;color:var(--dim);margin-top:3px}
.note{margin:16px 22px 0;font-size:10.5px;color:var(--dim);line-height:1.6}
.pd{display:flex;align-items:center;gap:8px;margin-top:12px;font-size:12.5px;color:#d9d6f5;background:rgba(139,92,246,.12);
  border:1px solid rgba(139,92,246,.25);border-radius:12px;padding:8px 11px}
.pd b{color:#fff}
.rwt{font-size:25px;font-weight:740;letter-spacing:-.8px;line-height:1.15;margin-top:10px}
.rwt em{font-style:normal;color:#fca5a5} .rwt em.g{color:#86efac}
.rwh{padding-bottom:12px}
.rwh .rw{display:block;margin:14px -20px -6px;width:390px}
.chips{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin:0 20px}
.ch{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:10px 11px}
.ch .k{font-size:10px;color:var(--dim);font-weight:650;white-space:nowrap}
.ch .v{font-size:15px;font-weight:720;letter-spacing:-.4px;margin-top:3px}
.ics{display:flex;flex-wrap:wrap;gap:6px;margin-top:7px}
.ic{display:inline-flex;align-items:center;gap:5px;font-size:11px;color:var(--mute);background:var(--card2);
  border:1px solid var(--line);border-radius:99px;padding:3px 9px 3px 6px}
"""


def page(body, cols=3, glow=""):
    css = CSS % {"font": FONT, "w": WIDTH, "cols": cols}
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head>'
            f'<body><div class="glow {glow}"></div><div class="z">{body}</div>'
            '<script>document.fonts.ready.then(function(){document.body.setAttribute("data-h",'
            'Math.ceil(document.querySelector(".z").getBoundingClientRect().bottom+22))})</script></body></html>')


def header(title, sub, today):
    t = mm.d(today)
    return (f'<div class="top"><div class="brand"><div class="mark">M</div><span>Money Map</span></div>'
            f'<span class="when">{mm.MONTHS[t.month]} {t.day}</span></div>'
            f'<h1>{esc(title)}</h1><div class="sub">{esc(sub)}</div>')


def stale_banner(p):
    if p.get("stale_days", 0) > 3:
        return (f'<div class="warn">{icons.svg("warning", "fill", 14, "#fcd34d")} Cash last updated {short_date(p["asOf"])} '
                f'({p["stale_days"]} days ago)</div>')
    return ""


def icon(st, *, flow_id=None, category=None, balance_id=None, done=False):
    """Rounded tile with the item's icon in its category colour. Open = duotone, done = plain line."""
    name, c = icons.look(looks(st), flow_id=flow_id, category=category, balance_id=balance_id)
    return (f'<div class="sq" style="background:{c}24;color:{c}">'
            f'{icons.svg(name, "regular" if done else "duotone", 18)}</div>')


def seg_bar(st, cats, total):
    if total <= 0:
        return ""
    top = cats[:5]
    rest = sum(c["amount"] for c in cats[5:])
    parts = [(c["name"], c["amount"], icons.category_color(looks(st), c["name"])) for c in top]
    if rest > 0:
        parts.append(("Other", rest, "#4b4b60"))
    bars = "".join(f'<i style="width:{a / total * 100:.2f}%;background:{col}"></i>' for _, a, col in parts)
    leg = "".join(f'<span class="lg"><i class="dot" style="background:{col}"></i>{esc(n)} '
                  f'{a / total * 100:.0f}%</span>' for n, a, col in parts)
    return f'<div class="seg">{bars}</div><div class="legend">{leg}</div>'


STATUS = {"paid": ("Paid", "ok"), "settled": ("In snapshot", ""), "partial": ("Part paid", "amb"),
          "pending": ("", "")}


def bill_row(st, e):
    label, cls = STATUS[e["status"]]
    done = e["status"] in ("paid", "settled")
    meta = [short_date(e["date"]), e["category"]]
    if e["status"] == "partial":
        meta.append(f"{peso(e['paid'], False)} paid")
    amount = e["amount"] if done else e["remaining"]
    small = f'<small class="{cls}">{label}</small>' if label else ""
    return (f'<div class="row{" done" if done else ""}">{icon(st, flow_id=e["id"], category=e["category"], done=done)}'
            f'<div class="mid"><div class="nm">{esc(clean_name(e["name"]))}</div>'
            f'<div class="mt">{esc(" · ".join(meta))}</div></div>'
            f'<div class="amt">{peso(amount)}{small}</div></div>')


def spend_block(st, p):
    sp = p.get("spends") or []
    if not sp:
        return ""
    by = {}
    for e in sp:
        by[e["category"]] = by.get(e["category"], 0.0) + e["amount"]
    rows = "".join(
        f'<div class="row">{icon(st, category=c)}<div class="mid"><div class="nm">{esc(c)}</div>'
        f'<div class="mt">{plural(sum(1 for e in sp if e["category"] == c), "entry", "entries")}</div></div>'
        f'<div class="amt">{peso(v, False)}</div></div>'
        for c, v in sorted(by.items(), key=lambda kv: -kv[1])[:4])
    last = sp[-1]
    return (f'<div class="lab"><span class="t">Spent this period</span><span class="r">{peso(p["spent"], False)}</span></div>'
            f'<div class="list">{rows}</div>'
            f'<div class="note" style="margin-top:8px">Last: {esc(last["name"])} · {peso(last["amount"], False)} · '
            f'{short_date(last["date"])}</div>')


# ---------------------------------------------------------------- card builders
def card_period(st, a):
    on = mm.d(a.on) if a.on else None
    p = mm.period_detail(st, on=on, offset=a.offset, scenario=a.scenario)
    left = p["left"]
    tone = "" if left is None else ("bad" if left < 0 else ("good" if left > 0.15 * max(p["income"], 1) else ""))
    today = mm.d(p["today"])
    days_left = (mm.d(p["period"]["end"]) - today).days + 1
    when = (f"{days_left} days left" if 0 < days_left <= 16 and mm.d(p["period"]["start"]) <= today
            else "upcoming" if mm.d(p["period"]["start"]) > today else "ended")
    cls = "red" if tone == "bad" else "green" if tone == "good" else "amber" if left is not None else "mute"
    pill = f'<span class="pill {cls}">{when}</span>'
    hero_k = "Short by" if left is not None and left < 0 else "Left after bills"
    eq = ""
    if p["carry"] is not None:
        spent = f' − <b>{peso(p["spent"], False)}</b> spent' if p["spent"] else ""
        eq = (f'<div class="eq"><b>{peso(p["carry"], False)}</b> brought forward + <b>{peso(p["income"], False)}</b> in '
              f'− <b>{peso(p["out"], False)}</b> bills{spent}</div>')
    current = mm.d(p["period"]["start"]) <= today <= mm.d(p["period"]["end"])
    if left is not None and left > 0 and current:
        eq += (f'<div class="pd">{icons.svg("coins", "duotone", 15)}<span>About <b>{peso(p["per_day"], False)}/day</b> '
               f'to spend for {p["days_left"]} day{"s" if p["days_left"] != 1 else ""}</span></div>')
    hero = (f'<div class="hero {tone}"><div class="k"><span>{hero_k}</span>{pill}</div>'
            f'<div class="n">{peso(abs(left) if left is not None else None)}</div>{eq}'
            f'{seg_bar(st, p["categories"], p["out"])}</div>')
    bills = [e for e in p["items"] if e["direction"] == "expense" and not e["spend"]]
    order = {"pending": 0, "partial": 0, "paid": 1, "settled": 2}
    bills.sort(key=lambda e: (order[e["status"]], e["date"], -e["amount"]))
    shown, hidden = bills[:8], bills[8:]
    rows = "".join(bill_row(st, e) for e in shown)
    if hidden:
        h_open = [e for e in hidden if e["status"] in ("pending", "partial")]
        txt = (f'+ {len(hidden)} more · {peso(sum(e["remaining"] for e in h_open))} still due' if h_open
               else f'+ {len(hidden)} more, all paid')
        rows += f'<div class="row"><div class="mid"><div class="mt">{txt}</div></div></div>'
    open_n = sum(1 for e in bills if e["status"] in ("pending", "partial"))
    done = p["bills_done"]
    pct = done / p["bills_total"] * 100 if p["bills_total"] else 0
    prog = (f'<div class="prog"><span class="tx">{done} / {p["bills_total"]} done</span>'
            f'<div class="tr"><i style="width:{max(pct, 2):.0f}%"></i></div>'
            f'<span class="tx">{open_n} open</span></div>')
    nxt = mm.timeline(st, periods=a.offset + 3, on=on, scenario=a.scenario)[a.offset + 1:]
    tiles = "".join(
        f'<div class="tile"><div><div class="w">{esc(r["label"])}</div>'
        f'<div class="m">{peso(r["income"], False)} in · {peso(r["out"], False)} out</div></div>'
        f'<div class="v {"bad" if (r["left"] or 0) < 0 else "ok"}">{peso(r["left"], False)}'
        f'<div class="m" style="text-align:right">left at end</div></div></div>' for r in nxt)
    body = (header(p["period"]["label"], f'{p["period"]["name"]} · {plural(open_n, "bill")} open', p["today"])
            + stale_banner(p) + hero
            + f'<div class="lab"><span class="t">Bills this period</span><span class="r">{peso(p["out"])} pending</span></div>'
            + f'<div class="list">{rows or "<div class=row><div class=mt>No bills</div></div>"}</div>' + prog
            + spend_block(st, p)
            + f'<div class="lab"><span class="t">Coming up</span></div><div class="tiles">{tiles}</div>'
            + f'<div class="note">Scenario: {esc(p["scenario"])} pay · cash snapshot {short_date(p["asOf"])}. '
              'Bills before the snapshot are already in that cash.</div>')
    if left is None:
        cap = f'{p["period"]["label"]}: this period is before your cash snapshot.'
    elif left < 0:
        cap = f'{p["period"]["label"]}: short by {peso(-left)} after {peso(p["out"])} in bills.'
    else:
        cap = (f'{p["period"]["label"]}: {peso(left)} left' +
               (f' after {peso(p["out"])} in bills.' if p["out"] else ', all bills paid.'))
        if current and p["per_day"]:
            cap += f' About {peso(p["per_day"], False)}/day for {p["days_left"]} days.'
    if p["stale_days"] > 3:
        cap += f' Snapshot is {p["stale_days"]} days old.'
    return page(body, glow="red" if tone == "bad" else ""), cap


def card_bills(st, a):
    on = mm.d(a.on) if a.on else date.today()
    rows = mm.upcoming_bills(st, days=a.days, on=on)
    total = sum(e["remaining"] for e in rows)
    overdue = [e for e in rows if e["state"] == "overdue"]
    groups, html_rows = {}, ""
    for e in rows:
        groups.setdefault(e["when"], []).append(e)
    unmarked = [e for e in rows if e["state"] == "unmarked"]
    for when, es in groups.items():
        dd = es[0]["days"]
        st_ = es[0]["state"]
        tag = ("Overdue" if st_ == "overdue" else "Not marked paid" if st_ == "unmarked" else
               "Today" if dd == 0 else "Tomorrow" if dd == 1 else f"In {dd} days")
        cls = "bad" if st_ == "overdue" else ("amb" if st_ == "unmarked" or dd <= 1 else "")
        html_rows += (f'<div class="lab" style="margin-top:14px"><span class="t {cls}">{short_date(when)} · {tag}</span>'
                      f'<span class="r">{peso(sum(x["remaining"] for x in es))}</span></div><div class="list">')
        top, more = es[:5], es[5:]
        html_rows += "".join(
            f'<div class="row">{icon(st, flow_id=e["id"], category=e["category"])}<div class="mid"><div class="nm">{esc(clean_name(e["name"]))}</div>'
            f'<div class="mt">{esc(e["category"])}{" · due date" if e.get("due") else ""}</div></div>'
            f'<div class="amt">{peso(e["remaining"])}</div></div>' for e in top)
        if more:
            html_rows += (f'<div class="row"><div class="mid"><div class="mt">+ {len(more)} more · '
                          f'{peso(sum(x["remaining"] for x in more))}</div></div></div>')
        html_rows += "</div>"
    p = {"stale_days": (on - mm.d(st["asOf"])).days, "asOf": st["asOf"]}
    tone = "bad" if overdue else ""
    if overdue:
        pill = f'<span class="pill red">{len(overdue)} overdue</span>'
    elif unmarked:
        pill = f'<span class="pill amber">{len(unmarked)} not marked paid</span>'
    else:
        pill = f'<span class="pill mute">{len(rows)} bills</span>'
    hero = (f'<div class="hero {tone}"><div class="k"><span>Unpaid, next {a.days} days</span>{pill}</div>'
            f'<div class="n">{peso(total)}</div></div>')
    body = (header("Bills due", f"{len(rows)} unpaid · through {short_date((on + timedelta(days=a.days)).isoformat())}",
                   on.isoformat()) + stale_banner(p) + hero
            + (html_rows or '<div class="note">Nothing unpaid in this window.</div>')
            + '<div class="note">Dates are the pay period each bill sits in unless a real due date is set.</div>')
    cap = f'{len(rows)} unpaid bills in the next {a.days} days, {peso(total)} total.'
    if overdue:
        cap += f' {len(overdue)} overdue.'
    if unmarked:
        cap += f' {len(unmarked)} from earlier dates are not marked paid yet.'
    return page(body, glow=tone and "red"), cap


def runway_series(st, on, end, scenario):
    """Cash at the end of each day from `on` to `end`, same rules as the period engine
    (snapshot at asOf, then every unpaid event after it)."""
    asof = mm.d(st["asOf"])
    cash = float(st["startingCash"])
    delta = {}
    for e in mm._events(st, asof + timedelta(days=1), end, scenario, mm._paid_map(st)):
        sign = 1 if e["direction"] == "income" else -1
        if mm.d(e["date"]) <= on:
            cash += sign * e["remaining"]
        else:
            delta[e["date"]] = delta.get(e["date"], 0.0) + sign * e["remaining"]
    out, day = [(on, round(cash, 2))], on
    while day < end:
        day += timedelta(days=1)
        cash += delta.get(day.isoformat(), 0.0)
        out.append((day, round(cash, 2)))
    return out


def runway_svg(series, rows, low_i):
    W, H, top, bot = 390, 176, 18, 146
    vals = [v for _, v in series]
    lo, hi = min(min(vals), 0), max(max(vals), 0)
    pad = (hi - lo) * 0.08 or 1
    lo, hi = lo - pad, hi + pad
    n = len(series) - 1 or 1
    X = lambda i: 6 + i / n * (W - 12)
    Y = lambda v: top + (hi - v) / (hi - lo) * (bot - top)
    zy = Y(0)
    line = f"M{X(0):.1f},{Y(vals[0]):.1f}" + "".join(f"H{X(i):.1f}V{Y(v):.1f}" for i, v in enumerate(vals) if i)
    area = line + f"H{X(n):.1f}V{zy:.1f}H{X(0):.1f}Z"
    first = series[0][0]
    grid = ""
    for r in rows[1:]:
        i = (mm.d(r["start"]) - first).days
        if 0 < i < n:
            grid += f'<line x1="{X(i):.1f}" x2="{X(i):.1f}" y1="{top - 6}" y2="{bot}" stroke="#22222e"/>'
            if X(i) > 62 and X(i) < W - 22:          # keep clear of the "Today" label and the right edge
                grid += f'<text x="{X(i):.1f}" y="{bot + 18}" text-anchor="middle">{short_date(r["start"])}</text>'
    lx, lv = X(low_i), vals[low_i]
    if lv < 0:                                  # below zero: label beside the dot, clear of the date row.
        # Left of the lowest point the line is always higher, so that side is free.
        anchor = "end" if lx > 80 else "start"
        lx_t, ly = (lx - 9 if anchor == "end" else lx + 9), Y(lv) + 4
    else:
        anchor = "end" if lx > W - 70 else ("start" if lx < 70 else "middle")
        lx_t, ly = lx, Y(lv) - 9
    lowc, lowt = ("#f87171", "#fca5a5") if lv < 0 else ("#a78bfa", "#c4b5fd")
    return f"""<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" class="rw">
<defs>
 <clipPath id="up"><rect x="0" y="0" width="{W}" height="{zy:.1f}"/></clipPath>
 <clipPath id="dn"><rect x="0" y="{zy:.1f}" width="{W}" height="{H}"/></clipPath>
 <linearGradient id="gu" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#8b5cf6" stop-opacity=".38"/><stop offset="1" stop-color="#8b5cf6" stop-opacity="0"/></linearGradient>
 <linearGradient id="gd" x1="0" x2="0" y1="1" y2="0"><stop offset="0" stop-color="#f87171" stop-opacity=".38"/><stop offset="1" stop-color="#f87171" stop-opacity="0"/></linearGradient>
</defs>
<g font-size="10" fill="#62627a" font-weight="600">{grid}</g>
<line x1="0" x2="{W}" y1="{zy:.1f}" y2="{zy:.1f}" stroke="#3a3a4c" stroke-dasharray="3 4"/>
<text x="{W - 2}" y="{zy - 5:.1f}" text-anchor="end" font-size="10" fill="#62627a" font-weight="600">₱0</text>
<path d="{area}" fill="url(#gu)" clip-path="url(#up)"/><path d="{area}" fill="url(#gd)" clip-path="url(#dn)"/>
<path d="{line}" fill="none" stroke="#a78bfa" stroke-width="2.2" stroke-linejoin="round" clip-path="url(#up)"/>
<path d="{line}" fill="none" stroke="#f87171" stroke-width="2.2" stroke-linejoin="round" clip-path="url(#dn)"/>
<circle cx="{X(0):.1f}" cy="{Y(vals[0]):.1f}" r="4" fill="#f5f5f8"/>
<text x="{X(0) + 2:.1f}" y="{bot + 18}" font-size="10" fill="#9a9aae" font-weight="700">Today</text>
<circle cx="{lx:.1f}" cy="{Y(lv):.1f}" r="4.5" fill="{lowc}" stroke="#08080c" stroke-width="2"/>
<text x="{lx_t:.1f}" y="{ly:.1f}" text-anchor="{anchor}" font-size="11" font-weight="700" fill="{lowt}">{peso(lv, False)}</text>
</svg>"""


def card_timeline(st, a):
    on = mm.d(a.on) if a.on else date.today()
    scen = a.scenario or st.get("scenario") or "average"
    rows = mm.timeline(st, periods=a.periods, on=on, scenario=scen)
    end = mm.d(rows[-1]["end"])
    series = runway_series(st, on, end, scen)
    low_i = min(range(len(series)), key=lambda i: series[i][1])
    low_d, low_v = series[low_i]
    dip = next((i for i, (_, v) in enumerate(series) if v < 0), None)
    back = next((i for i in range(low_i, len(series)) if series[i][1] >= 0), None) if dip is not None else None
    if dip == 0:
        head, tone = "Already <em>below zero</em> today", "bad"
    elif dip is not None:
        head, tone = f'Dips below zero on <em>{short_date(series[dip][0].isoformat())}</em>', "bad"
    else:
        head, tone = f'Stays above zero to <em class="g">{short_date(end.isoformat())}</em>', "good"
    facts = [f'Lowest <b>{peso(low_v, False)}</b> on {short_date(low_d.isoformat())}']
    if back is not None:
        facts.append(f'back above zero {short_date(series[back][0].isoformat())}')
    facts.append(f'ends at <b>{peso(series[-1][1], False)}</b>')
    pill = "red" if tone == "bad" else "green"
    hero = (f'<div class="hero {tone} rwh"><div class="k"><span>Cash runway</span>'
            f'<span class="pill {pill}">{len(rows)} periods</span></div>'
            f'<div class="rwt">{head}</div><div class="eq">{" · ".join(facts)}</div>'
            f'{runway_svg(series, rows, low_i)}</div>')
    chips = "".join(
        f'<div class="ch"><div class="k">{esc(r["label"])}</div>'
        f'<div class="v {"bad" if (r["left"] or 0) < 0 else ""}">{peso(r["left"], False)}</div></div>' for r in rows)
    paid = mm._paid_map(st)
    big = [e for e in mm._events(st, on + timedelta(days=1), end, scen, paid)
           if e["direction"] == "expense" and e["remaining"] > 0.005]
    groups = {}                                   # one row per bill: next date, how often it repeats, total
    for e in big:
        g = groups.setdefault(icons.bill_key(e["name"]), {"e": e, "n": 0, "total": 0.0})
        g["n"] += 1
        g["total"] += e["remaining"]
    top5 = sorted(groups.values(), key=lambda g: -g["total"])[:5]
    top5.sort(key=lambda g: g["e"]["date"])

    def meta(g):
        e = g["e"]
        bits = [short_date(e["date"]), f'in {(mm.d(e["date"]) - on).days} days']
        bits.append(f'{g["n"]}× to {short_date(end.isoformat())}' if g["n"] > 1 else e["category"])
        return " · ".join(bits)
    bill_rows = "".join(
        f'<div class="row">{icon(st, flow_id=g["e"]["id"], category=g["e"]["category"])}<div class="mid">'
        f'<div class="nm">{esc(clean_name(g["e"]["name"]))}</div><div class="mt">{esc(meta(g))}</div></div>'
        f'<div class="amt">{peso(g["total"], False)}'
        f'{"<small>" + peso(g["e"]["remaining"], False) + " each</small>" if g["n"] > 1 else ""}</div></div>'
        for g in top5)
    p = {"stale_days": (on - mm.d(st["asOf"])).days, "asOf": st["asOf"]}
    body = (header("Cash runway", f"Next {len(rows)} pay periods · {scen} pay", on.isoformat())
            + stale_banner(p) + hero
            + '<div class="lab"><span class="t">Left at end of each period</span></div>'
            + f'<div class="chips">{chips}</div>'
            + (f'<div class="lab"><span class="t">Biggest bills ahead</span><span class="r">total to {short_date(end.isoformat())}</span></div><div class="list">{bill_rows}</div>'
               if bill_rows else "")
            + '<div class="note">Daily cash from your snapshot plus scheduled pay and unpaid bills.</div>')
    if dip == 0:
        cap = f"Already below zero today ({peso(series[0][1])})."
    elif dip is not None:
        cap = f"Dips below zero on {short_date(series[dip][0].isoformat())}."
    else:
        cap = f"Stays above zero through {short_date(end.isoformat())}."
    cap += f" Lowest {peso(low_v)} on {short_date(low_d.isoformat())}; ends at {peso(series[-1][1])}."
    return page(body, glow="red" if tone == "bad" else ""), cap


def card_icons(st, a):
    T = looks(st)
    cats = icons._cat_order(st)
    blocks = ""
    for c in cats:
        col = icons.category_color(T, c)
        flows, seen = [], set()
        for f in st["flows"]:
            if (f.get("category") or "Other") == c and icons.bill_key(f["name"]) not in seen:
                seen.add(icons.bill_key(f["name"]))
                flows.append(f)
        chips = "".join(
            f'<span class="ic">{icons.svg(icons.look(T, flow_id=f["id"], category=c)[0], "duotone", 15, col)}'
            f'{esc(clean_name(f["name"]))}</span>' for f in flows)
        cname = esc(T.get("cat:" + c, {}).get("color", ""))
        blocks += (f'<div class="row" style="align-items:flex-start">{icon(st, category=c)}'
                   f'<div class="mid"><div class="nm">{esc(c)} <span class="mt" style="display:inline">'
                   f'· {cname}</span></div><div class="ics">{chips}</div></div></div>')
    auto = sum(1 for v in T.values() if v.get("auto"))
    body = (header("Icons & colours", f"{len(st['flows'])} bills · {len(cats)} categories", date.today().isoformat())
            + f'<div class="list" style="margin-top:16px">{blocks}</div>'
            + f'<div class="note">Colour = category, icon = bill. Red, green and amber are kept for status. '
              f'{auto} picks are automatic; change one with moneymap icon set.</div>')
    return page(body), f"{len(st['flows'])} bills across {len(cats)} categories, each with its own icon."


def card_receipt(st, a):
    pays = sorted(st.get("payments", []), key=lambda p: (p["paidOn"], p["id"]))
    if not pays:
        raise SystemExit("no payments recorded")
    pay = next((p for p in pays if p["id"] == a.payment), None) if a.payment else pays[-1]
    if not pay:
        raise SystemExit(f"payment {a.payment} not found")
    flow = next((f for f in st["flows"] if f["id"] == pay["flowId"]), {"name": pay["flowId"], "category": "Other"})
    on = mm.d(a.on) if a.on else None
    p = mm.period_detail(st, on=on or mm.d(pay["originalDate"]))
    item = next((e for e in p["items"] if e["id"] == pay["flowId"] and e["date"] == pay["originalDate"]), None)
    rem = item["remaining"] if item else 0
    body = (header("Payment recorded", f'{esc(clean_name(flow["name"]))} · {short_date(pay["paidOn"])}',
                   (on or date.today()).isoformat())
            + f'<div class="hero good"><div class="k"><span>Paid</span><span class="pill green">{icons.svg("check-circle", "fill", 11)} Saved</span></div>'
              f'<div class="n">{peso(pay["amount"])}</div>'
              f'<div class="eq">{"Fully paid" if rem <= 0.005 else peso(rem) + " still due on this bill"}</div></div>'
            + '<div class="stats">'
              f'<div class="st"><div class="k">Period</div><div class="v" style="font-size:14px">{esc(p["period"]["label"])}</div></div>'
              f'<div class="st"><div class="k">Bills open</div><div class="v">{p["bills_total"] - p["bills_done"]}</div></div>'
              f'<div class="st"><div class="k">Left</div><div class="v {"bad" if (p["left"] or 0) < 0 else "ok"}">{peso(p["left"], False)}</div></div>'
              '</div>')
    cap = f'Recorded {peso(pay["amount"])} for {clean_name(flow["name"])}.'
    if p["left"] is not None:
        cap += f' {p["period"]["label"]}: {peso(p["left"])} left.'
    return page(body), cap


def card_whatif(st, a):
    if a.amount is None:
        raise SystemExit("whatif needs --amount")
    when = mm.d(a.date) if a.date else (mm.d(a.on) if a.on else date.today())
    p = mm.period_detail(st, on=when, scenario=a.scenario)
    before = p["left"]
    after = None if before is None else before - a.amount
    rows = mm.timeline(st, periods=4, on=when, scenario=a.scenario)
    ok = after is not None and after >= 0
    later = next((r for r in rows[1:] if r["left"] is not None and r["left"] >= 0 and r["left"] - a.amount < 0), None)
    tone = "good" if ok and not later else ("" if ok else "bad")
    if after is None:
        verdict = "Before your snapshot"
    elif ok and later:
        verdict = f"Fits now, short in {later['label']}"
    elif ok:
        verdict = "Yes, it fits"
    elif before is not None and before < 0:
        verdict = "Already short this period"
    else:
        verdict = "It would leave you short"
    tiles = "".join(
        f'<div class="tile"><div><div class="w">{esc(r["label"])}</div><div class="m">left at end</div></div>'
        f'<div class="v">{peso(r["left"], False)} → <span class="{"bad" if (r["left"] or 0) - a.amount < 0 else "ok"}">'
        f'{peso(None if r["left"] is None else r["left"] - a.amount, False)}</span></div></div>' for r in rows)
    body = (header(f"Can I afford it?", f'{esc(a.label)} · {peso(a.amount)} · {short_date(when.isoformat())}',
                   (mm.d(a.on) if a.on else date.today()).isoformat()) + stale_banner(p)
            + f'<div class="hero {tone}"><div class="k"><span>{verdict}</span>'
              f'<span class="pill {"green" if tone == "good" else "amber" if ok else "red"}">{esc(p["period"]["label"])}</span></div>'
              f'<div class="n">{peso(after)}</div><div class="eq">left this period after it '
              f'(was <b>{peso(before)}</b>)</div></div>'
            + '<div class="lab"><span class="t">Knock-on effect</span><span class="r">before → after</span></div>'
            + f'<div class="tiles">{tiles}</div>'
            + '<div class="note">One-off spend, taken from this period. Nothing is recorded until you confirm it.</div>')
    fit = ("fits this period but leaves " + later["label"] + " short" if ok and later else "fits" if ok
           else "causes a shortfall")
    cap = (f'{a.label} ({peso(a.amount)}): {fit} — '
           f'{peso(after)} left in {p["period"]["label"]} (was {peso(before)}).')
    return page(body, glow="" if ok else "red"), cap


def card_debts(st, a):
    debts = mm.debt_status(st)
    total_now = sum(x["now"] for x in debts)
    paid = sum(x["paid_since"] for x in debts)
    biggest = max((x["now"] for x in debts), default=0) or 1
    rows = "".join(
        f'<div class="row">{icon(st, balance_id=x["id"])}<div class="mid"><div class="nm">{esc(x["name"])}</div>'
        f'<div class="seg" style="margin-top:7px;height:6px"><i style="width:{x["now"] / biggest * 100:.1f}%;'
        f'background:{icons.look(looks(st), balance_id=x["id"])[1]}"></i></div>'
        f'<div class="mt">{"−" + peso(x["paid_since"], False) + " paid since " if x["paid_since"] else "as of "}'
        f'{short_date(x["asOf"]) if x.get("asOf") else "—"}{"" if x["bills"] else " · not linked to a bill"}</div></div>'
        f'<div class="amt">{peso(x["now"], False)}<small>{x["now"] / (total_now or 1) * 100:.0f}%</small></div></div>'
        for x in debts if x["now"] > 0.005)
    cleared = [x for x in debts if x["now"] <= 0.005]
    hero_eq = f'<div class="eq"><b>{peso(paid, False)}</b> paid off since the last snapshots</div>' if paid else ""
    body = (header("Debts", f"{len(debts) - len(cleared)} open" + (f" · {len(cleared)} cleared" if cleared else ""),
                   (mm.d(a.on) if a.on else date.today()).isoformat())
            + f'<div class="hero"><div class="k"><span>Total owed now</span><span class="pill mute">live</span></div>'
              f'<div class="n">{peso(total_now)}</div>{hero_eq}</div>'
            + f'<div class="lab"><span class="t">By balance</span></div><div class="list">{rows}</div>'
            + '<div class="note">Each balance drops when you pay a bill linked to it (moneymap debt-link). '
              'Interest and fees only show up when the balance is updated from a statement.</div>')
    cap = f'{len(debts) - len(cleared)} debts, {peso(total_now)} owed now.'
    if paid:
        cap += f' {peso(paid)} paid off since the snapshots.'
    return page(body), cap


BUILDERS = {"period": card_period, "bills": card_bills, "timeline": card_timeline,
            "receipt": card_receipt, "whatif": card_whatif, "debts": card_debts, "icons": card_icons}


# ---------------------------------------------------------------- rendering
def chromium():
    for c in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        p = shutil.which(c)
        if p:
            return p
    raise SystemExit("chromium not found")


BASE_FLAGS = ["--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
              "--no-first-run", "--disable-extensions", "--virtual-time-budget=3000"]


def render(html_doc, out_png):
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as fh:
        fh.write(html_doc)
        src = fh.name
    try:
        url = "file://" + src
        dom = subprocess.run([chromium(), *BASE_FLAGS, f"--window-size={WIDTH},300", "--dump-dom", url],
                             capture_output=True, text=True, timeout=60).stdout
        m = re.search(r'data-h="(\d+)"', dom)
        height = int(m.group(1)) if m else 1400
        if os.path.exists(out_png):
            os.remove(out_png)
        subprocess.run([chromium(), *BASE_FLAGS, f"--window-size={WIDTH},{height}",
                        f"--force-device-scale-factor={SCALE}", f"--screenshot={out_png}", url],
                       capture_output=True, timeout=60)
        if not os.path.exists(out_png) or os.path.getsize(out_png) < 1000:
            raise SystemExit("render failed: no PNG written")
        return out_png, height, src
    except Exception:
        os.remove(src)
        raise


def make(kind, state, args):
    doc, caption = BUILDERS[kind](state, args)
    out = args.out or os.path.join(tempfile.gettempdir(), "moneymap", f"{kind}.png")
    png, height, src = render(doc, out)
    if getattr(args, "html", False):
        shutil.copy(src, os.path.splitext(png)[0] + ".html")
    os.remove(src)
    return {"png": png, "caption": caption, "height": height}
