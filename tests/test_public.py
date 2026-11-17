"""Multi-user pieces: invites, quotas, web sessions, bot tool guards, public server isolation.
Run: python3 -m unittest discover -s tests (from the repo root)."""
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import users  # noqa: E402
import moneymap as mm  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = users.USERS
        users.USERS = self.tmp

    def tearDown(self):
        users.USERS = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)


class Invites(Base):
    def test_code_works_once(self):
        code = users.new_invites(1)[0]
        self.assertFalse(users.is_member(111))
        self.assertTrue(users.redeem(111, code.lower(), "Ana"))
        self.assertTrue(users.is_member(111))
        self.assertFalse(users.redeem(222, code))           # already used
        self.assertFalse(users.redeem(333, "MM-NOPE"))

    def test_daily_quota(self):
        users.redeem(111, users.new_invites(1)[0])
        self.assertTrue(all(users.take_quota(111, 3) for _ in range(3)))
        self.assertFalse(users.take_quota(111, 3))
        self.assertFalse(users.take_quota(999, 3))            # not a member

    def test_chat_id_cannot_escape_folder(self):
        with self.assertRaises(ValueError):
            users.db_path("../../money-map")


class Sessions(Base):
    def test_link_is_one_time_and_maps_to_its_chat(self):
        link = users.login_link_token(111)
        sess, chat = users.exchange(link)
        self.assertEqual(chat, "111")
        self.assertEqual(users.session_chat(sess), "111")
        self.assertEqual(users.exchange(link), (None, None))   # spent
        self.assertIsNone(users.session_chat(link))           # a link token is not a session
        users.logout(sess)
        self.assertIsNone(users.session_chat(sess))


class BotTools(Base):
    def setUp(self):
        super().setUp()
        import bot
        self.bot = bot
        self.calls = []
        self._run = bot.run_mm
        bot.run_mm = lambda chat, *argv: self.calls.append((chat, argv)) or "ok"

    def tearDown(self):
        self.bot.run_mm = self._run
        super().tearDown()

    def test_tools_build_fixed_commands(self):
        T = self.bot.TOOLS
        T["log_spend"][0](5, {"amount": 180, "note": "jeep\nand lunch", "category": "Transport"})
        self.assertEqual(self.calls[-1], (5, ("spend", 180.0, "jeep and lunch", "--category", "Transport")))
        T["set_cash"][0](5, {"amount": "6200.5"})
        self.assertEqual(self.calls[-1][1], ("cash", 6200.5))
        T["add_bill"][0](5, {"name": "Rent", "amount": 9000, "repeats": "monthly", "day": 5, "category": "Household"})
        argv = self.calls[-1][1]
        self.assertEqual(argv[:6], ("flow-add", "--name", "Rent", "--direction", "expense", "--schedule"))

    def test_bad_ids_and_dates_are_refused(self):
        T = self.bot.TOOLS
        with self.assertRaises(ValueError):
            T["remove_bill"][0](5, {"bill_id": "x; rm -rf ~"})
        with self.assertRaises(ValueError):
            T["mark_paid"][0](5, {"bill_id": "rent", "bill_date": "tomorrow", "amount": 1})
        with self.assertRaises(ValueError):
            T["set_cash"][0](5, {"amount": 1e12})

    def test_real_run_uses_the_persons_own_db(self):
        self.bot.run_mm = self._run
        out = self.bot.run_mm(42, "setup", "--paydays", "15,30", "--pay", "18000", "--cash", "5000")
        self.assertIn("Set up", out)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "42.db")))
        self.assertIn("paydays: 15th, 30th", self.bot.run_mm(42, "paydays"))


class PublicServer(Base):
    def setUp(self):
        super().setUp()
        import server
        self.server = server
        server.PUBLIC = True
        for chat, cash in ((1, 1111), (2, 2222)):
            con = mm.connect(users.db_path(chat))
            mm.set_meta(con, version=1, asOf="2026-11-01", startingCash=cash, scenario="average", horizon=3)
            con.commit(); con.close()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.port = self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.server.PUBLIC = False
        super().tearDown()

    def get(self, path, cookie=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", path, headers={"Cookie": cookie} if cookie else {})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, dict(r.getheaders()), body

    def test_no_session_no_data(self):
        self.assertEqual(self.get("/api/state")[0], 401)
        self.assertEqual(self.get("/")[0], 401)

    def test_login_sees_only_own_db(self):
        code, headers, _ = self.get("/login?t=" + users.login_link_token(2))
        self.assertEqual(code, 302)
        cookie = headers["Set-Cookie"].split(";")[0]
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        status, _, body = self.get("/api/state", cookie)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["startingCash"], 2222)
        self.assertEqual(self.get("/login?t=" + "x" * 30)[0], 403)


if __name__ == "__main__":
    unittest.main()
