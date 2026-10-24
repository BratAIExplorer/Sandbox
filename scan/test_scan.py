"""Offline tests with made-up data (no network). Run: python -m unittest scan/test_scan.py -v
They prove the RULES do what they say. They do NOT prove Yahoo data is right."""
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import logic
import run_scan

TODAY = date(2026, 10, 24)


def series(n, start, daily, vol=1_000_000, dates_end=TODAY):
    closes, c = [], start
    for _ in range(n):
        c *= 1 + daily
        closes.append(c)
    dates = [dates_end - timedelta(days=n - 1 - i) for i in range(n)]
    return dict(dates=dates, closes=closes, vols=[vol] * n)


GOOD_FUND = dict(
    name="Good Co", sector="Healthcare", industry="Diagnostics", mcap=50e9, pe=40, pb=5, inst=0.4, roe=0.20,
    eps_q=[12, 11, 10, 9, 8], rev_q=[130, 125, 120, 115, 100], ni_q=[12, 11, 10, 9, 8],
    qdates=[date(2026, 6, 30), date(2026, 3, 31), date(2025, 12, 31), date(2025, 9, 30), date(2025, 6, 30)],
    eps_a=[40, 33, 27, 20], vendor_rev_g=0.30, vendor_ni_g=0.50,
    last_reported=date(2026, 8, 5), next_earnings=date(2026, 11, 10),
)


class FakeSource:
    def __init__(self, funds):
        self.funds = funds
        self.px = {
            "^CRSLDX": series(300, 100, -0.001),                 # index drifting down
            "GOOD.NS": series(300, 100, 0.004),                  # steady riser
            "FLAT.NS": series(300, 100, 0.0),                    # flat -> not up 12m
            "THIN.NS": series(300, 100, 0.004, vol=10),          # illiquid
            "SHORT.NS": series(100, 100, 0.004),                 # <1y history
        }

    def prices(self, tickers):
        return {t: self.px[t] for t in tickers if t in self.px}

    def fundamentals(self, sym):
        return self.funds.get(sym, {})


class Rules(unittest.TestCase):
    def test_yoy_refuses_bad_base(self):
        self.assertIsNone(logic.yoy(5, -2))
        self.assertIsNone(logic.yoy(5, 0))
        self.assertAlmostEqual(logic.yoy(15, 10), 0.5)

    def test_cagr(self):
        self.assertAlmostEqual(logic.cagr(8, 1, 3), 1.0)
        self.assertIsNone(logic.cagr(8, -1, 3))

    def test_distribution_days(self):
        closes, vols = [100.0] * 30, [1.0] * 30
        closes[-3], vols[-3] = 99.0, 2.0   # down 1% on higher volume
        closes[-2], closes[-1] = 99.0, 99.0
        self.assertEqual(logic.distribution_days(closes, vols, 25), 1)

    def test_gate_unknown_without_data(self):
        self.assertTrue(logic.index_gate([1.0] * 50, [1.0] * 50)["status"].startswith("UNKNOWN"))

    def test_gate_no_go_when_below_averages(self):
        g = logic.index_gate(series(300, 100, -0.002)["closes"], [1e6] * 300)
        self.assertEqual(g["status"], "NO-GO")

    def test_rs_rank_orders(self):
        r = logic.rs_ranks({"a": 0.1, "b": 0.5, "c": -0.2})
        self.assertEqual((r["c"], r["a"], r["b"]), (0.0, 50.0, 100.0))

    def test_stale_detection(self):
        # statement latest quarter 30-Jun, but company reported again on 17-Oct (the KVB case)
        self.assertTrue(logic.statement_lagging(date(2026, 6, 30), date(2026, 10, 17)))
        self.assertFalse(logic.statement_lagging(date(2026, 6, 30), date(2026, 8, 5)))

    def test_pct_of_high_uses_closes_and_dates(self):
        s = series(300, 100, 0.004)
        s["closes"][-10] = 1000.0
        ph, d = logic.pct_of_high(s["closes"], s["dates"])
        self.assertEqual(d, s["dates"][-10])
        self.assertLess(ph, 1)


class EndToEnd(unittest.TestCase):
    def run_scan(self, funds, **kw):
        uni = [("GOOD.NS", "Good"), ("FLAT.NS", "Flat"), ("THIN.NS", "Thin"), ("SHORT.NS", "Short")]
        return run_scan.run("india", FakeSource(funds), uni, TODAY, min_liq=1000, log=lambda *a: None, **kw)

    def test_funnel_and_core(self):
        res = self.run_scan({"GOOD.NS": GOOD_FUND})
        f = dict(res["funnel"])
        self.assertEqual(f["has 1y of prices"], 3)          # SHORT dropped
        self.assertEqual(res["gate"]["status"], "NO-GO")
        self.assertEqual([r["symbol"] for r in res["rows"]], ["GOOD.NS"])  # FLAT not up, THIN illiquid
        r = res["rows"][0]
        self.assertTrue(r["core_clean"])
        self.assertEqual((r["C"], r["A"], r["N"], r["L"]), ("Y", "Y", "Y", "Y"))

    def test_stale_and_mismatch_flags_block_clean(self):
        bad = dict(GOOD_FUND, last_reported=date(2026, 10, 17), vendor_rev_g=0.05)
        r = self.run_scan({"GOOD.NS": bad})["rows"][0]
        self.assertTrue(r["core"])
        self.assertFalse(r["core_clean"])
        self.assertIn("STALE", r["flags"])
        self.assertIn("CHECK-SALES", r["flags"])

    def test_negative_base_gives_na_not_percent(self):
        neg = dict(GOOD_FUND, eps_q=[5, 4, 3, 2, -1])
        r = self.run_scan({"GOOD.NS": neg})["rows"][0]
        self.assertIsNone(r["eps_q_yoy"])
        self.assertEqual(r["C"], "n")
        self.assertIn("NA-GROWTH", r["flags"])

    def test_bank_flagged(self):
        bank = dict(GOOD_FUND, industry="Banks - Regional")
        self.assertIn("BANK", self.run_scan({"GOOD.NS": bank})["rows"][0]["flags"])


if __name__ == "__main__":
    unittest.main()
