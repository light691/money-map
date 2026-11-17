#!/usr/bin/env python3
"""money-map agent CLI — SQLite-backed store for the Money Map forecast.

Single source of truth for the Hermes agent to read/write Money Map data.
DB lives at ../data/money-map.db (override with MONEYMAP_DB).

State model mirrors the web app (localStorage key 'money-map-v1'):
  {version, asOf, startingCash, scenario, horizon, flows[], balances[], payments[]}

  export  -> emits that exact JSON (drop-in for the app's Import backup)
  import  -> ingests the app's Export backup JSON
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import uuid
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.environ.get("MONEYMAP_DB", os.path.join(HERE, "..", "data", "money-map.db"))
STORAGE_KEY = "money-map-v1"

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS flows (
  id TEXT PRIMARY KEY, name TEXT NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('income','expense')),
  schedule  TEXT NOT NULL CHECK (schedule IN ('monthly','once')),
  amount REAL NOT NULL, low_amount REAL,
  day INTEGER, date TEXT, start TEXT, "end" TEXT,
  category TEXT, confidence TEXT, note TEXT, kind TEXT, due TEXT
);
CREATE TABLE IF NOT EXISTS overrides (
  flow_id TEXT NOT NULL REFERENCES flows(id) ON DELETE CASCADE,
  date TEXT NOT NULL, amount REAL NOT NULL,
  PRIMARY KEY (flow_id, date)
);
CREATE TABLE IF NOT EXISTS balances (
  id TEXT PRIMARY KEY, name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('asset','debt')),
  amount REAL NOT NULL, as_of TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS payments (
  id TEXT PRIMARY KEY, flow_id TEXT NOT NULL,
  original_date TEXT NOT NULL, paid_on TEXT NOT NULL,
  amount REAL NOT NULL, debt_reduction REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS spends (          -- day-to-day spending outside scheduled bills
  id TEXT PRIMARY KEY, date TEXT NOT NULL, amount REAL NOT NULL, category TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS debt_links (      -- paying this bill lowers that debt balance
  flow_id TEXT PRIMARY KEY, balance_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (        -- CLI-only settings; the web app never overwrites these
  key TEXT PRIMARY KEY, value TEXT
);
CREATE TABLE IF NOT EXISTS looks (           -- card icon + colour per bill / category / balance
  key TEXT PRIMARY KEY, icon TEXT, color TEXT -- key: flow:<id> | cat:<name> | bal:<id>
);
"""

# ---- seed = the web app's DEFAULT_STATE (Sept 2026 finance review) ----
SEED = {
  "version": 1, "asOf": "2026-11-01", "startingCash": 8000,
  "scenario": "average", "horizon": 3,
  "flows": [
    {"id":"pay-15","name":"15th payday","direction":"income","schedule":"monthly","amount":18000,"lowAmount":16500,"day":15,"start":"2026-11-01","category":"Pay","confidence":"estimate","note":"Sample data."},
    {"id":"pay-30","name":"30th payday","direction":"income","schedule":"monthly","amount":18000,"lowAmount":16500,"day":30,"start":"2026-11-01","category":"Pay","confidence":"estimate","note":"Sample data."},
    {"id":"rent","name":"Rent","direction":"expense","schedule":"monthly","amount":9000,"day":15,"start":"2026-11-01","category":"Household","confidence":"confirmed","due":"5"},
    {"id":"electric","name":"Electricity","direction":"expense","schedule":"monthly","amount":2500,"day":15,"start":"2026-11-01","category":"Utilities","confidence":"estimate"},
    {"id":"internet","name":"Internet","direction":"expense","schedule":"monthly","amount":1500,"day":30,"start":"2026-11-01","category":"Utilities","confidence":"confirmed"},
    {"id":"groceries","name":"Groceries","direction":"expense","schedule":"monthly","amount":4000,"day":30,"start":"2026-11-01","category":"Food","confidence":"estimate"},
    {"id":"phone-plan","name":"Phone plan","direction":"expense","schedule":"monthly","amount":999,"day":30,"start":"2026-11-01","category":"Utilities","confidence":"confirmed"},
    {"id":"card-pay","name":"Credit card payment","direction":"expense","schedule":"monthly","amount":3000,"day":15,"start":"2026-11-01","category":"Debt","confidence":"estimate"}
  ],
  "balances": [
    {"id":"card-balance","name":"Credit card","kind":"debt","amount":45000,"asOf":"2026-11-01"}
  ]
}

FLOW_COLS = ["id","name","direction","schedule","amount","low_amount","day","date","start","end","category","confidence","note","kind","due"]


def connect(db=None):
    path = db or DEFAULT_DB
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    init_db(con)          # guarantees schema + migrations on every connection
    return con


def init_db(con):
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(flows)")}
    if "due" not in cols:
        con.execute("ALTER TABLE flows ADD COLUMN due TEXT")
    if "deducted" not in {r[1] for r in con.execute("PRAGMA table_info(payments)")}:
        con.execute("ALTER TABLE payments ADD COLUMN deducted REAL NOT NULL DEFAULT 0")
    con.commit()


def set_meta(con, **kv):
    for k, v in kv.items():
        con.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (k, json.dumps(v)))


def get_meta(con, key, default=None):
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def clear_all(con):
    for t in ("overrides","payments","flows","balances","meta"):
        con.execute(f"DELETE FROM {t}")


def import_state(con, state, replace=True):
    if replace:
        clear_all(con)
    set_meta(con, version=state.get("version",1), asOf=state.get("asOf"),
             startingCash=state.get("startingCash"), scenario=state.get("scenario","average"),
             horizon=state.get("horizon",3))
    if state.get("budgetPeriod"):
        set_meta(con, budgetPeriod=state["budgetPeriod"])
    for f in state.get("flows", []):
        con.execute(
            f'INSERT OR REPLACE INTO flows({",".join(FLOW_COLS)}) VALUES({",".join("?"*len(FLOW_COLS))})',
            (f.get("id"), f.get("name"), f.get("direction"), f.get("schedule"), float(f.get("amount",0)),
             f.get("lowAmount"), f.get("day"), f.get("date") or None, f.get("start") or None,
             f.get("end") or None, f.get("category"), f.get("confidence"), f.get("note"), f.get("kind"),
             f.get("due")))
        for d, ov in (f.get("overrides") or {}).items():
            con.execute("INSERT OR REPLACE INTO overrides(flow_id,date,amount) VALUES(?,?,?)",
                        (f["id"], d, float(ov.get("amount", 0))))
    for b in state.get("balances", []):
        con.execute("INSERT OR REPLACE INTO balances(id,name,kind,amount,as_of,note) VALUES(?,?,?,?,?,?)",
                    (b.get("id"), b.get("name"), b.get("kind"), float(b.get("amount",0)), b.get("asOf"), b.get("note")))
    for p in state.get("payments", []):
        con.execute("INSERT OR REPLACE INTO payments(id,flow_id,original_date,paid_on,amount,debt_reduction,deducted) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (p.get("id"), p.get("flowId"), p.get("originalDate"), p.get("paidOn"),
                     float(p.get("amount",0)), float(p.get("debtReduction",0)),
                     float(p.get("amount", 0)) if p.get("deductedCash") else 0.0))
    con.commit()


