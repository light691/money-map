#!/usr/bin/env python3
"""Money Map backend — serves dist/ AND persists app state to SQLite.

Endpoints:
  GET  /api/state   -> current state JSON (from SQLite) + X-MM-Rev header
  POST /api/state   -> replace state IF the client is not stale (X-MM-Rev match)
  GET  /api/sync.js -> client shim: boots localStorage from the API and
                       mirrors every save back to the API (app.js untouched)
  GET  /*           -> static files from dist/ (index.html gets the shim injected)

Staleness guard: X-MM-Rev is a hash of the current state. A client loads it at
boot and echoes it on save. If the state changed meanwhile (another client, or
the `moneymap` CLI), the POST is rejected 409 so a stale browser can never
clobber newer data.

Auth: HTTP Basic from ../data/.auth.json (or MONEYMAP_AUTH). No file => open.
Binding: `server.py [port] [host1,host2,...]` (default 127.0.0.1)

Public mode (`server.py 8100 127.0.0.1 --public`, or MONEYMAP_MODE=public): for bot users only.
Nobody gets in without a one-time link from the bot's /web command (GET /login?t=...), which turns
into a 30-day HttpOnly cookie. Each session sees only data/users/<chat id>.db; the owner's
database is never opened in this mode.
"""
import base64
import hashlib
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.normpath(os.path.join(HERE, "..", "dist"))
sys.path.insert(0, HERE)
import moneymap  # noqa: E402
import users  # noqa: E402

PUBLIC = "--public" in sys.argv or os.environ.get("MONEYMAP_MODE") == "public"
COOKIE = "mm_s"
SECURE = os.environ.get("MONEYMAP_PUBLIC_URL", "").startswith("https://")

LOCK = threading.Lock()
KEY = "money-map-v1"

AUTH_FILE = os.environ.get("MONEYMAP_AUTH", os.path.normpath(os.path.join(HERE, "..", "data", ".auth.json")))
AUTH = None
if os.path.exists(AUTH_FILE):
    try:
        with open(AUTH_FILE) as _f:
            AUTH = json.load(_f)
    except Exception:  # noqa: BLE001
        AUTH = None

SYNC_JS = """(function () {
  var KEY = 'money-map-v1';
  var REV = null;
  try {
    var x = new XMLHttpRequest();
    x.open('GET', '/api/state', false);           // synchronous boot fetch
    x.send();
    if (x.status === 200 && x.responseText) {
      REV = x.getResponseHeader('X-MM-Rev');
      localStorage.setItem(KEY, x.responseText);
    }
  } catch (e) { console.warn('moneymap: boot sync failed', e); }
  var _set = localStorage.setItem.bind(localStorage);
  localStorage.setItem = function (k, v) {
    _set(k, v);
    if (k !== KEY) return;
    try {
      var r = new XMLHttpRequest();
      r.open('POST', '/api/state', true);
      r.setRequestHeader('Content-Type', 'application/json');
      if (REV) r.setRequestHeader('X-MM-Rev', REV);
      r.onload = function () {
        if (r.status === 409) {
          console.warn('moneymap: save REJECTED - data changed elsewhere. Reload.');
          document.title = '\\u26a0 RELOAD \\u2014 out of sync';
        } else if (r.status === 200) {
          var nr = r.getResponseHeader('X-MM-Rev'); if (nr) REV = nr;
        }
      };
      r.send(v);
    } catch (e) { console.warn('moneymap: save sync failed', e); }
  };
})();
"""


def state_rev(state):
    return hashlib.sha256(
        json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]


def db_state(db=None):
    with LOCK:
        con = moneymap.connect(db)
        moneymap.init_db(con)
        data = moneymap.export_state(con)
        con.close()
    return data


def db_replace(state, db=None):
    with LOCK:
        con = moneymap.connect(db)
        moneymap.init_db(con)
        moneymap.import_state(con, state)
        con.close()


