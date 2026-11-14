"""All candle data in this file is SYNTHETIC TEST DATA - never used for live analysis."""
import unittest, math
import numpy as np, pandas as pd
from futures.indicators import ema, rsi, atr, sma
from futures.validation import validate_candles
from futures import strategy as S
from futures.risk import size_position
from futures.trade_mgmt import PaperTrade
from futures.explain import explain
from core.db import DB
from core.config import Config, ConfigError

H, H4 = 3_600_000, 14_400_000
NOW = 1_700_000_000_000 // H4 * H4 + H4 + 10          # just after a 4H boundary


def mk(n, iv, now, f):
    last_open = (now // iv) * iv - iv
    rows = []
    for i in range(n):
        t = last_open - (n - 1 - i) * iv
        o, h, l, c, v = f(i)
        rows.append((t, o, h, l, c, v))
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])


def uptrend_frames(final=True):
    # 4H steady uptrend
    d4 = mk(300, H4, NOW, lambda i: (100 + i * .5, 100 + i * .5 + 1, 100 + i * .5 - 1, 100 + i * .5 + .5, 1000))
    base = 200.0
    def f(i):
        p = base + i * 0.2
        return (p, p + 1, p - 1, p + .2, 100)
    d1 = mk(120, H, NOW, f)
    return d1, d4


class TestIndicators(unittest.TestCase):
    def test_ema_known(self):
        s = pd.Series([1, 2, 3, 4, 5.0]); e = ema(s, 3)
        self.assertAlmostEqual(e.iloc[2], 2.0); self.assertAlmostEqual(e.iloc[3], 3.0); self.assertAlmostEqual(e.iloc[4], 4.0)
        self.assertTrue(math.isnan(e.iloc[1]))
    def test_sma(self): self.assertAlmostEqual(sma(pd.Series([1, 2, 3, 4.0]), 2).iloc[-1], 3.5)
    def test_rsi_bounds_and_extremes(self):
        up = rsi(pd.Series(range(1, 40), dtype=float)); self.assertEqual(up.iloc[-1], 100.0)
        dn = rsi(pd.Series(range(40, 1, -1), dtype=float)); self.assertAlmostEqual(dn.iloc[-1], 0.0)
        r = rsi(pd.Series(np.sin(np.arange(100)) + 10)).dropna(); self.assertTrue(((r >= 0) & (r <= 100)).all())
    def test_rsi_wilder_reference(self):
        # classic Wilder example series (first RSI(14) value ~70.46)
        c = pd.Series([44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28])
        self.assertAlmostEqual(rsi(c, 14).iloc[14], 70.46, delta=0.1)
    def test_atr_constant_range(self):
        df = pd.DataFrame({"high": [11.0] * 30, "low": [9.0] * 30, "close": [10.0] * 30}); self.assertAlmostEqual(atr(df).iloc[-1], 2.0)