def export_state(con):
    state = {
        "version": get_meta(con,"version",1),
        "asOf": get_meta(con,"asOf"),
        "startingCash": get_meta(con,"startingCash"),
        "scenario": get_meta(con,"scenario","average"),
        "horizon": get_meta(con,"horizon",3),
    }
    flows = []
    for r in con.execute("SELECT * FROM flows ORDER BY rowid"):
        f = {"id":r["id"],"name":r["name"],"direction":r["direction"],"schedule":r["schedule"],"amount":r["amount"]}
        for k_src,k_db in [("lowAmount","low_amount"),("day","day"),("category","category"),
                           ("confidence","confidence"),("note","note"),("kind","kind")]:
            if r[k_db] is not None: f[k_src] = r[k_db]
        for k in ("date", "start", "end", "due"):
            if r[k] is not None: f[k] = r[k]
        ovs = {o["date"]: {"date":o["date"],"amount":o["amount"]} for o in con.execute("SELECT * FROM overrides WHERE flow_id=?", (r["id"],))}
        if ovs: f["overrides"] = ovs
        flows.append(f)
    state["flows"] = flows
    state["balances"] = [{"id":b["id"],"name":b["name"],"kind":b["kind"],"amount":b["amount"],
                          **({"asOf":b["as_of"]} if b["as_of"] else {}), **({"note":b["note"]} if b["note"] else {})}
                         for b in con.execute("SELECT * FROM balances ORDER BY rowid")]
    pays = [{"id":p["id"],"flowId":p["flow_id"],"originalDate":p["original_date"],"paidOn":p["paid_on"],
             "amount":p["amount"],"debtReduction":p["debt_reduction"],
             **({"deductedCash": True} if p["deducted"] else {})}
            for p in con.execute("SELECT * FROM payments ORDER BY paid_on")]
    if pays: state["payments"] = pays
    bp = get_meta(con,"budgetPeriod")
    if bp: state["budgetPeriod"] = bp
    return state


# ---------- helpers ----------
def d(s):  # parse ISO date
    return datetime.strptime(s, "%Y-%m-%d").date()


def occurrences(flow, start, end):
    """Yield ISO dates the flow hits in [start,end] (inclusive)."""
    out = []
    if flow["schedule"] == "once":
        if flow.get("date") and start <= d(flow["date"]) <= end:
            out.append(flow["date"])
        return out
    fs, fe = d(flow["start"]), (d(flow["end"]) if flow.get("end") else None)
    cur = d(f"{start.year:04d}-{start.month:02d}-01")
    while cur <= end:
        y, m, day = cur.year, cur.month, min(flow["day"], _last_day(cur.year, cur.month))
        occ = date(y, m, day)
        if start <= occ <= end and occ >= fs and (fe is None or occ <= fe):
            out.append(occ.isoformat())
        cur = (cur + timedelta(days=32)).replace(day=1)
    return sorted(out)


def _last_day(y, m):
    return (date(y + (m == 12), 1 if m == 12 else m + 1, 1) - timedelta(days=1)).day


def effective_amount(flow, dt, scenario):
    ov = flow.get("overrides") or {}
    if dt in ov: return ov[dt]["amount"]
    if scenario == "low" and flow.get("lowAmount") is not None: return flow["lowAmount"]
    return flow["amount"]


def forecast(con, months, scenario, from_date):
    state = export_state(con)
    start = d(from_date) if from_date else (d(state["asOf"]) + timedelta(days=1))
    end = date(start.year, start.month, 1)
    end = (end + timedelta(days=32 * months)).replace(day=1) - timedelta(days=1)
    paid = {}
    for p in state.get("payments", []):
        paid.setdefault((p["flowId"], p["originalDate"]), 0.0)
        paid[(p["flowId"], p["originalDate"])] += p["amount"]
    events = []
    for f in state["flows"]:
        for occ in occurrences(f, start, end):
            amt = effective_amount(f, occ, scenario)
            rem = amt - paid.get((f["id"], occ), 0.0)
            if rem <= 0: continue
            events.append((occ, f["id"], f["name"], f["direction"], rem))
    events.sort()
    cash = float(state["startingCash"])
    rows = []
    for occ, fid, name, direction, amt in events:
        cash += amt if direction == "income" else -amt
        rows.append((occ, direction, name, amt, cash))
    return state, start, end, cash, rows


# ---------- period engine (structured data; the CLI, cards and API all use this) ----------
PAYDAYS = (10, 25)          # default; each user's own list lives in settings.paydays


def _paydays(state_or_days):
    if isinstance(state_or_days, dict):
        state_or_days = state_or_days.get("paydays")
    days = sorted({int(x) for x in (state_or_days or PAYDAYS)})
    if not days or any(not 1 <= x <= 31 for x in days):
        raise ValueError("paydays must be days of the month, 1-31")
    return days


def period_bounds(dt, paydays=PAYDAYS):
    """Pay period containing dt: from one payday to the day before the next. Returns (start, end, kind)
    where kind is 1 for the first payday of the month, 2 for the second, and so on.
    Paydays past the end of a short month land on its last day (30th -> Feb 28)."""
    days = _paydays(paydays)
    starts = []
    for k in (-1, 0, 1):
        y, m = dt.year + (dt.month - 1 + k) // 12, (dt.month - 1 + k) % 12 + 1
        for i, pd in enumerate(days):
            starts.append((date(y, m, min(pd, _last_day(y, m))), i + 1))
    starts.sort()
    start, kind = max((x for x in starts if x[0] <= dt), key=lambda x: x[0])
    nxt = min(x[0] for x in starts if x[0] > dt)
    return start, nxt - timedelta(days=1), kind


def shift_period(start, offset, paydays=PAYDAYS):
    """Start date of the period `offset` periods after the one starting at `start`."""
    s = start
    for _ in range(abs(offset)):
        if offset > 0:
            s = period_bounds(s, paydays)[1] + timedelta(days=1)
        else:
            s = period_bounds(s - timedelta(days=1), paydays)[0]
    return s


def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def period_name(start, kind, paydays):
    days = _paydays(paydays)
    if len(days) == 1:
        return f"Monthly · {ordinal(days[0])} pay"
    return f"{ordinal(kind)} period · {ordinal(days[kind - 1])} pay"


def period_label(start, end):
    if start.month == end.month:
        return f"{MONTHS[start.month]} {start.day}–{end.day}"
    return f"{MONTHS[start.month]} {start.day} – {MONTHS[end.month]} {end.day}"


def _paid_map(state):
    paid = {}
    for p in state.get("payments", []):
        k = (p["flowId"], p["originalDate"])
        paid[k] = paid.get(k, 0.0) + float(p["amount"])
    return paid


def due_for(flow, occ):
    """Real due date for one occurrence. `due` is a day of the month ("13") or an ISO date;
    for monthly bills only its day counts. The due day falls on/after the occurrence date."""
    du = str(flow.get("due") or "").strip()
    if not du:
        return None
    if flow.get("schedule") == "once" and not du.isdigit():
        return du
    day = int(du) if du.isdigit() else d(du).day
    o = d(occ)
    y, m = o.year, o.month
    if day < o.day:
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return date(y, m, min(day, _last_day(y, m))).isoformat()


def _events(state, start, end, scenario, paid):
    out = []
    for f in state["flows"]:
        for occ in occurrences(f, start, end):
            amt = float(effective_amount(f, occ, scenario))
            got = paid.get((f["id"], occ), 0.0)
            out.append({
                "id": f["id"], "name": f["name"], "category": f.get("category") or "Other",
                "direction": f["direction"], "date": occ, "amount": round(amt, 2),
                "paid": round(min(got, amt), 2), "remaining": round(max(amt - got, 0.0), 2),
                "due": due_for(f, occ), "confidence": f.get("confidence"), "spend": False,
            })
    for sp in state.get("spends", []):
        if start <= d(sp["date"]) <= end:
            amt = round(float(sp["amount"]), 2)
            out.append({
                "id": sp["id"], "name": sp.get("note") or "Spending", "category": sp.get("category") or "Spending",
                "direction": "expense", "date": sp["date"], "amount": amt, "paid": 0.0, "remaining": amt,
                "due": None, "confidence": "actual", "spend": True,
            })
    out.sort(key=lambda e: (e["date"], e["direction"] != "income", e["spend"], -e["amount"]))
    return out


