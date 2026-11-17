"""Per-person storage for the public Money Map bot and web app.

Every person gets their own SQLite file (data/users/<telegram chat id>.db); nobody shares a database
with anyone else, and the owner's own data/money-map.db is never reachable from here.

  invites   one-time codes the owner hands out (`python3 tools/bot.py invite`)
  registry  who joined, when, with which code, and today's message count (cost guard)
  sessions  web logins: the bot sends a one-time link (10 min), which becomes a 30-day cookie.
            Only SHA-256 hashes of tokens are stored.
"""
import hashlib
import json
import os
import re
import secrets
import threading
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
USERS = os.environ.get("MONEYMAP_USERS", os.path.normpath(os.path.join(HERE, "..", "data", "users")))
_LOCK = threading.Lock()
LINK_TTL = 10 * 60
SESSION_TTL = 30 * 24 * 3600


def _path(name):
    os.makedirs(USERS, mode=0o700, exist_ok=True)
    return os.path.join(USERS, name)


def _read(name, default):
    try:
        with open(_path(name), encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write(name, data):
    tmp = _path(name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
    os.chmod(tmp, 0o600)
    os.replace(tmp, _path(name))


def _h(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _cid(chat_id):
    cid = str(chat_id)
    if not re.fullmatch(r"-?\d{1,20}", cid):
        raise ValueError("bad chat id")
    return cid


def db_path(chat_id):
    return _path(f"{_cid(chat_id)}.db")


# ---------------------------------------------------------------- invites and registry
def new_invites(n=1, note=""):
    with _LOCK:
        inv = _read("invites.json", {})
        codes = []
        for _ in range(n):
            code = "MM-" + secrets.token_hex(3).upper()
            inv[code] = {"created": int(time.time()), "note": note, "used_by": None}
            codes.append(code)
        _write("invites.json", inv)
    return codes


def is_member(chat_id):
    return _cid(chat_id) in _read("registry.json", {})


def redeem(chat_id, code, name=""):
    """True if this chat is (now) a member."""
    cid = _cid(chat_id)
    with _LOCK:
        reg = _read("registry.json", {})
        if cid in reg:
            return True
        inv = _read("invites.json", {})
        code = (code or "").strip().upper()
        if code not in inv or inv[code]["used_by"]:
            return False
        inv[code]["used_by"] = cid
        reg[cid] = {"name": name, "joined": int(time.time()), "invite": code, "day": "", "count": 0}
        _write("invites.json", inv)
        _write("registry.json", reg)
    return True


def members():
    return _read("registry.json", {})


def take_quota(chat_id, limit):
    """Count one AI call for today; False once the daily limit is used up."""
    cid = _cid(chat_id)
    with _LOCK:
        reg = _read("registry.json", {})
        u = reg.get(cid)
        if not u:
            return False
        today = date.today().isoformat()
        if u.get("day") != today:
            u["day"], u["count"] = today, 0
        if u["count"] >= limit:
            return False
        u["count"] += 1
        _write("registry.json", reg)
    return True


# ---------------------------------------------------------------- web sessions
def _prune(ses):
    now = time.time()
    return {k: v for k, v in ses.items() if v["exp"] > now}


def login_link_token(chat_id):
    """One-time token for a /login?t=... link, valid for 10 minutes."""
    tok = secrets.token_urlsafe(24)
    with _LOCK:
        ses = _prune(_read("sessions.json", {}))
        ses[_h(tok)] = {"chat": _cid(chat_id), "kind": "link", "exp": time.time() + LINK_TTL}
        _write("sessions.json", ses)
    return tok


def exchange(link_token):
    """Spend a one-time link token; returns (session token, chat id) or (None, None)."""
    with _LOCK:
        ses = _prune(_read("sessions.json", {}))
        rec = ses.pop(_h(link_token or ""), None)
        if not rec or rec["kind"] != "link":
            _write("sessions.json", ses)
            return None, None
        tok = secrets.token_urlsafe(32)
        ses[_h(tok)] = {"chat": rec["chat"], "kind": "session", "exp": time.time() + SESSION_TTL}
        _write("sessions.json", ses)
    return tok, rec["chat"]


def session_chat(session_token):
    if not session_token:
        return None
    rec = _read("sessions.json", {}).get(_h(session_token))
    if rec and rec["kind"] == "session" and rec["exp"] > time.time():
        return rec["chat"]
    return None


def logout(session_token):
    with _LOCK:
        ses = _prune(_read("sessions.json", {}))
        ses.pop(_h(session_token or ""), None)
        _write("sessions.json", ses)
