"""Engine + card tests. Run: python3 -m unittest discover -s tests -v   (from the repo root)"""
import os
import shutil
import sys
import tempfile
import types
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import moneymap as mm  # noqa: E402
import cards  # noqa: E402
import icons  # noqa: E402

STATE = {
    "version": 1, "asOf": "2026-11-09", "startingCash": 10000, "scenario": "average", "horizon": 3,
    "flows": [
        {"id": "pay-10", "name": "10th payday", "direction": "income", "schedule": "monthly",
         "amount": 40000, "lowAmount": 35000, "day": 10, "start": "2026-10-01", "category": "Pay"},
        {"id": "pay-25", "name": "25th payday", "direction": "income", "schedule": "monthly",
         "amount": 30000, "day": 25, "start": "2026-10-01", "category": "Pay"},
        {"id": "rent", "name": "Rent", "direction": "expense", "schedule": "monthly",
         "amount": 15000, "day": 10, "start": "2026-10-01", "category": "Household"},
        {"id": "net", "name": "Internet", "direction": "expense", "schedule": "monthly",
         "amount": 1700, "day": 13, "start": "2026-10-01", "category": "Utilities", "due": "2026-11-13"},
        {"id": "elec", "name": "Electricity", "direction": "expense", "schedule": "monthly",
         "amount": 5000, "day": 25, "start": "2026-10-01", "category": "Utilities"},
        {"id": "old", "name": "Before snapshot", "direction": "expense", "schedule": "once",
         "amount": 999, "date": "2026-11-05", "category": "Other"},
        {"id": "ends", "name": "Laptop", "direction": "expense", "schedule": "monthly",
         "amount": 8000, "day": 4, "start": "2026-10-01", "end": "2026-12-31", "category": "Other debt"},
    ],
    "balances": [{"id": "card", "name": "Card", "kind": "debt", "amount": 100000}],
    "payments": [{"id": "p1", "flowId": "rent", "originalDate": "2026-11-10", "paidOn": "2026-11-11",
                  "amount": 5000, "debtReduction": 0}],
}


class PeriodBounds(unittest.TestCase):
    def test_first_period(self):
        self.assertEqual(mm.period_bounds(date(2026, 11, 17)), (date(2026, 11, 10), date(2026, 11, 24), 1))

    def test_second_period_same_month(self):
        self.assertEqual(mm.period_bounds(date(2026, 11, 25)), (date(2026, 11, 25), date(2026, 12, 9), 2))

    def test_second_period_early_days(self):
        self.assertEqual(mm.period_bounds(date(2026, 12, 3)), (date(2026, 11, 25), date(2026, 12, 9), 2))

    def test_year_rollover(self):
        self.assertEqual(mm.period_bounds(date(2027, 1, 5)), (date(2026, 12, 25), date(2027, 1, 9), 2))
        self.assertEqual(mm.shift_period(date(2026, 12, 25), 1), date(2027, 1, 10))
        self.assertEqual(mm.shift_period(date(2027, 1, 10), -1), date(2026, 12, 25))


class PeriodDetail(unittest.TestCase):
    def setUp(self):
        self.p = mm.period_detail(STATE, on=date(2026, 11, 17))

    def test_numbers(self):
        p = self.p
        self.assertEqual(p["period"]["label"], "Nov 10–24")
        self.assertEqual(p["carry"], 10000)                 # nothing between snapshot and Nov 10
        self.assertEqual(p["income"], 40000)
        self.assertEqual(p["out"], 10000 + 1700)            # rent partly paid: 15000 - 5000
        self.assertEqual(p["left"], 10000 + 40000 - 11700)

    def test_statuses(self):
        by = {e["id"]: e for e in self.p["items"]}
        self.assertEqual(by["rent"]["status"], "partial")
        self.assertEqual(by["rent"]["remaining"], 10000)
        self.assertEqual(by["net"]["status"], "pending")
        self.assertEqual(self.p["stale_days"], 8)

    def test_snapshot_items_are_settled(self):
        p = mm.period_detail(STATE, on=date(2026, 11, 5))   # Oct 25 - Nov 9 period, contains asOf
        by = {e["id"]: e for e in p["items"]}
        self.assertEqual(by["old"]["status"], "settled")
        self.assertEqual(p["out"], 0)                       # everything in it is before/at the snapshot
        self.assertEqual(p["left"], 10000)

    def test_period_before_snapshot_has_no_cash(self):
        p = mm.period_detail(STATE, on=date(2026, 10, 15))
        self.assertIsNone(p["left"])

    def test_low_scenario(self):
        p = mm.period_detail(STATE, on=date(2026, 11, 17), scenario="low")
        self.assertEqual(p["income"], 35000)

    def test_flow_end_respected(self):
        jan = mm.period_detail(STATE, on=date(2027, 1, 5))
        self.assertNotIn("ends", [e["id"] for e in jan["items"]])