def period_detail(state, on=None, offset=0, scenario=None):
    """Everything a period card needs. Mirrors the app: cash snapshot at asOf, then only
    activity after asOf counts; pending = amount - recorded payments."""
    scenario = scenario or state.get("scenario") or "average"
    today = on or date.today()
    pdays = _paydays(state)
    ps, pe, kind = period_bounds(today, pdays)
    if offset:
        ps = shift_period(ps, offset, pdays)
        ps, pe, kind = period_bounds(ps, pdays)
    asof = d(state["asOf"])
    paid = _paid_map(state)
    items = _events(state, ps, pe, scenario, paid)
    for e in items:
        e["before_snapshot"] = d(e["date"]) <= asof
        if e["spend"]:
            e["status"] = "spent"
        elif e["remaining"] <= 0.005:
            e["status"] = "paid"
        elif e["before_snapshot"]:
            e["status"] = "settled"          # already inside the cash snapshot
        elif e["paid"] > 0:
            e["status"] = "partial"
        else:
            e["status"] = "pending"
    cash = None
    if pe >= asof:
        cash = float(state["startingCash"])
        if ps > asof + timedelta(days=1):
            for e in _events(state, asof + timedelta(days=1), ps - timedelta(days=1), scenario, paid):
                cash += e["remaining"] if e["direction"] == "income" else -e["remaining"]
    counted = [e for e in items if not e["before_snapshot"]]
    inc = sum(e["remaining"] for e in counted if e["direction"] == "income")
    out = sum(e["remaining"] for e in counted if e["direction"] == "expense" and not e["spend"])
    spent = sum(e["remaining"] for e in counted if e["spend"])
    cats = {}
    for e in counted:
        if e["direction"] == "expense" and not e["spend"] and e["remaining"] > 0:
            cats[e["category"]] = cats.get(e["category"], 0.0) + e["remaining"]
    bills = [e for e in items if e["direction"] == "expense" and not e["spend"]]
    left = None if cash is None else round(cash + inc - out - spent, 2)
    in_period = ps <= today <= pe
    days_left = (pe - today).days + 1 if in_period else (pe - ps).days + 1
    per_day = round(left / days_left, 2) if left is not None and left > 0 and days_left > 0 else 0.0
    return {
        "period": {"start": ps.isoformat(), "end": pe.isoformat(), "kind": kind,
                   "label": period_label(ps, pe), "name": period_name(ps, kind, pdays)},
        "today": today.isoformat(), "asOf": state["asOf"], "stale_days": (today - asof).days,
        "scenario": scenario, "carry": None if cash is None else round(cash, 2),
        "income": round(inc, 2), "out": round(out, 2), "spent": round(spent, 2),
        "left": left, "days_left": days_left, "per_day": per_day,
        "spends": [e for e in counted if e["spend"]],
        "categories": sorted(({"name": k, "amount": round(v, 2)} for k, v in cats.items()),
                             key=lambda c: -c["amount"]),
        "items": items,
        "bills_total": len(bills),
        "bills_done": sum(1 for e in bills if e["status"] in ("paid", "settled")),
    }


def timeline(state, periods=6, on=None, scenario=None):
    rows = []
    for i in range(periods):
        p = period_detail(state, on=on, offset=i, scenario=scenario)
        rows.append({"label": p["period"]["label"], "start": p["period"]["start"], "end": p["period"]["end"],
                     "kind": p["period"]["kind"], "carry": p["carry"], "income": p["income"],
                     "out": p["out"], "spent": p["spent"], "net": round(p["income"] - p["out"] - p["spent"], 2),
                     "left": p["left"]})
    return rows


def upcoming_bills(state, days=14, on=None, scenario=None):
    """Unpaid bills from the snapshot up to today+days, with overdue flagged."""
    scenario = scenario or state.get("scenario") or "average"
    today = on or date.today()
    asof = d(state["asOf"])
    start = max(asof + timedelta(days=1), today - timedelta(days=45))
    evs = _events(state, start, today + timedelta(days=days), scenario, _paid_map(state))
    out = []
    for e in evs:
        if e["direction"] != "expense" or e["spend"] or e["remaining"] <= 0.005:
            continue
        when = d(e["due"]) if e.get("due") else d(e["date"])
        e["when"] = when.isoformat()
        e["days"] = (when - today).days
        if e["days"] < 0:
            # only a real due date can be "overdue"; a passed pay-period date just isn't marked paid yet
            e["state"] = "overdue" if e.get("due") else "unmarked"
        else:
            e["state"] = "today" if e["days"] == 0 else "soon"
        out.append(e)
    out.sort(key=lambda e: (e["when"], -e["remaining"]))
    return out


def load_looks(con):
    return {r["key"]: {k: r[k] for k in ("icon", "color") if r[k]} for r in con.execute("SELECT * FROM looks")}


def get_setting(con, key, default=None):
    row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(con, key, value):
    con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)))


def debt_status(state):
    """Debt balances as of now: the snapshot amount minus payments on linked bills made after it.
    A payment's explicit debt_reduction wins over its amount."""
    links = state.get("debtLinks") or {}
    out = []
    for b in state.get("balances", []):
        if b["kind"] != "debt":
            continue
        since = b.get("asOf") or "0000-00-00"
        paid = [p for p in state.get("payments", [])
                if links.get(p["flowId"]) == b["id"] and p["paidOn"] > since]
        cut = sum((p.get("debtReduction") or 0) or p["amount"] for p in paid)
        out.append({"id": b["id"], "name": b["name"], "snapshot": b["amount"], "asOf": b.get("asOf"),
                    "paid_since": round(cut, 2), "payments": len(paid),
                    "now": round(max(b["amount"] - cut, 0.0), 2),
                    "bills": sorted(f for f, bal in links.items() if bal == b["id"])})
    return sorted(out, key=lambda x: -x["now"])


def load_state(db=None):
    """Everything the engine and cards need: the web app's state plus CLI-only data."""
    con = connect()
    try:
        st = export_state(con)
        st["looks"] = load_looks(con)
        st["spends"] = [dict(r) for r in con.execute("SELECT * FROM spends ORDER BY date, id")]
        st["debtLinks"] = {r["flow_id"]: r["balance_id"] for r in con.execute("SELECT * FROM debt_links")}
        st["paydays"] = get_setting(con, "paydays", list(PAYDAYS))
        return st
    finally:
        con.close()