NO_SESSION = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Money Map</title><body style="font:16px system-ui;background:#08080c;color:#eee;display:grid;place-items:center;
height:100vh;margin:0"><div style="max-width:320px;text-align:center"><h2>Money Map</h2>
<p>Open this page from the Money Map bot: send <b>/web</b> there and tap the link.</p></div></body>"""


def injected_index():
    with open(os.path.join(DIST, "index.html"), encoding="utf-8") as f:
        html = f.read()
    marker = '<script src="./app.js"'
    shim = '<script src="/api/sync.js"></script>\n  '
    if "/api/sync.js" not in html and marker in html:
        html = html.replace(marker, shim + marker, 1)
    return html


def _consteq(a, b):
    if len(a) != len(b):
        return False
    r = 0
    for x, y in zip(a.encode(), b.encode()):
        r |= x ^ y
    return r == 0


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=DIST, **k)

    def _cookie(self):
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return None

    def _user_db(self):
        """Public mode: the caller's own database, or None (no valid session)."""
        chat = users.session_chat(self._cookie())
        return users.db_path(chat) if chat else None

    def _public_get(self, p):
        q = urlparse(self.path).query
        if p == "/login":
            tok = dict(x.partition("=")[::2] for x in q.split("&") if x).get("t", "")
            session, chat = users.exchange(tok)
            if not session:
                return self._send(NO_SESSION.replace("Open this page", "That link has expired or was used. Open this page"),
                                  "text/html; charset=utf-8", 403)
            flags = f"; Path=/; Max-Age={users.SESSION_TTL}; HttpOnly; SameSite=Lax" + ("; Secure" if SECURE else "")
            return self._send("", "text/plain", 302, {"Location": "/", "Set-Cookie": f"{COOKIE}={session}{flags}"})
        if p == "/logout":
            users.logout(self._cookie())
            return self._send("", "text/plain", 302, {"Location": "/", "Set-Cookie": f"{COOKIE}=; Path=/; Max-Age=0"})
        db = self._user_db()
        if p == "/api/health":
            return self._json({"ok": True, "mode": "public", "signed_in": bool(db)})
        if not db:
            if p.startswith("/api/"):
                return self._json({"ok": False, "error": "not signed in"}, 401)
            if p in ("/", "/index.html"):
                return self._send(NO_SESSION, "text/html; charset=utf-8", 401)
            return SimpleHTTPRequestHandler.do_GET(self)          # static assets only
        if p == "/api/state":
            data = db_state(db)
            return self._json(data, 200, {"X-MM-Rev": state_rev(data)})
        if p == "/api/sync.js":
            return self._send(SYNC_JS, "application/javascript")
        if p in ("/", "/index.html"):
            return self._send(injected_index(), "text/html; charset=utf-8")
        return SimpleHTTPRequestHandler.do_GET(self)

    def _authorized(self):
        if not AUTH:
            return True
        h = self.headers.get("Authorization", "")
        if not h.startswith("Basic "):
            return False
        try:
            u, p = base64.b64decode(h[6:]).decode("utf-8").split(":", 1)
        except Exception:  # noqa: BLE001
            return False
        return _consteq(u, AUTH.get("user", "")) and _consteq(p, AUTH.get("password", ""))

    def _deny(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Money Map", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send(self, body, ctype, code=200, extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200, extra=None):
        self._send(json.dumps(obj, ensure_ascii=False), "application/json", code, extra)

    def do_GET(self):
        p = urlparse(self.path).path
        if PUBLIC:
            return self._public_get(p)
        if not self._authorized():
            return self._deny()
        if p == "/api/state":
            data = db_state()
            return self._json(data, 200, {"X-MM-Rev": state_rev(data)})
        if p == "/api/sync.js":
            return self._send(SYNC_JS, "application/javascript")
        if p == "/api/health":
            return self._json({"ok": True, "auth": bool(AUTH), "rev": state_rev(db_state()),
                               "db": os.path.abspath(moneymap.DEFAULT_DB)})
        if p in ("/", "/index.html"):
            return self._send(injected_index(), "text/html; charset=utf-8")
        return super().do_GET()

    def do_POST(self):
        db = None
        if PUBLIC:
            db = self._user_db()
            if not db:
                return self._json({"ok": False, "error": "not signed in"}, 401)
        elif not self._authorized():
            return self._deny()
        p = urlparse(self.path).path
        if p != "/api/state":
            return self.send_error(404)
        cur = state_rev(db_state(db))
        client = self.headers.get("X-MM-Rev")
        if client != cur:
            return self._json({"ok": False, "error": "stale", "rev": cur}, 409, {"X-MM-Rev": cur})
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        try:
            state = json.loads(raw)
            db_replace(state, db)
        except Exception as e:  # noqa: BLE001
            return self._json({"ok": False, "error": str(e)}, 400)
        return self._json({"ok": True, "flows": len(state.get("flows", []))}, 200,
                          {"X-MM-Rev": state_rev(state)})

    def log_message(self, fmt, *args):
        sys.stderr.write("[money-map] %s\n" % (fmt % args))
        sys.stderr.flush()


def main():
    argv = [x for x in sys.argv[1:] if x != "--public"]
    port = int(argv[0]) if argv else 8000
    raw_hosts = argv[1] if len(argv) > 1 else os.environ.get("MONEYMAP_HOST", "127.0.0.1")
    hosts = [h.strip() for h in raw_hosts.split(",") if h.strip()]
    servers = []
    for h in hosts:
        try:
            servers.append((h, ThreadingHTTPServer((h, port), Handler)))
        except OSError as e:
            print(f"[money-map] cannot bind {h}:{port}: {e}", flush=True)
    if not servers:
        sys.exit(f"[money-map] no usable bind addresses from {raw_hosts!r}")
    for h, _ in servers:
        if PUBLIC:
            print(f"Money Map PUBLIC mode at http://{h}:{port}  (bot users only, sessions in {users.USERS})", flush=True)
        else:
            print(f"Money Map serving {DIST} at http://{h}:{port}  (auth={'on' if AUTH else 'OFF'}, "
                  f"db={os.path.abspath(moneymap.DEFAULT_DB)})", flush=True)
    for _, srv in servers[1:]:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    servers[0][1].serve_forever()


if __name__ == "__main__":
    main()