class Timeline(unittest.TestCase):
    def test_chain(self):
        rows = mm.timeline(STATE, periods=6, on=date(2026, 11, 17))
        self.assertEqual(len(rows), 6)
        for prev, nxt in zip(rows, rows[1:]):
            self.assertAlmostEqual(prev["left"], nxt["carry"], places=2)   # end of one = start of next

    def test_matches_daily_forecast(self):
        # the old day-by-day engine and the new period engine must agree on end cash
        rows = mm.timeline(STATE, periods=4, on=date(2026, 11, 17))
        cash = STATE["startingCash"]
        paid = mm._paid_map(STATE)
        for e in mm._events(STATE, date(2026, 11, 10), mm.d(rows[-1]["end"]), "average", paid):
            cash += e["remaining"] if e["direction"] == "income" else -e["remaining"]
        self.assertAlmostEqual(rows[-1]["left"], cash, places=2)


class Upcoming(unittest.TestCase):
    def test_states(self):
        rows = {e["id"]: e for e in mm.upcoming_bills(STATE, days=14, on=date(2026, 11, 17))}
        self.assertEqual(rows["net"]["state"], "overdue")      # has a real due date that passed
        self.assertEqual(rows["rent"]["state"], "unmarked")     # period date passed, no due date
        self.assertEqual(rows["elec"]["state"], "soon")
        self.assertNotIn("old", rows)                           # before snapshot


class Cards(unittest.TestCase):
    def args(self, **kw):
        base = dict(on="2026-11-17", offset=0, scenario=None, periods=6, days=14, payment=None,
                    amount=None, label="Test", date=None, out=None, html=False)
        base.update(kw)
        return types.SimpleNamespace(**base)

    def test_all_builders_produce_html_and_caption(self):
        for kind, extra in [("period", {}), ("bills", {}), ("timeline", {}), ("receipt", {}),
                            ("whatif", {"amount": 2500}), ("debts", {}), ("icons", {})]:
            doc, cap = cards.BUILDERS[kind](STATE, self.args(**extra))
            self.assertIn("<html>", doc, kind)
            self.assertTrue(cap, kind)
            self.assertNotIn("None", cap, kind)

    def test_period_caption_uses_engine_numbers(self):
        _, cap = cards.card_period(STATE, self.args())
        self.assertIn("₱38,300.00 left", cap)

    def test_whatif_math(self):
        _, cap = cards.card_whatif(STATE, self.args(amount=40000, label="Phone"))
        self.assertIn("causes a shortfall", cap)
        self.assertIn("−₱1,700.00", cap)

    def test_whatif_warns_when_a_later_period_goes_short(self):
        rows = mm.timeline(STATE, periods=4, on=date(2026, 11, 17))
        now = rows[0]["left"]
        later = min(r["left"] for r in rows[1:] if r["left"] >= 0)
        amt = (min(now, later) + max(now, later)) / 2 if later < now else None
        if amt is None:
            self.skipTest("fixture has no period tighter than the current one")
        _, cap = cards.card_whatif(STATE, self.args(amount=amt, label="Phone"))
        self.assertIn("fits this period but leaves", cap)

    def test_names_are_escaped(self):
        st = dict(STATE, flows=STATE["flows"] + [{"id": "x", "name": "<b>evil</b>", "direction": "expense",
                                                   "schedule": "once", "amount": 1, "date": "2026-11-20"}])
        doc, _ = cards.card_period(st, self.args())
        self.assertNotIn("<b>evil</b>", doc)

    @unittest.skipUnless(shutil.which("chromium"), "chromium not installed")
    def test_render_png(self):
        out = os.path.join(tempfile.mkdtemp(), "t.png")
        res = cards.make("receipt", STATE, self.args(out=out))
        self.assertTrue(os.path.getsize(res["png"]) > 10000)
        self.assertLess(res["height"], 900)   # receipt is short; no empty canvas


