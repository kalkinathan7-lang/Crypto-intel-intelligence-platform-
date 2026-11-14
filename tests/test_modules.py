"""All data here is SYNTHETIC TEST DATA."""
import asyncio, json, unittest
import numpy as np, pandas as pd
from investment.models import CoinData, completeness
from investment.agents import BullishAnalyst, BearishAnalyst, IndependentJudge, research
from investment.scoring import sub_scores, composite, rank
from investment.portfolio import allocate, dca_plan, exit_plan, risk_stats, zone_from_technicals
from investment.technical import technicals
from news.verify import process, similar, reliability
from tax.india import estimate
from futures.backtest import backtest
from futures.scanner import scan, evaluate_pair
from core.config import Config
from core.db import DB
from tests.test_futures import entry_long_frames, NOW, H


def daily(n=400, drift=0.002):
    t0 = 1_600_000_000_000
    px = 100 * np.cumprod(1 + drift + 0.01 * np.sin(np.arange(n)))
    return pd.DataFrame({"time": [t0 + i * 86_400_000 for i in range(n)], "close": px, "volume": [1e6] * n})


def strong():
    return CoinData("GOOD", "Good", price=110, market_cap=1.1e10, fdv=1.2e10, circulating=1e8, total_supply=1.05e8, max_supply=1.1e8, volume_24h=5e8,
                    unlock_next_12m_pct=2, protocol_revenue_30d=5e6, tvl_change_90d_pct=40, active_addr_change_90d_pct=30, top10_holder_pct=25,
                    audits=True, security_incident_12m=False, dev_activity_change_pct=20, regulatory_flag=False, daily=daily(), retrieved_ms=1)


def weak():
    return CoinData("BAD", "Bad", price=1, market_cap=1e8, fdv=9e8, circulating=1e7, total_supply=1e8, max_supply=1e8, volume_24h=1e5,
                    unlock_next_12m_pct=30, tvl_change_90d_pct=-50, active_addr_change_90d_pct=-40, top10_holder_pct=70, audits=False,
                    security_incident_12m=True, daily=daily(drift=-0.003), retrieved_ms=1)


class TestInvestment(unittest.TestCase):
    def test_buy(self):
        r = research(strong()); self.assertEqual(r["judge"]["decision"], "BUY"); self.assertEqual(r["judge"]["contradictions"], [])
    def test_avoid_critical(self):
        r = research(weak()); self.assertEqual(r["judge"]["decision"], "AVOID"); self.assertTrue(r["judge"]["critical_risks"])
    def test_wait_on_missing_data(self):
        r = research(CoinData("X", price=5)); self.assertEqual(r["judge"]["decision"], "WAIT")
        self.assertTrue(r["bullish"]["uncertainties"]); self.assertEqual(r["bullish"]["evidence"], [])     # missing != positive
    def test_wait_mixed(self):
        d = strong(); d.unlock_next_12m_pct = 12; d.top10_holder_pct = 60; d.tvl_change_90d_pct = None; d.active_addr_change_90d_pct = None
        self.assertIn(research(d)["judge"]["decision"], ("WAIT", "AVOID"))
    def test_judge_rejects_unsupported_claim(self):
        d = strong(); bull = BullishAnalyst().analyze(d); bear = BearishAnalyst().analyze(d)
        bear.evidence.append(__import__("investment.agents", fromlist=["Evidence"]).Evidence("fdv_mc", "FDV far above market cap", "9x", .7))   # false claim
        j = IndependentJudge().judge(d, bull, bear)
        self.assertTrue(any(e["key"] == "fdv_mc" for e in j["invalid_bearish"])); self.assertNotEqual(j["decision"], "AVOID")
    def test_judge_detects_inconsistent_data(self):
        d = strong(); d.market_cap = 5e9
        self.assertTrue(any("inconsistent" in n or "differs" in n for n in research(d)["judge"]["notes"]))
    def test_exactly_three_agents(self):
        r = research(strong()); self.assertEqual({r["bullish"]["agent"], r["bearish"]["agent"], r["judge"]["agent"]},
                                                  {"Bullish Research Analyst", "Bearish Research Analyst", "Independent Final Investment Judge"})
    def test_scoring_missing_not_good(self):
        s = sub_scores(CoinData("X", price=1)); self.assertTrue(all(v is None for v in s.values()))
        self.assertIsNone(composite(s, CoinData("X"))["score"])
        full = composite(sub_scores(strong()), strong()); part = composite(sub_scores(CoinData("P", price=1, circulating=1, total_supply=1)), CoinData("P"))
        self.assertGreater(full["score"], part["score"] if part["score"] is not None else -1); self.assertGreater(part["penalty"], full["penalty"])
    def test_ranking(self):
        items = []
        for d in (weak(), strong(), CoinData("X", price=1)):
            r = research(d); items.append(dict(symbol=d.symbol, judge=r["judge"], scores=sub_scores(d), composite=composite(sub_scores(d), d)))
        out = rank(items); self.assertEqual(out[0]["symbol"], "GOOD"); self.assertEqual(out[-1]["symbol"], "BAD")
    def test_technicals(self):
        t = technicals(daily()); self.assertIsNotNone(t["ma200d"]); self.assertIsNone(t["ma200w"]); self.assertIsNone(technicals(None)["ma200d"])
    def test_completeness(self):
        self.assertGreater(completeness(strong()), .9); self.assertEqual(completeness(CoinData("X")), 0)