def _json_out(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


# ---------- commands ----------
def cmd_period(a):
    st = load_state()
    on = d(a.on) if a.on else None
    p = period_detail(st, on=on, offset=a.offset, scenario=a.scenario)
    if a.json:
        return _json_out(p)
    left = "n/a (before snapshot)" if p["left"] is None else f"{p['left']:,.2f}"
    print(f"{p['period']['label']}  ({p['period']['name']})  scenario={p['scenario']}  snapshot {p['asOf']}"
          + (f"  [{p['stale_days']}d old]" if p["stale_days"] > 3 else ""))
    print(f"brought forward {p['carry'] if p['carry'] is None else format(p['carry'], ',.2f')}"
          f"  + in {p['income']:,.2f}  - out {p['out']:,.2f}  = left {left}")
    for e in p["items"]:
        sign = "+" if e["direction"] == "income" else "-"
        print(f"  {e['date']}  {sign}{e['remaining']:>11,.2f}  {e['status']:<8} {e['name']}")


def cmd_timeline(a):
    rows = timeline(load_state(), periods=a.periods, on=d(a.on) if a.on else None, scenario=a.scenario)
    if a.json:
        return _json_out(rows)
    print(f"{'period':<18}{'in':>12}{'out':>12}{'net':>12}{'left':>14}")
    for r in rows:
        left = "n/a" if r["left"] is None else f"{r['left']:,.2f}"
        print(f"{r['label']:<18}{r['income']:>12,.2f}{r['out']:>12,.2f}{r['net']:>12,.2f}{left:>14}")


def cmd_upcoming(a):
    rows = upcoming_bills(load_state(), days=a.days, on=d(a.on) if a.on else None)
    if a.json:
        return _json_out(rows)
    for e in rows:
        print(f"{e['when']}  {e['state']:<8} {e['remaining']:>11,.2f}  {e['name']}")


def cmd_card(a):
    import cards  # local module next to this file
    res = cards.make(a.type, load_state(), a)
    print(res["caption"])
    print(f"MEDIA:{res['png']}")


def _look_key(st, target):
    """Accept a flow id, a category name, a balance id, or an explicit flow:/cat:/bal: key."""
    if re.match(r"^(flow|cat|bal):", target):
        return target
    if any(f["id"] == target for f in st["flows"]):
        return f"flow:{target}"
    cats = {(f.get("category") or "Other") for f in st["flows"]}
    hit = next((c for c in cats if c.lower() == target.lower()), None)
    if hit:
        return f"cat:{hit}"
    if any(b["id"] == target for b in st["balances"]):
        return f"bal:{target}"
    raise SystemExit(f"'{target}' is not a bill id, category or balance id (see `moneymap flows` / `balances`)")


def cmd_icon(a):
    import icons
    st = load_state()
    table = icons.assign(st)
    if a.action == "find":
        q = " ".join(a.args)
        if not q:
            raise SystemExit("usage: moneymap icon find <plain words>")
        owner = {}
        for k, v in table.items():
            owner.setdefault(v.get("icon"), []).append(k)
        for n in icons.search(q, k=a.k):
            print(f"{n:<28}{'used by ' + ', '.join(owner[n]) if n in owner else 'free'}")
        return
    if a.action == "list":
        for k in sorted(table, key=lambda k: (k.split(":")[0] != "cat", k)):
            v = table[k]
            print(f"{k:<44}{v.get('icon', ''):<24}{v.get('color', ''):<12}{'auto' if v.get('auto') else 'saved'}")
        return
    con = connect()
    if a.action == "auto":                       # freeze today's automatic picks so new bills never reshuffle them
        n = 0
        for k, v in table.items():
            if v.get("auto"):
                con.execute("INSERT INTO looks(key,icon,color) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET "
                            "icon=COALESCE(looks.icon,excluded.icon), color=COALESCE(looks.color,excluded.color)",
                            (k, v.get("icon"), v.get("color") if k.startswith("cat:") else None))
                n += 1
        con.commit(); con.close()
        return print(f"saved {n} automatic looks")
    if a.action == "set":
        if len(a.args) < 2 and not a.color:
            raise SystemExit("usage: moneymap icon set <bill-id|category|balance-id> <icon> [--color NAME]")
        key = _look_key(st, a.args[0])
        icon = a.args[1] if len(a.args) > 1 else None
        if icon:
            if not icons.exists(icon):
                raise SystemExit(f"no icon '{icon}'. Closest: {', '.join(icons.search(icon.replace('-', ' ')))}")
            kind = key.split(":")[0] + ":"
            clash = [k for k, v in table.items() if k.startswith(kind) and k != key and v.get("icon") == icon]
            if clash:
                alts = icons.search(icon.replace("-", " "), k=4,
                                    exclude={v.get("icon") for k, v in table.items() if k.startswith(kind)})
                raise SystemExit(f"'{icon}' is already used by {clash[0]}. Free alternatives: {', '.join(alts)}")
        if a.color:
            if a.color in icons.STATUS:
                raise SystemExit("red, green and amber are reserved for status (short / paid / due)")
            if a.color not in icons.PALETTE:
                raise SystemExit(f"colour must be one of: {', '.join(icons.PALETTE)}")
            if not key.startswith(("cat:", "bal:")):
                raise SystemExit("colour belongs to the category; set it on the category instead")
        con.execute("INSERT INTO looks(key,icon,color) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET "
                    "icon=COALESCE(excluded.icon,looks.icon), color=COALESCE(excluded.color,looks.color)",
                    (key, icon, a.color))
        con.commit(); con.close()
        return print(f"{key}: icon={icon or table.get(key, {}).get('icon')} colour={a.color or table.get(key, {}).get('color', '-')}")
    if a.action == "reset":
        key = _look_key(st, a.args[0])
        con.execute("DELETE FROM looks WHERE key=?", (key,)); con.commit(); con.close()
        return print(f"{key}: back to automatic")


def _today(a):
    return d(a.date) if getattr(a, "date", None) else date.today()


def cmd_cash(a):
    """Set the cash you actually have now. Everything dated on/before this day counts as already
    inside that number; only later activity is added or taken away."""
    st = load_state()
    when = _today(a)
    old_asof = d(st["asOf"])
    unpaid = [e for e in _events(st, old_asof + timedelta(days=1), when, st.get("scenario") or "average",
                                 _paid_map(st))
              if e["direction"] == "expense" and not e["spend"] and e["remaining"] > 0.005]
    con = connect()
    set_meta(con, asOf=when.isoformat(), startingCash=round(a.amount, 2))
    con.commit(); con.close()
    print(f"Cash set to {a.amount:,.2f} on {when.isoformat()} (was {st['startingCash']:,.2f} on {st['asOf']}).")
    if unpaid:
        print(f"{len(unpaid)} bill(s) dated up to today were not marked paid and are now treated as paid:")
        for e in unpaid[:12]:
            print(f"  {e['date']}  {e['remaining']:>10,.2f}  {e['name']}  [{e['id']}]")
        print("If one is still unpaid, tell the agent; it can move it with: moneymap override / flow-set")


def cmd_spend(a):
    st = load_state()
    when = _today(a)
    sid = "sp-" + uuid.uuid4().hex[:8]
    note = " ".join(a.note).strip() or None
    con = connect()
    con.execute("INSERT INTO spends(id,date,amount,category,note) VALUES(?,?,?,?,?)",
                (sid, when.isoformat(), round(a.amount, 2), a.category or "Spending", note))
    con.commit(); con.close()
    p = period_detail(load_state(), on=when)
    msg = f"Logged ₱{a.amount:,.2f}{' for ' + note if note else ''} ({sid})."
    if p["left"] is not None:
        if p["left"] < 0:
            msg += f" {p['period']['label']}: short by ₱{-p['left']:,.2f}."
        else:
            msg += (f" {p['period']['label']}: ₱{p['left']:,.2f} left, about ₱{p['per_day']:,.0f}/day "
                    f"for {p['days_left']} days.")
    if when <= d(st["asOf"]):
        msg += " (Dated on/before the cash snapshot, so it is already inside that cash.)"
    print(msg)


def cmd_spends(a):
    con = connect()
    since = (date.today() - timedelta(days=a.days)).isoformat()
    rows = list(con.execute("SELECT * FROM spends WHERE date>=? ORDER BY date, id", (since,)))
    con.close()
    if a.json:
        return _json_out([dict(r) for r in rows])
    for r in rows:
        print(f"{r['date']}  {r['amount']:>10,.2f}  {r['category'] or '':<12} {r['note'] or ''}  [{r['id']}]")
    print(f"{len(rows)} spends, {sum(r['amount'] for r in rows):,.2f} in the last {a.days} days")


def cmd_spend_rm(a):
    con = connect()
    n = con.execute("DELETE FROM spends WHERE id=?", (a.id,)).rowcount
    con.commit(); con.close()
    print(f"removed {a.id}" if n else f"no spend {a.id}")


def cmd_due(a):
    con = connect()
    if a.flow is None:
        rows = list(con.execute("SELECT id,name,day,date,due,amount FROM flows WHERE direction='expense' "
                                "AND (\"end\" IS NULL OR \"end\">=?) AND (schedule='monthly' OR date>=?) ORDER BY amount DESC",
                                (date.today().isoformat(), date.today().isoformat())))
        missing = [r for r in rows if not r["due"]]
        for r in missing:
            print(f"{r['id']:<20} {r['amount']:>10,.2f}  {r['name']}  (sits on {'day ' + str(r['day']) if r['day'] else r['date']})")
        print(f"{len(rows) - len(missing)}/{len(rows)} current bills have a real due date.")
        con.close()
        return
    v = a.value
    if not (v.isdigit() and 1 <= int(v) <= 31) and not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
        sys.exit("due must be a day of the month (1-31) or YYYY-MM-DD")
    n = con.execute("UPDATE flows SET due=? WHERE id=?", (v, a.flow)).rowcount
    con.commit(); con.close()
    print(f"{a.flow}: due {'every ' + ordinal(int(v)) if v.isdigit() else v}" if n else f"no bill {a.flow}")


def cmd_debt_link(a):
    con = connect()
    if a.balance is None:
        st = load_state()
        for x in debt_status(st):
            print(f"{x['id']:<22} now {x['now']:>11,.2f}  (snapshot {x['snapshot']:,.2f} on {x['asOf']}, "
                  f"-{x['paid_since']:,.2f} from {x['payments']} payment(s))  bills: {', '.join(x['bills']) or '-'}")
        con.close()
        return
    if a.balance == "none":
        con.execute("DELETE FROM debt_links WHERE flow_id=?", (a.flow,))
        print(f"{a.flow}: no longer lowers a debt")
    else:
        if not con.execute("SELECT 1 FROM balances WHERE id=? AND kind='debt'", (a.balance,)).fetchone():
            sys.exit(f"no debt balance {a.balance}")
        con.execute("INSERT OR REPLACE INTO debt_links(flow_id,balance_id) VALUES(?,?)", (a.flow, a.balance))
        print(f"{a.flow}: payments now lower {a.balance}")
    con.commit(); con.close()


def cmd_paydays(a):
    con = connect()
    if a.days:
        days = _paydays([int(x) for x in re.split(r"[ ,/]+", a.days.strip()) if x])
        set_setting(con, "paydays", days)
        con.commit()
        print("paydays: " + ", ".join(ordinal(x) for x in days))
    else:
        print("paydays: " + ", ".join(ordinal(x) for x in _paydays(get_setting(con, "paydays", list(PAYDAYS)))))
    con.close()


def cmd_setup(a):
    """First-run setup for a new person: paydays, take-home pay per payday, cash now."""
    con = connect()
    if con.execute("SELECT COUNT(*) FROM flows").fetchone()[0] and not a.force:
        sys.exit("this database already has data (use --force to add pay schedule anyway)")
    days = _paydays([int(x) for x in re.split(r"[ ,/]+", a.paydays.strip()) if x])
    pays = [float(x) for x in re.split(r"[ ,/]+", a.pay.strip()) if x]
    if len(pays) == 1:
        pays = pays * len(days)
    if len(pays) != len(days):
        sys.exit("give one take-home amount, or one per payday")
    today = date.today()
    start = today.replace(day=1).isoformat()
    set_setting(con, "paydays", days)
    set_meta(con, version=1, asOf=today.isoformat(), startingCash=round(a.cash, 2), scenario="average", horizon=3)
    for day, amt in zip(days, pays):
        con.execute(f'INSERT OR REPLACE INTO flows({",".join(FLOW_COLS)}) VALUES({",".join("?" * len(FLOW_COLS))})',
                    (f"pay-{day}", f"{ordinal(day)} payday", "income", "monthly", amt, None, day, None, start, None,
                     "Pay", "estimate", "Take-home pay from setup.", None, None))
    con.commit(); con.close()
    print(f"Set up: paid on the {', '.join(ordinal(x) for x in days)}; {', '.join(f'{x:,.2f}' for x in pays)} each; "
          f"cash now {a.cash:,.2f}. Next: add bills with flow-add.")


def cmd_backup(a):
    """Consistent copies of every Money Map database (yours and any bot users'), keeping the newest N."""
    root = os.path.dirname(os.path.abspath(DEFAULT_DB))
    dest = a.dest or os.path.normpath(os.path.join(root, "..", "backups"))
    os.makedirs(dest, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    dbs = [DEFAULT_DB] + [os.path.join(root, "users", f) for f in sorted(os.listdir(os.path.join(root, "users")))
                          if f.endswith(".db")] if os.path.isdir(os.path.join(root, "users")) else [DEFAULT_DB]
    made = []
    for src in dbs:
        if not os.path.exists(src):
            continue
        base = os.path.splitext(os.path.basename(src))[0]
        out = os.path.join(dest, f"{base}-{stamp}.db")
        s_con, d_con = sqlite3.connect(src), sqlite3.connect(out)
        s_con.backup(d_con)
        d_con.close(); s_con.close()
        made.append(out)
        olds = sorted(f for f in os.listdir(dest) if re.match(re.escape(base) + r"-\d{8}-\d{4}\.db$", f))
        for f in olds[:-a.keep]:
            os.remove(os.path.join(dest, f))
    print(f"backed up {len(made)} database(s) to {dest} (keeping {a.keep} each)")


def brief(state, today=None):
    """What is worth saying this morning. Returns (lines, card type) or ([], None) on a quiet day."""
    today = today or date.today()
    iso = today.isoformat()
    lines, card = [], None
    paid_today = [e for e in _events(state, today, today, state.get("scenario") or "average", _paid_map(state))
                  if e["direction"] == "income" and e["remaining"] > 0]
    if paid_today:
        lines.append(f"Payday today: {', '.join(e['name'] for e in paid_today)}.")
        card = "period"
    soon = [e for e in upcoming_bills(state, days=1, on=today) if e["state"] in ("today", "soon", "overdue")]
    if soon:
        tot = sum(e["remaining"] for e in soon)
        names = ", ".join(e["name"] for e in soon[:3]) + (f" +{len(soon) - 3} more" if len(soon) > 3 else "")
        lines.append(f"Due by tomorrow: {names} (₱{tot:,.2f}).")
        card = card or "bills"
    p = period_detail(state, on=today)
    if p["left"] is not None and p["left"] < 0 and (card or today.weekday() == 0):
        lines.append(f"Heads up: this period is short by ₱{-p['left']:,.2f}.")
        card = card or "period"
    stale = (today - d(state["asOf"])).days
    if stale >= 4:
        lines.append(f"Your cash figure is {stale} days old. Reply with what you have now, like \"cash 6200\".")
    if today.weekday() == 6:                                     # Sundays: one missing due date at a time
        miss = [f for f in state["flows"] if f["direction"] == "expense" and not f.get("due")
                and ((f["schedule"] == "monthly" and (not f.get("end") or f["end"] >= iso))
                     or (f["schedule"] == "once" and (f.get("date") or "") >= iso))]
        if miss:
            big = max(miss, key=lambda f: f["amount"])
            lines.append(f"Quick one: what day is {big['name']} actually due? ({len(miss)} bills have no due date yet.)")
    return lines, card


def cmd_brief(a):
    """Morning message for a scheduler: prints nothing on quiet days, else text + MEDIA:<card>."""
    st = load_state()
    today = d(a.on) if a.on else date.today()
    lines, card = brief(st, today)
    if not lines and not a.force:
        return
    out = []
    if lines:
        out.append("Good morning! " + " ".join(lines))
    if card or a.force:
        import types
        import cards
        args = types.SimpleNamespace(on=today.isoformat(), offset=0, scenario=None, periods=6, days=7, payment=None,
                                     amount=None, label="", date=None, html=False,
                                     out=os.path.join("/tmp", "moneymap", f"brief-{card or 'period'}.png"))
        res = cards.make(card or "period", st, args)
        out.append(res["caption"])
        out.append(f"MEDIA:{res['png']}")
    print("\n".join(out))


def cmd_init(a):
    con = connect(); init_db(con); con.close()
    print(f"initialised {os.path.abspath(DEFAULT_DB)}")


def cmd_seed(a):
    con = connect(); init_db(con); import_state(con, SEED); con.close()
    con = connect(); con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('paydays','[15, 30]')")
    con.execute("INSERT OR REPLACE INTO debt_links(flow_id,balance_id) VALUES('card-pay','card-balance')")
    con.commit(); con.close()
    print(f"seeded sample data ({len(SEED['flows'])} flows, {len(SEED['balances'])} balance, paydays 15/30)")


def cmd_import(a):
    con = connect(); init_db(con)
    data = sys.stdin.read() if a.file in (None, "-") else open(a.file).read()
    state = json.loads(data)
    import_state(con, state); con.close()
    print(f"imported {len(state.get('flows',[]))} flows, {len(state.get('balances',[]))} balances")


def cmd_export(a):
    con = connect(); init_db(con)
    out = json.dumps(export_state(con), indent=2, ensure_ascii=False)
    (open(a.file, "w").write(out) if a.file else print(out))
    if a.file: print(f"wrote {a.file}")
    con.close()


def cmd_status(a):
    con = connect()
    st = export_state(con)
    inc = sum(f["amount"] for f in st["flows"] if f["direction"]=="income" and f["schedule"]=="monthly")
    exp = sum(f["amount"] for f in st["flows"] if f["direction"]=="expense" and f["schedule"]=="monthly")
    ones = [f for f in st["flows"] if f["schedule"]=="once"]
    print(f"asOf                : {st['asOf']}")
    print(f"startingCash        : {st['startingCash']:,.2f}")
    print(f"scenario            : {st['scenario']}  horizon: {st['horizon']}mo")
    print(f"flows               : {len(st['flows'])}  (monthly income {inc:,.2f} / monthly expense {exp:,.2f}, net {inc-exp:,.2f})")
    print(f"one-time flows      : {len(ones)}")
    print(f"balances            : {len(st['balances'])}  (total debt {sum(b['amount'] for b in st['balances'] if b['kind']=='debt'):,.2f})")
    print(f"payments recorded   : {len(st.get('payments',[]))}")
    con.close()


def cmd_flows(a):
    con = connect()
    for r in con.execute("SELECT * FROM flows ORDER BY direction DESC, schedule, day, date"):
        when = f"day {r['day']}" if r['schedule']=='monthly' else r['date']
        print(f"{r['id']:<14} {r['direction']:<7} {r['schedule']:<7} {when:<10} {r['amount']:>12,.2f}  {r['name']}")
    con.close()


def cmd_bills(a):
    """Bills with their REAL due date (due), separate from the period they sit in."""
    con = connect()
    rows = list(con.execute("SELECT id,name,due,day,date,amount FROM flows "
                            "WHERE direction='expense' ORDER BY COALESCE(due,'9999'), amount DESC"))
    print(f"{'real due':<12}{'amount':>11}  {'bill':<40} sits in")
    for r in rows:
        per = f"day {r['day']}" if r['day'] else (r['date'] or '-')
        print(f"{r['due'] or '—':<12}{r['amount']:>11,.2f}  {r['name'][:40]:<40} {per}")
    missing = [r['id'] for r in rows if not r['due']]
    print(f"\n{len(rows)-len(missing)}/{len(rows)} have a real due date.")
    if missing:
        print("missing: " + ", ".join(missing))
        print("set with: moneymap flow-set <id> due=YYYY-MM-DD")
    con.close()


def cmd_flow_add(a):
    con = connect(); init_db(con)
    fid = a.id or ("flow-" + uuid.uuid4().hex[:8])
    con.execute(f'INSERT OR REPLACE INTO flows({",".join(FLOW_COLS)}) VALUES({",".join("?"*len(FLOW_COLS))})',
        (fid, a.name, a.direction, a.schedule, a.amount, a.low_amount, a.day, a.date,
         a.start or "2026-10-01", a.end, a.category, a.confidence, a.note, a.kind, a.due))
    con.commit(); con.close()
    print(f"added flow {fid}")


def cmd_flow_set(a):
    con = connect(); init_db(con)
    for pair in a.set:
        k, _, v = pair.partition("=")
        col = {"lowAmount":"low_amount","asOf":"as_of"}.get(k, k)
        if col not in FLOW_COLS: sys.exit(f"unknown field {k}")
        con.execute(f'UPDATE flows SET "{col}"=? WHERE id=?', (v, a.id))
    con.commit(); con.close()
    print(f"updated {a.id}: {' '.join(a.set)}")


def cmd_flow_rm(a):
    con = connect(); init_db(con)
    con.execute("DELETE FROM flows WHERE id=?", (a.id,)); con.commit(); con.close()
    print(f"removed {a.id}")


def cmd_balances(a):
    con = connect()
    for r in con.execute("SELECT * FROM balances ORDER BY kind, name"):
        print(f"{r['id']:<20} {r['kind']:<6} {r['amount']:>14,.2f}  asOf {r['as_of'] or '-':<12} {r['name']}")
    con.close()


def cmd_balance_add(a):
    con = connect(); init_db(con)
    bid = a.id or ("bal-" + uuid.uuid4().hex[:8])
    con.execute("INSERT OR REPLACE INTO balances(id,name,kind,amount,as_of,note) VALUES(?,?,?,?,?,?)",
                (bid, a.name, a.kind, a.amount, a.as_of, a.note))
    con.commit(); con.close(); print(f"added balance {bid}")


def cmd_balance_set(a):
    con = connect(); init_db(con)
    for pair in a.set:
        k, _, v = pair.partition("=")
        col = {"asOf":"as_of"}.get(k, k)
        if col not in ("name","kind","amount","as_of","note"): sys.exit(f"unknown field {k}")
        con.execute(f'UPDATE balances SET "{col}"=? WHERE id=?', (v, a.id))
    con.commit(); con.close(); print(f"updated {a.id}")


def cmd_payments(a):
    con = connect()
    for r in con.execute("SELECT * FROM payments ORDER BY paid_on"):
        print(f"{r['id']:<16} {r['flow_id']:<14} orig {r['original_date']}  paid {r['paid_on']}  {r['amount']:>10,.2f}  debt↓ {r['debt_reduction']:,.2f}")
    con.close()


def cmd_pay(a):
    """Record a bill payment. Like the web app, money paid on/after the cash snapshot date comes out
    of that cash (the bill leaves the pending list, so the cash has to drop instead).
    --no-deduct when the cash figure already includes it."""
    con = connect(); init_db(con)
    pid = a.id or ("pay-" + uuid.uuid4().hex[:8])
    paid_on = a.paid_on or a.original_date
    asof = get_meta(con, "asOf")
    # Only a bill that sits after the snapshot is still pending in the forecast; paying it must lower cash.
    # Bills dated on/before the snapshot are already inside that cash figure.
    deduct = 0.0 if a.no_deduct or (asof and (a.original_date <= asof or paid_on < asof)) else round(a.amount, 2)
    con.execute("INSERT OR REPLACE INTO payments(id,flow_id,original_date,paid_on,amount,debt_reduction,deducted) "
                "VALUES(?,?,?,?,?,?,?)", (pid, a.flow, a.original_date, paid_on, a.amount, a.debt_reduction, deduct))
    if deduct:
        set_meta(con, startingCash=round(float(get_meta(con, "startingCash", 0)) - deduct, 2))
    con.commit(); con.close()
    print(f"recorded payment {pid}" + (f"; cash now {float(get_meta(connect(), 'startingCash', 0)):,.2f}" if deduct else
                                       " (cash already included it)"))


def cmd_undo(a):
    con = connect(); init_db(con)
    row = con.execute("SELECT deducted FROM payments WHERE id=?", (a.id,)).fetchone()
    if not row:
        con.close()
        return print(f"no payment {a.id}")
    con.execute("DELETE FROM payments WHERE id=?", (a.id,))
    if row["deducted"]:
        set_meta(con, startingCash=round(float(get_meta(con, "startingCash", 0)) + row["deducted"], 2))
    con.commit(); con.close()
    print(f"undid payment {a.id}" + (f"; {row['deducted']:,.2f} back in cash" if row["deducted"] else ""))


def cmd_forecast(a):
    state, start, end, cash, rows = forecast(con := connect(), a.months, a.scenario, a.from_date)
    print(f"scenario={a.scenario}  startingCash={state['startingCash']:,.2f}  window {start} -> {end}")
    print(f"{'date':<12}{'dir':<8}{'amount':>12} {'cash after':>14}  name")
    for occ, direction, name, amt, cash in rows:
        print(f"{occ:<12}{direction:<8}{amt:>12,.2f} {cash:>14,.2f}  {name}")
    print(f"\nprojected cash end of window: {cash:,.2f}")
    con.close()


def cmd_override(a):
    """Pin a one-off actual amount for a flow on a specific date (keeps the estimate)."""
    con = connect(); init_db(con)
    if a.clear:
        con.execute("DELETE FROM overrides WHERE flow_id=? AND date=?", (a.flow, a.date))
        print(f"cleared override {a.flow} @ {a.date}")
    else:
        if a.amount is None:
            sys.exit("override needs --amount (or --clear)")
        con.execute("INSERT OR REPLACE INTO overrides(flow_id,date,amount) VALUES(?,?,?)", (a.flow, a.date, a.amount))
        print(f"override {a.flow} @ {a.date} = {a.amount:,.2f}")
    con.commit(); con.close()


def cmd_overrides(a):
    con = connect()
    rows = list(con.execute("SELECT * FROM overrides ORDER BY date"))
    for r in rows:
        print(f"{r['flow_id']:<14} {r['date']}  {r['amount']:>12,.2f}")
    if not rows:
        print("(no overrides)")
    con.close()


MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _period(occ):
    """Map a date to its pay period: A = 10th-24th, B = 25th-next 9th."""
    y, m, d = int(occ[:4]), int(occ[5:7]), int(occ[8:10])
    if 10 <= d <= 24:
        return (y, m, 0), f"{MONTHS[m]} {y}  10-24"
    if d >= 25:
        return (y, m, 1), f"{MONTHS[m]} {y}  25-09"
    py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
    return (py, pm, 1), f"{MONTHS[pm]} {py}  25-09"


def cmd_periods(a):
    """Per-pay-period rollup: in / out / net / end cash. The default view."""
    con = connect()
    state, start, end, cash, rows = forecast(con, a.months, a.scenario, a.from_date)
    con.close()
    groups, order = {}, []
    for occ, direction, name, amt, running in rows:
        k, label = _period(occ)
        if k not in groups:
            groups[k] = {"in": 0.0, "out": 0.0, "end": running, "label": label}
            order.append(k)
        g = groups[k]
        g["in" if direction == "income" else "out"] += amt
        g["end"] = running
    print(f"scenario={a.scenario}  start {state['startingCash']:,.2f}  window {start}..{end}")
    print(f"{'period':<16}{'in':>12}{'out':>12}{'net':>12}{'end cash':>14}")
    for k in sorted(order):
        g = groups[k]
        print(f"{g['label']:<16}{g['in']:>12,.2f}{g['out']:>12,.2f}{g['in']-g['out']:>12,.2f}{g['end']:>14,.2f}")
    print(f"\nend of window cash: {cash:,.2f}")


def cmd_sql(a):
    con = connect()
    cur = con.execute(a.query)
    if cur.description:
        cols = [c[0] for c in cur.description]
        print(" | ".join(cols))
        for r in cur.fetchall(): print(" | ".join(str(r[c]) for c in cols))
    else:
        con.commit(); print(f"{cur.rowcount} rows affected")
    con.close()


def build_parser():
    p = argparse.ArgumentParser(prog="moneymap", description="Money Map agent CLI (SQLite)")
    p.add_argument("--db", help="override DB path")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(fn=cmd_init)
    sub.add_parser("seed").set_defaults(fn=cmd_seed)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("flows").set_defaults(fn=cmd_flows)
    sub.add_parser("bills").set_defaults(fn=cmd_bills)
    sub.add_parser("balances").set_defaults(fn=cmd_balances)
    sub.add_parser("payments").set_defaults(fn=cmd_payments)

    ip = sub.add_parser("import"); ip.add_argument("file", nargs="?"); ip.set_defaults(fn=cmd_import)
    ex = sub.add_parser("export"); ex.add_argument("file", nargs="?"); ex.set_defaults(fn=cmd_export)

    fa = sub.add_parser("flow-add")
    fa.add_argument("--id"); fa.add_argument("--name", required=True)
    fa.add_argument("--direction", required=True, choices=["income","expense"])
    fa.add_argument("--schedule", required=True, choices=["monthly","once"])
    fa.add_argument("--amount", type=float, required=True); fa.add_argument("--low-amount", type=float, dest="low_amount")
    fa.add_argument("--day", type=int); fa.add_argument("--date"); fa.add_argument("--start"); fa.add_argument("--end")
    fa.add_argument("--category"); fa.add_argument("--confidence"); fa.add_argument("--note"); fa.add_argument("--kind")
    fa.add_argument("--due", help="real due date, e.g. 2026-10-30")
    fa.set_defaults(fn=cmd_flow_add)

    fs = sub.add_parser("flow-set"); fs.add_argument("id"); fs.add_argument("set", nargs="+"); fs.set_defaults(fn=cmd_flow_set)
    fr = sub.add_parser("flow-rm"); fr.add_argument("id"); fr.set_defaults(fn=cmd_flow_rm)

    ba = sub.add_parser("balance-add")
    ba.add_argument("--id"); ba.add_argument("--name", required=True)
    ba.add_argument("--kind", required=True, choices=["asset","debt"])
    ba.add_argument("--amount", type=float, required=True); ba.add_argument("--as-of", dest="as_of"); ba.add_argument("--note")
    ba.set_defaults(fn=cmd_balance_add)

    bs = sub.add_parser("balance-set"); bs.add_argument("id"); bs.add_argument("set", nargs="+"); bs.set_defaults(fn=cmd_balance_set)

    pa = sub.add_parser("pay")
    pa.add_argument("--id"); pa.add_argument("--flow", required=True)
    pa.add_argument("--original-date", dest="original_date", required=True)
    pa.add_argument("--paid-on", dest="paid_on"); pa.add_argument("--amount", type=float, required=True)
    pa.add_argument("--debt-reduction", dest="debt_reduction", type=float, default=0)
    pa.add_argument("--no-deduct", dest="no_deduct", action="store_true", help="cash snapshot already includes this payment")
    pa.set_defaults(fn=cmd_pay)
    pu = sub.add_parser("undo"); pu.add_argument("id"); pu.set_defaults(fn=cmd_undo)

    fo = sub.add_parser("forecast")
    fo.add_argument("--months", type=int, default=3)
    fo.add_argument("--scenario", choices=["average","low"], default="average")
    fo.add_argument("--from", dest="from_date"); fo.set_defaults(fn=cmd_forecast)

    pe = sub.add_parser("periods")
    pe.add_argument("--months", type=int, default=3)
    pe.add_argument("--scenario", choices=["average","low"], default="average")
    pe.add_argument("--from", dest="from_date"); pe.set_defaults(fn=cmd_periods)

    ov = sub.add_parser("override")
    ov.add_argument("--flow", required=True); ov.add_argument("--date", required=True)
    ov.add_argument("--amount", type=float); ov.add_argument("--clear", action="store_true")
    ov.set_defaults(fn=cmd_override)
    sub.add_parser("overrides").set_defaults(fn=cmd_overrides)

    sq = sub.add_parser("sql"); sq.add_argument("query"); sq.set_defaults(fn=cmd_sql)

    pd = sub.add_parser("period", help="one pay period in detail (default: the current one)")
    pd.add_argument("--offset", type=int, default=0, help="0 = current, 1 = next, -1 = previous")
    pd.add_argument("--on", help="treat this date as today (YYYY-MM-DD)")
    pd.add_argument("--scenario", choices=["average", "low"])
    pd.add_argument("--json", action="store_true"); pd.set_defaults(fn=cmd_period)

    tl = sub.add_parser("timeline", help="next N pay periods: in / out / net / left")
    tl.add_argument("--periods", type=int, default=6); tl.add_argument("--on")
    tl.add_argument("--scenario", choices=["average", "low"])
    tl.add_argument("--json", action="store_true"); tl.set_defaults(fn=cmd_timeline)

    ub = sub.add_parser("upcoming", help="unpaid bills due soon (overdue flagged)")
    ub.add_argument("--days", type=int, default=14); ub.add_argument("--on")
    ub.add_argument("--json", action="store_true"); ub.set_defaults(fn=cmd_upcoming)

    cd = sub.add_parser("card", help="render a PNG summary card and print MEDIA:<path>")
    cd.add_argument("type", choices=["period", "bills", "timeline", "receipt", "whatif", "debts", "icons"])
    cd.add_argument("--offset", type=int, default=0); cd.add_argument("--on")
    cd.add_argument("--scenario", choices=["average", "low"])
    cd.add_argument("--periods", type=int, default=6); cd.add_argument("--days", type=int, default=14)
    cd.add_argument("--payment", help="receipt: payment id (default: latest)")
    cd.add_argument("--amount", type=float, help="whatif: extra spend")
    cd.add_argument("--label", default="New expense", help="whatif: what it is")
    cd.add_argument("--date", help="whatif: when (default: today)")
    cd.add_argument("--out", help="PNG path (default /tmp/moneymap/<type>.png)")
    cd.add_argument("--html", action="store_true", help="also keep the HTML next to the PNG")
    cd.set_defaults(fn=cmd_card)

    ca = sub.add_parser("cash", help="set the cash you have right now")
    ca.add_argument("amount", type=float); ca.add_argument("--date", help="default today")
    ca.set_defaults(fn=cmd_cash)

    sp = sub.add_parser("spend", help="log day-to-day spending: moneymap spend 180 jeep and lunch")
    sp.add_argument("amount", type=float); sp.add_argument("note", nargs="*")
    sp.add_argument("--category", help="e.g. Food, Transport, Fun (default Spending)")
    sp.add_argument("--date", help="default today"); sp.set_defaults(fn=cmd_spend)
    sl = sub.add_parser("spends", help="recent spending")
    sl.add_argument("--days", type=int, default=14); sl.add_argument("--json", action="store_true")
    sl.set_defaults(fn=cmd_spends)
    sr = sub.add_parser("spend-rm", help="delete one logged spend"); sr.add_argument("id"); sr.set_defaults(fn=cmd_spend_rm)

    du = sub.add_parser("due", help="set a bill's real due day, or list bills missing one")
    du.add_argument("flow", nargs="?"); du.add_argument("value", nargs="?", help="day of month (1-31) or YYYY-MM-DD")
    du.set_defaults(fn=cmd_due)

    dl = sub.add_parser("debt-link", help="paying a bill lowers a debt; no args = live debt list")
    dl.add_argument("flow", nargs="?"); dl.add_argument("balance", nargs="?", help="debt balance id, or 'none'")
    dl.set_defaults(fn=cmd_debt_link)

    py = sub.add_parser("paydays", help="show or set paydays, e.g. moneymap paydays 15,30")
    py.add_argument("days", nargs="?"); py.set_defaults(fn=cmd_paydays)

    su = sub.add_parser("setup", help="first-run setup for a new person")
    su.add_argument("--paydays", required=True, help="e.g. 15,30 or 25")
    su.add_argument("--pay", required=True, help="take-home per payday, e.g. 18000 or 18000,16500")
    su.add_argument("--cash", type=float, required=True, help="cash on hand now")
    su.add_argument("--force", action="store_true"); su.set_defaults(fn=cmd_setup)

    bk = sub.add_parser("backup", help="copy every database to backups/ (keeps newest N)")
    bk.add_argument("--keep", type=int, default=14); bk.add_argument("--dest")
    bk.set_defaults(fn=cmd_backup)

    br = sub.add_parser("brief", help="morning message for a scheduler (silent on quiet days)")
    br.add_argument("--on"); br.add_argument("--force", action="store_true", help="always send the period card")
    br.set_defaults(fn=cmd_brief)

    ic = sub.add_parser("icon", help="card icons: find / set / reset / list / auto")
    ic.add_argument("action", choices=["find", "set", "reset", "list", "auto"])
    ic.add_argument("args", nargs="*", help="find: plain words · set: <bill-id|category|balance-id> <icon>")
    ic.add_argument("--color", help="set: category colour name (see icons.PALETTE)")
    ic.add_argument("-k", type=int, default=6, help="find: how many results")
    ic.set_defaults(fn=cmd_icon)
    return p


def main():
    global DEFAULT_DB
    args = build_parser().parse_args()
    if getattr(args, "db", None):
        DEFAULT_DB = args.db
    args.fn(args)


if __name__ == "__main__":
    main()