class Runway(unittest.TestCase):
    def test_series_lands_on_period_ends(self):
        on = date(2026, 11, 17)
        rows = mm.timeline(STATE, periods=4, on=on)
        series = dict(cards.runway_series(STATE, on, mm.d(rows[-1]["end"]), "average"))
        for r in rows:
            self.assertAlmostEqual(series[mm.d(r["end"])], r["left"], places=2, msg=r["label"])

    def test_caption_names_the_dip(self):
        st = dict(STATE, startingCash=-40000)   # payday on the 10th still leaves it negative
        _, cap = cards.card_timeline(st, Cards().args())
        self.assertTrue(cap.startswith(("Dips below zero", "Already below zero")), cap)


class Icons(unittest.TestCase):
    def test_search_understands_local_words(self):
        self.assertEqual(icons.search("Meralco")[0], "lightning")
        self.assertEqual(icons.search("PLDT fiber")[0], "wifi-high")
        self.assertEqual(icons.search("tuition")[0], "graduation-cap")
        self.assertTrue(icons.search("dog food"))          # falls through to Phosphor tags

    def test_icons_unique_per_kind_and_colours_not_status(self):
        t = icons.assign(STATE)
        own = {}                                   # one icon per distinct bill name, unless it fell back to its category's
        for f in STATE["flows"]:
            ic = t[f"flow:{f['id']}"]["icon"]
            if ic != t[f"cat:{f['category']}"]["icon"]:
                own.setdefault(icons.bill_key(f["name"]), ic)
        self.assertEqual(len(own.values()), len(set(own.values())))
        self.assertEqual(t["flow:pay-10"]["icon"], t["flow:pay-25"]["icon"])   # "10th payday" / "25th payday"
        cats = [v["icon"] for k, v in t.items() if k.startswith("cat:")]
        self.assertEqual(len(cats), len(set(cats)))
        for k, v in t.items():
            if k.startswith("cat:"):
                self.assertIn(v["color"], icons.PALETTE)
        self.assertFalse(set(icons.PALETTE.values()) & set(icons.STATUS.values()))

    def test_saved_look_wins(self):
        st = dict(STATE, looks={"flow:rent": {"icon": "bank"}, "cat:Utilities": {"color": "pink"}})
        t = icons.assign(st)
        self.assertEqual(t["flow:rent"]["icon"], "bank")
        self.assertEqual(icons.look(t, flow_id="net", category="Utilities")[1], icons.PALETTE["pink"])
        self.assertNotEqual(t["flow:net"]["icon"], "bank")

    def test_svg_is_real_markup(self):
        self.assertIn("<path", icons.svg("wallet"))
        self.assertIn("<path", icons.svg("no-such-icon"))  # fallback, never empty


class Paydays(unittest.TestCase):
    def test_default_matches_old_rule(self):
        self.assertEqual(mm.period_bounds(date(2026, 11, 17)), (date(2026, 11, 10), date(2026, 11, 24), 1))
        self.assertEqual(mm.period_bounds(date(2026, 11, 5)), (date(2026, 10, 25), date(2026, 11, 9), 2))

    def test_15_30_clamps_in_february(self):
        self.assertEqual(mm.period_bounds(date(2027, 2, 20), [15, 30]), (date(2027, 2, 15), date(2027, 2, 27), 1))
        self.assertEqual(mm.period_bounds(date(2027, 3, 1), [15, 30]), (date(2027, 2, 28), date(2027, 3, 14), 2))

    def test_monthly(self):
        self.assertEqual(mm.period_bounds(date(2026, 11, 17), [25]), (date(2026, 10, 25), date(2026, 11, 24), 1))

    def test_state_paydays_drive_periods_and_chain(self):
        st = dict(STATE, paydays=[15, 30])
        p = mm.period_detail(st, on=date(2026, 11, 17))
        self.assertEqual((p["period"]["start"], p["period"]["end"]), ("2026-11-15", "2026-11-29"))
        self.assertEqual(p["period"]["name"], "1st period · 15th pay")
        rows = mm.timeline(st, periods=4, on=date(2026, 11, 17))
        for x, y in zip(rows, rows[1:]):
            self.assertAlmostEqual(x["left"], y["carry"], places=2)