class TestPortfolio(unittest.TestCase):
    def test_allocate(self):
        a = allocate(10000, ["BTC", "ETH"], ["A", "B"], .65, .35); self.assertAlmostEqual(sum(a["allocation"].values()), 10000)
        e = allocate(10000, [], ["A"]); self.assertAlmostEqual(e["unallocated"], 6500); self.assertTrue(e["warnings"])
    def test_dca(self):
        p = dca_plan(100, 80, 95, 1000, 5); self.assertEqual(len(p["tranches"]), 5); self.assertAlmostEqual(sum(t["allocation"] for t in p["tranches"]), 1000)
        self.assertFalse(dca_plan(100, None, None, 1000)["active"]); self.assertFalse(dca_plan(100, 80, 95, 1000, thesis_ok=False)["active"])
    def test_exit(self):
        p = exit_plan(100, 10, 150); self.assertAlmostEqual(p["unrealised"], 500); self.assertAlmostEqual(p["levels"][0]["remaining_qty"], 7.5)
        self.assertAlmostEqual(p["levels"][-1]["remaining_qty"], 0.0)
    def test_zone_never_invented(self):
        self.assertEqual(zone_from_technicals(100, dict(ma200d=None, ma200w=None)), (None, None))
    def test_risk_stats(self):
        self.assertFalse(risk_stats({"A": pd.Series(range(5)), "B": pd.Series(range(5))}, {"A": .5, "B": .5})["available"])
        s = pd.Series(np.cumprod(1 + np.random.default_rng(1).normal(0, .02, 100)) * 100)
        self.assertTrue(risk_stats({"A": s, "B": s * 1.1}, {"A": .5, "B": .5})["available"])


