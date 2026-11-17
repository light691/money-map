"""Icons and identity colours for Money Map cards.

Icons come from Phosphor (MIT, vendor/phosphor, ~1,400 icons, brand logos removed).
The agent never draws or invents icons: it describes the thing in words, `search()` ranks
real icon names by name + tags (+ a few PH-specific synonyms), and the pick is stored in the
`looks` table. Colours are handed out by the app from PALETTE; the status colours
(red / green / amber) are reserved for short / paid / due and never identify a category.

Identity rules
  * a bill (flow) gets its own icon; icons are unique among flows and among categories
  * a bill takes its category's colour, so colour groups and the icon tells items apart
  * status changes weight/opacity (duotone = open, regular + faded = paid), never colour

Rebuilding vendor/phosphor: `npm pack @phosphor-icons/core`, untar, then for each icon outside
the "brands" category write {n, t, c} to catalog.json and the inner SVG of the regular,
duotone and fill assets to <weight>.json.
"""
import json
import os
import re
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.normpath(os.path.join(HERE, "..", "vendor", "phosphor"))
FALLBACK = "dot-outline"

# name -> hex. Spread out in hue, all readable on the dark card, none of them status colours.
PALETTE = {
    "violet": "#8b5cf6", "blue": "#3b82f6", "pink": "#f472b6", "cyan": "#22d3ee",
    "sand": "#d6b48a", "orchid": "#d17cf5", "teal": "#2dd4bf", "slate": "#94a3b8", "periwinkle": "#8ea2ff",
}
STATUS = {"red": "#f87171", "green": "#4ade80", "amber": "#fbbf24"}

# Words people actually type here -> words Phosphor understands. Lower-case keys.
SYNONYMS = {
    "meralco": "lightning", "electric": "lightning", "electricity": "lightning", "kuryente": "lightning",
    "maynilad": "drop", "water": "drop", "tubig": "drop",
    "pldt": "wifi-high", "converge": "wifi-high", "globe": "wifi-high", "internet": "wifi-high",
    "wifi": "wifi-high", "fiber": "wifi-high", "load": "sim-card", "smart": "sim-card",
    "netflix": "television-simple", "youtube": "television-simple", "hbo": "television-simple",
    "spotify": "music-notes", "codex": "robot", "chatgpt": "robot", "claude": "robot", "openai": "robot",
    "gcash": "wallet", "maya": "wallet", "sss": "shield-check", "gsis": "shield-check",
    "philhealth": "first-aid-kit", "pagibig": "house-line", "pag-ibig": "house-line",
    "rent": "house", "upa": "house", "household": "house", "bahay": "house",
    "jeep": "bus", "jeepney": "bus", "fare": "bus", "transport": "bus", "commute": "bus",
    "grab": "car", "angkas": "motorcycle", "gasolina": "gas-pump", "gas": "gas-pump",
    "chicken": "bird", "manok": "bird", "feed": "bird", "egg": "egg", "animals": "paw-print",
    "food": "fork-knife", "pagkain": "fork-knife", "groceries": "shopping-cart", "grocery": "shopping-cart",
    "palengke": "shopping-cart", "tuition": "graduation-cap", "school": "graduation-cap",
    "medicine": "pill", "gamot": "pill", "parents": "users", "allowance": "hand-heart",
    "brother": "handshake", "kuya": "handshake", "ate": "handshake", "utang": "handshake",
    "personal debt": "handshake", "metrobank": "credit-card", "bpi": "credit-card", "bdo": "credit-card",
    "card": "credit-card", "macbook": "laptop", "laptop": "laptop", "vape": "cigarette",
    "debt": "hand-coins", "loan": "hand-coins", "payday": "money", "salary": "money", "sweldo": "money",
    "pay": "money", "13th": "gift", "bonus": "gift", "savings": "piggy-bank", "ipon": "piggy-bank",
    "subscriptions": "repeat", "utilities": "plug", "health": "heartbeat", "lending": "hand-arrow-up",
    "income": "coins", "personal": "user", "other debt": "invoice", "ticket": "ticket", "gift": "gift",
    "spending": "shopping-bag", "transport": "bus", "fun": "confetti", "shopping": "shopping-bag",
    "mom": "heart", "mama": "heart", "nanay": "heart", "dad": "user", "papa": "user", "tatay": "user",
    "ceiling": "hammer", "repair": "hammer", "survey": "clipboard-text", "meds": "pill", "phone": "device-mobile",
}

_cache = {}


def _load(name):
    if name not in _cache:
        with open(os.path.join(VENDOR, name), encoding="utf-8") as fh:
            _cache[name] = json.load(fh)
    return _cache[name]


def catalog():
    return _load("catalog.json")


def names():
    if "_names" not in _cache:
        _cache["_names"] = {i["n"] for i in catalog()}
    return _cache["_names"]


def exists(name):
    return name in names()


NOISE = {"and", "the", "of", "for", "to", "from", "placeholder", "payment", "repayment", "repay", "future",
         "catch-up", "catchup", "last", "rest", "extra", "defer", "deferred", "minimum", "min", "balance",
         "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
         "january", "february", "march", "april", "june", "july", "august", "september", "october",
         "november", "december", "back", "1st", "2nd", "10th", "25th", "plan", "monthly"}
MIN_SCORE = 30          # below this a match is a guess; use the category icon instead


def _words(text):
    return [w for w in re.split(r"[^a-z0-9\-]+", (text or "").lower())
            if w and w not in NOISE and not w.isdigit()]


