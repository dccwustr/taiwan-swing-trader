import sys, unittest
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import trade_check as tc

def frame(rows):
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], dtype=float)

class Costs(unittest.TestCase):
    def test_net_rr_below_gross(self):
        c = tc.check_trade(100, 96, 110)
        self.assertLess(c["net_rr"], 2.5)
        expected = (110 * (1 - .001425 - .003) - 100 * 1.001425) / (100 * 1.001425 - 96 * (1 - .001425 - .003))
        self.assertAlmostEqual(c["net_rr"], round(expected, 2))

class Risk(unittest.TestCase):
    def test_bad_rr_blocks(self):
        c = tc.check_trade(100, 88, 105)   # +5% / -12%
        self.assertEqual(c["verdict"], "BLOCK")
        self.assertTrue(any("報酬風險比" in r for r in c["reasons"]))
        self.assertTrue(any("跌停" in w for w in c["warnings"]))
    def test_good_passes(self):
        self.assertEqual(tc.check_trade(100, 95, 115)["verdict"], "PASS")
    def test_bad_order(self):
        self.assertEqual(tc.check_trade(100, 101, 110)["verdict"], "BLOCK")
        self.assertEqual(tc.check_trade(100, 95, 99)["verdict"], "BLOCK")
    def test_unaffordable(self):
        c = tc.check_trade(20000, 19000, 23000)
        self.assertEqual(c["verdict"], "BLOCK")
        self.assertEqual(c["size"]["shares"], 0)
    def test_loss_cap_blocks_one_share(self):
        c = tc.check_trade(5000, 4000, 8000)
        self.assertTrue(any("上限" in r for r in c["reasons"]))

class Size(unittest.TestCase):
    def test_limits(self):
        s = tc.size_odd_lot(100, 90, 10000, 500)
        self.assertEqual(s["by_budget"], 99)
        self.assertEqual(s["shares"], s["by_loss"])
        self.assertLessEqual(s["loss_at_stop"], 500)
        self.assertLessEqual(s["cost"], 10000)

class Walk(unittest.TestCase):
    def test_both_touched_is_stop(self):
        d = frame([[100,100,100,100],[100,120,80,100]])
        self.assertEqual(tc.walk_forward(d, 0, 90, 110, 5)["outcome"], -1)
    def test_gap_fills_at_open(self):
        d = frame([[100,100,100,100],[70,72,69,70]])
        r = tc.walk_forward(d, 0, 90, 110, 5)
        self.assertLess(r["r"], -2.5)
    def test_target(self):
        d = frame([[100,100,100,100],[101,111,100,105]])
        self.assertEqual(tc.walk_forward(d, 0, 90, 110, 5)["outcome"], 1)
    def test_unfinished_is_none(self):
        d = frame([[100,100,100,100],[100,101,99,100]])
        self.assertIsNone(tc.walk_forward(d, 0, 90, 110, 5))
    def test_expiry(self):
        d = frame([[100,100,100,100]] + [[100,101,99,102]] * 3)
        r = tc.walk_forward(d, 0, 90, 110, 3)
        self.assertEqual(r["outcome"], 0)
        self.assertEqual(r["exit_idx"], 3)

def random_df(drift, n=250, seed=1):
    rng = np.random.default_rng(seed)
    c = 100 * np.cumprod(1 + rng.normal(drift, .015, n))
    o = np.r_[100, c[:-1]]
    return pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.005, "Low": np.minimum(o, c) * .995, "Close": c})

class Sim(unittest.TestCase):
    def test_sums_and_repeatable(self):
        df = random_df(0)
        a, b = tc.simulate_odds(df, 100, 95, 110), tc.simulate_odds(df, 100, 95, 110)
        self.assertEqual(a, b)
        self.assertAlmostEqual(a["target_pct"] + a["stop_pct"] + a["neither_pct"], 100, delta=.2)
    def test_drift_direction(self):
        up, dn = tc.simulate_odds(random_df(.004), 100, 95, 110), tc.simulate_odds(random_df(-.004), 100, 95, 110)
        self.assertGreater(up["target_pct"], dn["target_pct"])
        self.assertGreater(up["avg_r"], dn["avg_r"])
    def test_too_few_bars(self):
        self.assertIsNone(tc.simulate_odds(random_df(0, n=20), 100, 95, 110))
    def test_invalid_plan(self):
        self.assertIsNone(tc.simulate_odds(random_df(0), 100, 105, 110))
    def test_history(self):
        h = tc.history_same_distance(random_df(0), 100, 95, 110)
        self.assertGreater(h["n"], 3)
        self.assertEqual(h["n"], h["target"] + h["stop"] + h["neither"])

class Html(unittest.TestCase):
    def test_no_blank_lines(self):
        df = random_df(0)
        h = tc.render_html(tc.check_trade(100, 95, 115), tc.simulate_odds(df, 100, 95, 115), tc.history_same_distance(df, 100, 95, 115))
        self.assertNotIn("\n", h)
        self.assertIn("PASS", h)
    def test_empty(self):
        self.assertEqual(tc.render_html(), "")

if __name__ == "__main__":
    unittest.main()