class Spending(unittest.TestCase):
    ST = dict(STATE, spends=[{"id": "s1", "date": "2026-11-15", "amount": 500, "category": "Food", "note": "lunch"},
                             {"id": "s0", "date": "2026-11-08", "amount": 999, "category": "Food", "note": "old"}])

    def test_spend_lowers_left_but_is_not_a_bill(self):
        base = mm.period_detail(STATE, on=date(2026, 11, 17))
        p = mm.period_detail(self.ST, on=date(2026, 11, 17))
        self.assertEqual(p["spent"], 500)                      # the Nov 8 one is inside the snapshot
        self.assertAlmostEqual(p["left"], base["left"] - 500, places=2)
        self.assertEqual(p["bills_total"], base["bills_total"])
        self.assertNotIn("s1", [e["id"] for e in mm.upcoming_bills(self.ST, on=date(2026, 11, 17))])

    def test_per_day(self):
        p = mm.period_detail(STATE, on=date(2026, 11, 17))
        self.assertEqual(p["days_left"], 8)
        self.assertAlmostEqual(p["per_day"], round(p["left"] / 8, 2), places=2)

    def test_period_card_shows_spending(self):
        doc, cap = cards.card_period(self.ST, Cards().args())
        self.assertIn("Spent this period", doc)
        self.assertIn("/day", cap)


class DueAndDebts(unittest.TestCase):
    def test_due_day_rolls_forward(self):
        self.assertEqual(mm.due_for({"due": "5", "schedule": "monthly"}, "2026-11-15"), "2026-12-05")
        self.assertEqual(mm.due_for({"due": "20", "schedule": "monthly"}, "2026-11-15"), "2026-11-20")
        self.assertEqual(mm.due_for({"due": "2026-11-13", "schedule": "monthly"}, "2026-12-13"), "2026-12-13")

    def test_linked_payment_lowers_debt(self):
        st = dict(STATE, debtLinks={"rent": "card"},
                  balances=[{"id": "card", "name": "Card", "kind": "debt", "amount": 100000, "asOf": "2026-11-01"}])
        x = mm.debt_status(st)[0]
        self.assertEqual((x["paid_since"], x["now"]), (5000, 95000))
        _, cap = cards.card_debts(st, Cards().args())
        self.assertIn("₱95,000.00 owed now", cap)


class Brief(unittest.TestCase):
    def test_payday_sends_period_card(self):
        lines, card = mm.brief(STATE, date(2026, 11, 25))
        self.assertEqual(card, "period")
        self.assertTrue(any("Payday today" in x for x in lines))

    def test_quiet_day_is_silent(self):
        st = dict(STATE, asOf="2026-11-18")
        self.assertEqual(mm.brief(st, date(2026, 11, 19)), ([], None))

    def test_stale_cash_nudges(self):
        lines, _ = mm.brief(dict(STATE, asOf="2026-11-10"), date(2026, 11, 19))
        self.assertTrue(any("cash figure is 9 days old" in x for x in lines))


class PayDeductsCash(unittest.TestCase):
    def test_pay_after_snapshot_moves_cash_and_undo_restores(self):
        import subprocess
        db = os.path.join(tempfile.mkdtemp(), "t.db")
        mmpy = os.path.join(os.path.dirname(__file__), "..", "tools", "moneymap.py")
        run = lambda *a: subprocess.run([sys.executable, mmpy, "--db", db, *a], capture_output=True, text=True).stdout
        run("seed")                                             # asOf 2026-11-01, cash 8000
        before = mm.period_detail(mm.export_state(mm.connect(db)) | {"paydays": [15, 30]}, on=date(2026, 11, 20))["left"]
        out = run("pay", "--flow", "rent", "--original-date", "2026-11-15", "--amount", "9000", "--paid-on", "2026-11-15")
        self.assertIn("cash now -1,000.00", out)
        st = mm.export_state(mm.connect(db)) | {"paydays": [15, 30]}
        self.assertAlmostEqual(mm.period_detail(st, on=date(2026, 11, 20))["left"], before, places=2)
        pid = out.split()[2].rstrip(";")
        self.assertIn("9,000.00 back in cash", run("undo", pid))
        self.assertEqual(mm.export_state(mm.connect(db))["startingCash"], 8000)
        self.assertIn("already included", run("pay", "--flow", "rent", "--original-date", "2026-11-15",
                                                "--amount", "9000", "--no-deduct"))
        run("cash", "5000", "--date", "2026-11-20")           # bill dated before the snapshot: already in cash
        self.assertIn("already included", run("pay", "--flow", "electric", "--original-date", "2026-11-15",
                                                "--amount", "2500", "--paid-on", "2026-11-21"))


if __name__ == "__main__":
    unittest.main()