def scored(query, exclude=()):
    """[(icon, score)] best first for a plain-words description."""
    q = (query or "").lower()
    words = _words(q)
    direct = [SYNONYMS[s] for s in SYNONYMS if " " in s and s in q]          # multi-word synonyms
    direct += [SYNONYMS[w] for w in words if w in SYNONYMS]
    terms = set(words) | {p for d_ in direct for p in d_.split("-")}
    scores = {}
    for i in catalog():
        n = i["n"]
        if n in exclude:
            continue
        parts = n.split("-")
        s = 0.0
        if n in direct:
            s += max(120 - 15 * direct.index(n), 60)                           # synonym hit, earlier word = stronger
        if n in words:
            s += 100
        s += sum(30 for p in parts if p in terms)
        tags = [t.lower() for t in i["t"]]
        s += sum(18 for t in tags if t in terms)
        s += sum(5 for t in tags for w in terms if len(w) > 3 and w != t and w in t)
        if s:
            s -= 2 * (len(parts) - 1)                                           # prefer the plain base icon
            scores[n] = s
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def search(query, k=5, exclude=()):
    """Icon names for a plain-words description, best first."""
    return [n for n, _ in scored(query, exclude)[:k]]


def svg(name, weight="duotone", size=18, color="currentColor"):
    w = _load(f"{weight}.json")
    inner = w.get(name) or w.get(FALLBACK, "")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="{size}" height="{size}" '
            f'fill="{color}" aria-hidden="true">{inner}</svg>')


# ---------------------------------------------------------------- assignment
def _cat_order(state, today=None):
    """Categories in flow order, but those with bills still ahead first (they get the distinct colours)."""
    today = (today or date.today()).isoformat()
    seen, live = [], set()
    for f in state.get("flows", []):
        c = f.get("category") or "Other"
        if c not in seen:
            seen.append(c)
        if (f.get("schedule") == "monthly" and (not f.get("end") or f["end"] >= today)) or                 (f.get("schedule") == "once" and (f.get("date") or "") >= today):
            live.add(c)
    for sp in state.get("spends", []):
        c = sp.get("category") or "Spending"
        if c not in seen:
            seen.append(c)
        if (sp.get("date") or "") >= today[:8] + "01":       # spent this month = still active
            live.add(c)
    return [c for c in seen if c in live] + [c for c in seen if c not in live]


def bill_key(name):
    """Bills with the same plain name (Chicken feed on the 10th and the 25th) share one icon."""
    return " ".join(_words(re.sub(r"\(.*?\)", "", name or ""))) or (name or "").lower()


def assign(state, today=None):
    """Full, deterministic look table: {"flow:<id>"|"cat:<name>"|"bal:<id>": {"icon", "color", "auto"}}.
    Saved looks win. Automatic picks: categories and bills each get an unused icon when there is a
    confident match; same-name bills share one; weak matches fall back to the category icon."""
    saved = state.get("looks") or {}
    out = {k: dict(v, auto=False) for k, v in saved.items()}
    cats = _cat_order(state, today)

    used_c = {v.get("color") for k, v in out.items() if k.startswith("cat:") and v.get("color")}
    free = [c for c in PALETTE if c not in used_c] or list(PALETTE)
    n = 0
    for cat in cats:
        key = f"cat:{cat}"
        out.setdefault(key, {"auto": True})
        if not out[key].get("color"):
            out[key]["color"] = free[n % len(free)]
            n += 1

    used = {v["icon"] for k, v in out.items() if k.startswith("cat:") and v.get("icon")}
    for cat in cats:
        key = f"cat:{cat}"
        if not out[key].get("icon"):
            best = next(((i, sc) for i, sc in scored(cat, used) if sc >= MIN_SCORE), None)
            out[key]["icon"] = best[0] if best else "tag"
            used.add(out[key]["icon"])

    used = {v["icon"] for k, v in out.items() if k.startswith("flow:") and v.get("icon")}
    group_icon = {}
    for f in state.get("flows", []):
        key = f"flow:{f['id']}"
        out.setdefault(key, {"auto": True})
        if out[key].get("icon"):
            group_icon.setdefault(bill_key(f["name"]), out[key]["icon"])
            continue
        g = bill_key(f["name"])
        if g in group_icon:
            out[key]["icon"] = group_icon[g]
            continue
        best = next(((i, sc) for i, sc in scored(f["name"], used) if sc >= MIN_SCORE), None)
        if best:
            out[key]["icon"] = best[0]
            used.add(best[0])
        else:
            out[key]["icon"] = out[f"cat:{f.get('category') or 'Other'}"]["icon"]
        group_icon[g] = out[key]["icon"]

    used = {v["icon"] for k, v in out.items() if k.startswith("bal:") and v.get("icon")}
    pal = list(PALETTE)
    for i, b in enumerate(state.get("balances", [])):
        key = f"bal:{b['id']}"
        out.setdefault(key, {"auto": True})
        if not out[key].get("icon"):
            best = next(((ic, sc) for ic, sc in scored(b["name"], used) if sc >= MIN_SCORE), None)
            out[key]["icon"] = best[0] if best else "user-circle"
            if best:
                used.add(best[0])
        out[key].setdefault("color", pal[i % len(pal)])
    return out


def look(table, *, flow_id=None, category=None, balance_id=None):
    """(icon name, colour hex) for one row on a card."""
    cat = table.get(f"cat:{category or 'Other'}", {})
    color = PALETTE.get(cat.get("color"), PALETTE["slate"])
    if flow_id and f"flow:{flow_id}" in table:
        return table[f"flow:{flow_id}"]["icon"], color
    if balance_id and f"bal:{balance_id}" in table:
        own = table[f"bal:{balance_id}"]
        return own["icon"], PALETTE.get(own.get("color"), PALETTE["slate"])
    return cat.get("icon", FALLBACK), color


def category_color(table, category):
    return PALETTE.get(table.get(f"cat:{category or 'Other'}", {}).get("color"), PALETTE["slate"])