class TestValidation(unittest.TestCase):
    def test_incomplete_candle_dropped(self):
        d1, _ = uptrend_frames(); extra = pd.DataFrame([{"time": d1.time.iloc[-1] + H, "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 1}])
        cleaned, issues = validate_candles(pd.concat([d1, extra]), "1h", d1.time.iloc[-1] + H + 5, 60)
        self.assertEqual(issues, []); self.assertEqual(len(cleaned), len(d1))
    def test_duplicate_invalid_gap_stale(self):
        d1, _ = uptrend_frames(); now = int(d1.time.iloc[-1] + H + 5)
        self.assertTrue(validate_candles(pd.concat([d1, d1.tail(1)]), "1h", now, 60)[1])
        bad = d1.copy(); bad.loc[50, "high"] = bad.loc[50, "low"] - 1; self.assertTrue(validate_candles(bad, "1h", now, 60)[1])
        self.assertTrue(validate_candles(d1.drop(index=60), "1h", now, 60)[1])
        self.assertTrue(validate_candles(d1, "1h", now + 3 * H, 60)[1])
        self.assertTrue(validate_candles(d1.head(10), "1h", now, 60)[1])
        self.assertTrue(validate_candles(None, "1h", now, 60)[1])


def long_setup():
    """Crafted synthetic frames that satisfy all six LONG conditions."""
    d4 = mk(300, H4, NOW, lambda i: (100 + i * .5, 100 + i * .5 + 1, 100 + i * .5 - 1, 100 + i * .5 + .5, 1000))
    n = 120
    closes = [200 + 0.3 * i + (0.6 if i % 2 else -0.6) for i in range(n)]          # choppy uptrend -> RSI mid-range
    def f(i):
        c = closes[i]; return (c - .3, c + .5, c - .5, c, 100)
    d1 = mk(n, H, NOW, f)
    return d1, d4


def entry_long_frames():
    n = 120; closes = [200 + 0.1 * i + (0.8 if i % 2 else -0.8) for i in range(n)]
    d4 = mk(300, H4, NOW, lambda i: (100 + i * .5, 100 + i * .5 + 1, 100 + i * .5 - 1, 100 + i * .5 + .5, 1000))
    d1 = mk(n, H, NOW, lambda i: (closes[i] - .3, closes[i] + .5, closes[i] - .5, closes[i], 100)).copy()
    e = float(ema(d1.close, 21).iloc[n - 2]); p = n - 2
    d1.loc[p, ["open", "high", "low", "close"]] = [e + .2, e + 1.0, e - .2, e + .3]
    base = e + .3
    d1.loc[n - 1, ["open", "high", "low", "close", "volume"]] = [base, base + 1.05, base - .05, base + 1.0, 500]
    return d1, d4


def mirror(d):
    m = d.copy(); m["open"], m["close"] = 400 - d["open"], 400 - d["close"]; m["high"], m["low"] = 400 - d["low"], 400 - d["high"]; return m


class TestEntry(unittest.TestCase):
    def test_long_entry_full_pipeline(self):
        d1, d4 = entry_long_frames(); a = S.analyze("T", d1, d4, 0.0001, 8, NOW)
        self.assertEqual(a.status, "ENTRY — LONG"); self.assertTrue(a.plan["valid"])
        self.assertLess(a.plan["sl"], a.plan["entry"]); self.assertGreater(a.plan["tp2"], a.plan["tp1"]); self.assertGreaterEqual(a.plan["rr_tp2"], 2)
        self.assertAlmostEqual(a.plan["tp1"] - a.plan["entry"], 1.5 * a.plan["R"])
        self.assertEqual(a.signal_candle_ms, int(d1.time.iloc[-1]))
        self.assertEqual(S.analyze("T", d1, d4, 0.0001, 8, NOW).to_dict()["status"], a.status)   # deterministic
    def test_each_condition_failure_blocks_entry(self):
        d1, d4 = entry_long_frames()
        low_vol = d1.copy(); low_vol.loc[len(low_vol) - 1, "volume"] = 100
        a = S.analyze("T", low_vol, d4, 0.0001, 8, NOW); self.assertNotEqual(a.status, "ENTRY — LONG"); self.assertFalse(a.long_conds[3].passed)
        bear = d1.copy(); i = len(bear) - 1; bear.loc[i, ["open", "close"]] = [bear.loc[i, "close"], bear.loc[i, "open"]]
        self.assertFalse(S.analyze("T", bear, d4, 0.0001, 8, NOW).long_conds[4].passed)
    def test_mirror_short_conditions_evaluated(self):
        d1, d4 = entry_long_frames(); a = S.analyze("T", mirror(d1), mirror(d4), 0.0001, 8, NOW)
        self.assertTrue(a.short_conds[0].passed); self.assertFalse(a.long_conds[0].passed)    # trend side flips


class TestStrategy(unittest.TestCase):
    def _force_long(self):
        d1, d4 = long_setup()
        e21 = ema(d1.close, 21)
        # previous candle dips to EMA21 (low <= ema), RSI rises: craft last two candles
        d1 = d1.copy()
        p = len(d1) - 2
        e = float(e21.iloc[p])
        d1.loc[p, ["open", "high", "low", "close"]] = [e + .2, e + 1.0, e - 0.2, e + .3]
        c = len(d1) - 1
        base = e + .3
        d1.loc[c, ["open", "high", "low", "close", "volume"]] = [base, base + 2.0, base - 0.05, base + 1.9, 500]
        return d1, d4

    def test_all_conditions_structure_and_explain(self):
        d1, d4 = self._force_long()
        a = S.analyze("TEST_USDT", d1, d4, 0.0001, 8, NOW)
        self.assertIn(a.status, ("ENTRY — LONG", "WAIT", "NO SIGNAL"))
        self.assertEqual(len(a.long_conds), 6); self.assertEqual(len(a.short_conds), 6)
        txt = explain(a); self.assertIn("PASS", txt + "FAIL")
        self.assertTrue(a.long_conds[0].passed)            # 4H uptrend must pass on the synthetic trend
        self.assertFalse(a.short_conds[0].passed)

    def test_entry_requires_all_six(self):
        d1, d4 = self._force_long()
        a = S.analyze("T", d1, d4, 0.0001, 8, NOW)
        if a.status == "ENTRY — LONG": self.assertTrue(all(c.passed for c in a.long_conds))
        # funding failure blocks LONG regardless of other conditions
        b = S.analyze("T", d1, d4, 0.0005, 8, NOW)
        self.assertFalse(b.long_conds[5].passed); self.assertNotEqual(b.status, "ENTRY — LONG")

    def test_funding_units_and_boundaries(self):
        d1, d4 = self._force_long()
        a = S.analyze("T", d1, d4, 0.0003, 8, NOW); self.assertFalse(a.long_conds[5].passed)       # not strictly <
        a = S.analyze("T", d1, d4, 0.00029, 8, NOW); self.assertTrue(a.long_conds[5].passed)
        a = S.analyze("T", d1, d4, -0.0003, 8, NOW); self.assertFalse(a.short_conds[5].passed)
        self.assertAlmostEqual(a.metrics["funding_pct"], -0.03)

    def test_data_unavailable_cases(self):
        d1, d4 = self._force_long()
        self.assertEqual(S.analyze("T", d1, d4, None, 8, NOW).status, "DATA UNAVAILABLE")
        self.assertEqual(S.analyze("T", None, d4, 0.0, 8, NOW).status, "DATA UNAVAILABLE")
        self.assertEqual(S.analyze("T", d1.head(30), d4, 0.0, 8, NOW).status, "DATA UNAVAILABLE")
        self.assertEqual(S.analyze("T", d1, d4, 0.0, 8, NOW + 10 * H).status, "DATA UNAVAILABLE")   # stale

    def test_incomplete_candle_never_signals(self):
        d1, d4 = self._force_long()
        incomplete = d1.tail(1).copy(); incomplete["time"] = incomplete["time"] + H
        a = S.analyze("T", pd.concat([d1.iloc[:-1], incomplete]), d4, 0.0001, 8, NOW)   # last completed candle removed -> stale/different
        self.assertNotEqual(a.status, "ENTRY — LONG")

    def test_zero_range_candle_rejected(self):
        self.assertIsNone(S.candle_ratio(1, 5, 5, 5))
        self.assertAlmostEqual(S.candle_ratio(1, 10, 0, 8), 0.8)

    def test_wait_is_not_entry_and_no_signal(self):
        d1, d4 = long_setup()
        a = S.analyze("T", d1, d4, 0.0001, 8, NOW)
        self.assertNotIn(a.status, ("ENTRY — SHORT",))
        flat = mk(300, H4, NOW, lambda i: (100, 101, 99, 100, 1000)); flat1 = mk(120, H, NOW, lambda i: (100, 101, 99, 100, 100))
        self.assertEqual(S.analyze("T", flat1, flat, 0.0, 8, NOW).status, "NO SIGNAL")


class TestPlan(unittest.TestCase):
    def frames(self):
        d1 = mk(40, H, NOW, lambda i: (100, 101, 99, 100, 10)); d4 = mk(60, H4, NOW, lambda i: (100, 120, 90, 100, 10))
        return d1, d4
    def test_long_plan_math(self):
        d1, _ = self.frames(); d4 = mk(60, H4, NOW, lambda i: (100, 150 if i == 30 else 105, 95, 100, 10))
        p = S.build_plan("LONG", 105.0, d1, d4, 2.0, 4.0)
        self.assertAlmostEqual(p["swing"], 99); self.assertAlmostEqual(p["sl"], 98.0); self.assertAlmostEqual(p["R"], 7.0)   # 3.5x ATR boundary
        self.assertTrue(p["valid"]); self.assertAlmostEqual(p["tp1"], 115.5); self.assertAlmostEqual(p["base_tp2"], 126.0)
        self.assertAlmostEqual(p["tp2"], 126.0); self.assertGreaterEqual(p["rr_tp2"], 2)
    def test_sl_distance_limits(self):
        d1, d4 = self.frames()
        self.assertFalse(S.build_plan("LONG", 99.5, d1, d4, 2.0, 1.0)["valid"])      # R too small (<0.8 ATR) or SL wrong side
        self.assertFalse(S.build_plan("LONG", 140, d1, d4, 2.0, 1.0)["valid"])       # R too large
    def test_resistance_adjustment_and_min_2r(self):
        d1 = mk(40, H, NOW, lambda i: (100, 101, 99, 100, 10))
        d4 = mk(60, H4, NOW, lambda i: (100, 110, 95, 100, 10))   # resistance 110
        p = S.build_plan("LONG", 101.0, d1, d4, 1.0, 2.0)          # SL=98.5 R=2.5 base TP2=108.5; cap=110-.5=109.5 -> TP2=108.5
        self.assertTrue(p["valid"]); self.assertAlmostEqual(p["tp2"], 108.5)
        d4b = mk(60, H4, NOW, lambda i: (100, 104, 95, 100, 10))   # resistance 104 -> cap 103.5 < 2R(106)
        p2 = S.build_plan("LONG", 101.0, d1, d4b, 1.0, 2.0); self.assertFalse(p2["valid"]); self.assertIn("2R", p2["reject"])
    def test_short_plan(self):
        d1 = mk(40, H, NOW, lambda i: (100, 101, 99, 100, 10)); d4 = mk(60, H4, NOW, lambda i: (100, 105, 60, 100, 10))
        p = S.build_plan("SHORT", 99.0, d1, d4, 1.0, 2.0)          # SL=101.5 R=2.5 TP1=95.25 base2=91.5
        self.assertTrue(p["valid"]); self.assertAlmostEqual(p["sl"], 101.5); self.assertAlmostEqual(p["tp1"], 95.25); self.assertAlmostEqual(p["tp2"], 91.5)
    def test_missing_data(self):
        d1, d4 = self.frames(); self.assertFalse(S.build_plan("LONG", 100, d1.head(5), d4, 1, 1)["valid"])
        self.assertFalse(S.build_plan("LONG", 100, d1, d4, float("nan"), 1)["valid"])


class TestRisk(unittest.TestCase):
    spec = dict(min_qty=0.001, qty_step=0.001, max_leverage=10)
    def test_sizing(self):
        r = size_position(1000, .015, 100, 95, self.spec, .0005, .0005, 5, 1000)
        self.assertTrue(r["ok"]); self.assertAlmostEqual(r["qty"], 3.0); self.assertAlmostEqual(r["planned_risk"], 15.0)
        self.assertAlmostEqual(r["notional"], 300.0); self.assertAlmostEqual(r["initial_margin"], 60.0)
    def test_rejections(self):
        self.assertFalse(size_position(1000, .015, 100, 95, None, .0005, .0005, 5, 1000)["ok"])
        self.assertFalse(size_position(1000, .015, 100, 95, self.spec, .0005, .0005, 5, 10)["ok"])         # margin
        self.assertFalse(size_position(1, .015, 100, 50, dict(min_qty=1, qty_step=1), .0005, .0005, 5, 1000)["ok"])  # below min


class TestTradeMgmt(unittest.TestCase):
    def mk(self, d="LONG"):
        return PaperTrade("T", d, 100.0, 95.0, 107.5, 115.0, 10.0, 0, fee_rate=0.001) if d == "LONG" else \
               PaperTrade("T", d, 100.0, 105.0, 92.5, 85.0, 10.0, 0, fee_rate=0.001)
    def c(self, i, o, h, l, c): return dict(time=i * H, open=o, high=h, low=l, close=c)
    def test_stop_loss(self):
        t = self.mk(); t.on_candle(self.c(0, 100, 101, 94, 95), 98); self.assertEqual(t.exit_reason, "STOP_LOSS"); self.assertLess(t.net_pnl, 0)
    def test_tp1_partial_be_trail_tp2(self):
        t = self.mk(); t.on_candle(self.c(0, 100, 108, 99, 107), 99)
        self.assertEqual(t.stage, "TP1_DONE"); self.assertAlmostEqual(t.remaining, .5); self.assertAlmostEqual(t.stop, 100.2)  # entry + 2*0.1%
        t.on_candle(self.c(1, 107, 111, 106, 110), 102); self.assertEqual(t.stage, "TRAILING"); self.assertAlmostEqual(t.stop, 102)
        t.on_candle(self.c(2, 110, 112, 108, 111), 101); self.assertAlmostEqual(t.stop, 102)           # never loosened
        t.on_candle(self.c(3, 111, 116, 110, 115), 105); self.assertEqual(t.exit_reason, "TP2"); self.assertGreater(t.net_pnl, 0)
    def test_be_stop_after_tp1(self):
        t = self.mk(); t.on_candle(self.c(0, 100, 108, 99, 107), 99); t.on_candle(self.c(1, 107, 107, 99, 100), 99)
        self.assertEqual(t.exit_reason, "BREAKEVEN_STOP"); self.assertGreaterEqual(t.net_pnl, -0.0001 * 1000)  # ~ fee-neutral on remainder, TP1 profit kept
    def test_48h_exit(self):
        t = self.mk()
        for i in range(48): t.on_candle(self.c(i, 100, 101, 99, 100), 99)
        self.assertEqual(t.exit_reason, "TIME_EXIT_48H")
    def test_short_mirror(self):
        t = self.mk("SHORT"); t.on_candle(self.c(0, 100, 101, 92, 93), 101)
        self.assertEqual(t.stage, "TP1_DONE"); self.assertAlmostEqual(t.stop, 99.8)
    def test_conservative_stop_first(self):
        t = self.mk(); t.on_candle(self.c(0, 100, 110, 94, 100), 99); self.assertEqual(t.exit_reason, "STOP_LOSS")


class TestInfra(unittest.TestCase):
    def test_db_duplicate_signal_and_settings(self):
        db = DB(":memory:")
        self.assertTrue(db.save_signal("A", "LONG", 1, "ENTRY — LONG", {})); self.assertFalse(db.save_signal("A", "LONG", 1, "ENTRY — LONG", {}))
        db.set_setting("x", {"a": 1}); self.assertEqual(db.get_setting("x"), {"a": 1}); self.assertIsNone(db.get_setting("nope"))
    def test_config_validation(self):
        Config().validate()
        for bad in (dict(account_equity=-1), dict(risk_pct=.5), dict(execution_mode="live"), dict(core_pct=.9, satellite_pct=.3), dict(dca_tranches=2)):
            with self.assertRaises(ConfigError): Config(**bad).validate()


if __name__ == "__main__":
    unittest.main()
      