class TestNewsTax(unittest.TestCase):
    NOW = 1_700_000_000_000
    def it(self, h, url, age_d=1, **k): return dict(headline=h, url=url, published_ms=self.NOW - int(age_d * 86_400_000), **k)
    def test_verification_labels(self):
        out = process([self.it("Exchange X lists token Y", "https://www.coindesk.com/a"), self.it("Exchange X lists token Y today", "https://www.reuters.com/b"),
                       self.it("Token Z rumour reportedly hacked", "https://someblog.xyz/c"), self.it("Old story about thing", "https://www.reuters.com/d", age_d=60),
                       self.it("SEC statement on token Q", "https://www.sec.gov/e")], self.NOW)
        by = {o["headline"]: o for o in out}
        self.assertEqual(by["Exchange X lists token Y"]["verification"], "VERIFIED"); self.assertEqual(by["Token Z rumour reportedly hacked"]["verification"], "UNVERIFIED")
        self.assertEqual(by["Old story about thing"]["verification"], "OUTDATED"); self.assertEqual(by["SEC statement on token Q"]["verification"], "VERIFIED")
        self.assertEqual(by["Exchange X lists token Y today"]["duplicate"], "DUPLICATE/SYNDICATED")
    def test_conflicting(self):
        out = process([self.it("Project A audit passes", "https://www.coindesk.com/1", claim_polarity="up"), self.it("Project A audit fails", "https://www.reuters.com/2", claim_polarity="down")], self.NOW, sim_threshold=.4)
        self.assertTrue(all(o["verification"] == "CONFLICTING" for o in out))
    def test_helpers(self): self.assertGreater(similar("a b c", "a b d"), .4); self.assertEqual(reliability("https://x.io/a"), "UNKNOWN")
    def test_tax(self):
        r = estimate([dict(asset="A", buy_cost=100, sell_value=200), dict(asset="B", buy_cost=100, sell_value=50)],
                     dict(vda_tax_rate=.3, cess_rate=.04, tds_194s_rate=.01, loss_offset_allowed=False, last_verified=None))
        self.assertAlmostEqual(r["estimated_tax"], 100 * .3 * 1.04); self.assertAlmostEqual(r["unusable_losses"], 50); self.assertFalse(r["rules_verified"])


class FakeClient:
    """Test double returning SYNTHETIC candles; counts calls."""
    def __init__(self, bad=()): self.bad = set(bad); self.cfg = Config()
    async def discover(self): return ["A_USDT", "B_USDT", "BAD_USDT"]
    async def funding_all(self): return {"A_USDT": (0.0001, 8.0), "B_USDT": (0.0001, 8.0), "BAD_USDT": (0.0001, 8.0)}
    async def instrument(self, pair): return dict(min_qty=0.001, qty_step=0.001, max_leverage=10)
    async def candles(self, pair, res, limit, now_ms):
        if pair == "BAD_USDT": raise RuntimeError("boom")
        d1, d4 = entry_long_frames(); return d1 if res == "1h" else d4


class TestScannerBacktest(unittest.TestCase):
    def test_scanner_reports_honest_coverage_and_dedupes(self):
        db = DB(":memory:"); cfg = Config(); cfg.leverage = 10
        r = asyncio.run(scan(FakeClient(), cfg, db, now_ms=NOW)); s = r["summary"]
        self.assertEqual(s["eligible"], 3); self.assertEqual(s["failed_fetch"], 1); self.assertEqual(s["analysed"], 2)
        self.assertEqual(s["counts"]["ENTRY — LONG"], 2); self.assertEqual(len(db.q("SELECT * FROM signals")), 2)
        asyncio.run(scan(FakeClient(), cfg, db, now_ms=NOW)); self.assertEqual(len(db.q("SELECT * FROM signals")), 2)       # no duplicate signals
        self.assertEqual(len(db.q("SELECT * FROM failures")), 2)
    def test_scanner_and_coin_page_same_engine(self):
        cfg = Config(); c = FakeClient(); f = asyncio.run(c.funding_all())
        a1 = asyncio.run(evaluate_pair(c, cfg, "A_USDT", f, NOW)); r = asyncio.run(scan(c, cfg, None, now_ms=NOW))
        a2 = next(x for x in r["results"] if x.symbol == "A_USDT"); self.assertEqual(a1.status, a2.status); self.assertEqual(a1.plan["sl"], a2.plan["sl"])
    def test_sizing_rejection_downgrades_signal(self):
        class NoSpec(FakeClient):
            async def instrument(self, p): return None
        a = asyncio.run(evaluate_pair(NoSpec(), Config(), "A_USDT", {"A_USDT": (0.0001, 8)}, NOW)); self.assertEqual(a.status, "NO SIGNAL")
    def test_backtest_runs_no_lookahead_shape(self):
        d1, d4 = entry_long_frames(); r = backtest("T", d1, d4, start_index=100)
        self.assertIn("metrics", r); self.assertIn("assumptions", r); self.assertGreaterEqual(r["metrics"].get("total_trades", 0), 0)


if __name__ == "__main__":
    unittest.main()
