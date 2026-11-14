"""EXACTLY THREE independent agents for the long-term module: BullishAnalyst, BearishAnalyst, IndependentJudge.
Release 1 agents are DETERMINISTIC evidence engines (no LLM). Each agent reads raw CoinData itself; the judge never trusts
agent output - it re-derives every claim from raw data via its own verifier table and can reject both sides.
Missing data is reported as an uncertainty, never as positive or negative evidence."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
from .models import CoinData, completeness
from .technical import technicals

STALE_MS = 7 * 86_400_000


@dataclass
class Evidence:
    key: str
    claim: str
    value: str
    strength: float            # 0-1 agent-assigned weight
    critical: bool = False
    source: str = ""


@dataclass
class AgentReport:
    agent: str
    thesis: str
    evidence: list
    uncertainties: list
    confidence: float
    retrieved_ms: Optional[int]
    sources: list = field(default_factory=list)

    def to_dict(self): return asdict(self)


def _src(d: CoinData, *fields_):
    s = {d.sources.get(f, {}).get("source") for f in fields_ if d.sources.get(f)}
    return ", ".join(sorted(x for x in s if x)) or "unspecified"


def _ratio(a, b):
    return None if a is None or b in (None, 0) else a / b


class BullishAnalyst:
    name = "Bullish Research Analyst"

    def analyze(self, d: CoinData) -> AgentReport:
        ev, unc, t = [], [], technicals(d.daily)
        circ_max = _ratio(d.circulating, d.max_supply or d.total_supply)
        if circ_max is not None and circ_max >= 0.7:
            ev.append(Evidence("circ_ratio", "Most supply already circulating (limited dilution)", f"{circ_max:.0%}", .6, source=_src(d, "circulating")))
        fdv_mc = _ratio(d.fdv, d.market_cap)
        if fdv_mc is not None and fdv_mc <= 1.5:
            ev.append(Evidence("fdv_mc", "FDV close to market cap", f"{fdv_mc:.2f}x", .5, source=_src(d, "fdv")))
        if d.tvl_change_90d_pct is not None and d.tvl_change_90d_pct > 10:
            ev.append(Evidence("tvl", "TVL growing", f"{d.tvl_change_90d_pct:+.1f}% / 90d", .6, source=_src(d, "tvl_change_90d_pct")))
        if d.active_addr_change_90d_pct is not None and d.active_addr_change_90d_pct > 10:
            ev.append(Evidence("addr", "Active addresses growing", f"{d.active_addr_change_90d_pct:+.1f}% / 90d", .6, source=_src(d, "active_addr_change_90d_pct")))
        if d.protocol_revenue_30d and d.protocol_revenue_30d > 0:
            ev.append(Evidence("rev", "Protocol generates revenue (note: not necessarily token-holder revenue)", f"{d.protocol_revenue_30d:,.0f} / 30d", .5, source=_src(d, "protocol_revenue_30d")))
        if d.audits:
            ev.append(Evidence("audit", "Independent audit reported", "yes", .4, source=_src(d, "audits")))
        if d.dev_activity_change_pct is not None and d.dev_activity_change_pct > 10:
            ev.append(Evidence("dev", "Developer activity rising", f"{d.dev_activity_change_pct:+.1f}%", .4, source=_src(d, "dev_activity_change_pct")))
        if t["price_vs_200d"] is not None and t["price_vs_200d"] > 0:
            ev.append(Evidence("above200d", "Price above 200-day MA", f"{t['price_vs_200d']:+.1%}", .5, source="daily candles"))
        if t["weekly_rsi"] is not None and t["weekly_rsi"] < 40:
            ev.append(Evidence("wrsi", "Weekly RSI low - possible accumulation area (not proof of value)", f"{t['weekly_rsi']:.1f}", .3, source="daily candles"))
        if t["structure"] == "higher highs/higher lows":
            ev.append(Evidence("struct", "Higher-high/higher-low weekly structure", t["structure"], .5, source="daily candles"))
        for k, label in [("tvl_change_90d_pct", "TVL trend"), ("active_addr_change_90d_pct", "on-chain activity"), ("unlock_next_12m_pct", "unlock schedule"),
                         ("protocol_revenue_30d", "protocol revenue"), ("audits", "audit status")]:
            if getattr(d, k) is None: unc.append(f"{label} unavailable - not counted as evidence")
        if not ev: thesis = "No verifiable bullish evidence found in available data."
        else: thesis = f"{len(ev)} verifiable supporting factor(s): " + "; ".join(e.claim for e in ev[:3])
        conf = min(1.0, completeness(d) * (0.5 + 0.5 * min(1, sum(e.strength for e in ev) / 3)))
        return AgentReport(self.name, thesis, ev, unc, round(conf, 2), d.retrieved_ms, sorted({e.source for e in ev}))


class BearishAnalyst:
    name = "Bearish Research Analyst"

    def analyze(self, d: CoinData) -> AgentReport:
        ev, unc, t = [], [], technicals(d.daily)
        fdv_mc = _ratio(d.fdv, d.market_cap)
        if fdv_mc is not None and fdv_mc > 3:
            ev.append(Evidence("fdv_mc", "FDV far above market cap (large future dilution)", f"{fdv_mc:.1f}x", .7, source=_src(d, "fdv")))
        circ_max = _ratio(d.circulating, d.max_supply or d.total_supply)
        if circ_max is not None and circ_max < 0.4:
            ev.append(Evidence("circ_ratio", "Low circulating share of supply", f"{circ_max:.0%}", .6, source=_src(d, "circulating")))
        if d.unlock_next_12m_pct is not None and d.unlock_next_12m_pct > 10:
            ev.append(Evidence("unlock", "Large unlocks next 12 months (selling pressure risk)", f"{d.unlock_next_12m_pct:.1f}% of supply", .7, source=_src(d, "unlock_next_12m_pct")))
        if d.tvl_change_90d_pct is not None and d.tvl_change_90d_pct < -20:
            ev.append(Evidence("tvl", "TVL declining", f"{d.tvl_change_90d_pct:+.1f}% / 90d", .6, source=_src(d, "tvl_change_90d_pct")))
        if d.active_addr_change_90d_pct is not None and d.active_addr_change_90d_pct < -20:
            ev.append(Evidence("addr", "Active addresses declining", f"{d.active_addr_change_90d_pct:+.1f}% / 90d", .6, source=_src(d, "active_addr_change_90d_pct")))
        if d.top10_holder_pct is not None and d.top10_holder_pct > 50:
            ev.append(Evidence("conc", "Concentrated ownership (distinct exchange wallets not verified)", f"top10 {d.top10_holder_pct:.0f}%", .5, source=_src(d, "top10_holder_pct")))
        if d.audits is False:
            ev.append(Evidence("audit", "No independent audit reported", "no", .5, source=_src(d, "audits")))
        if d.security_incident_12m:
            ev.append(Evidence("sec", "Security incident in last 12 months", "yes", .9, critical=True, source=_src(d, "security_incident_12m")))
        if d.regulatory_flag:
            ev.append(Evidence("reg", "Regulatory action/uncertainty flagged", "yes", .6, source=_src(d, "regulatory_flag")))
        liq = _ratio(d.volume_24h, d.market_cap)
        if liq is not None and liq < 0.01:
            ev.append(Evidence("liq", "Poor liquidity relative to market cap", f"vol/mcap {liq:.2%}", .5, source=_src(d, "volume_24h")))
        if t["price_vs_200d"] is not None and t["price_vs_200d"] < 0:
            ev.append(Evidence("below200d", "Price below 200-day MA", f"{t['price_vs_200d']:+.1%}", .4, source="daily candles"))
        if t["structure"] == "lower highs/lower lows":
            ev.append(Evidence("struct", "Lower-high/lower-low weekly structure", t["structure"], .5, source="daily candles"))
        if t["drawdown_from_high"] is not None and t["drawdown_from_high"] > -0.1 and (t["weekly_rsi"] or 0) > 75:
            ev.append(Evidence("overheat", "Overheated weekly RSI near highs", f"{t['weekly_rsi']:.0f}", .4, source="daily candles"))
        for k, label in [("unlock_next_12m_pct", "unlock schedule"), ("top10_holder_pct", "holder concentration"),
                         ("security_incident_12m", "security incident history"), ("regulatory_flag", "regulatory status")]:
            if getattr(d, k) is None: unc.append(f"{label} unavailable - risk cannot be ruled out")
        thesis = "No verifiable bearish evidence found in available data (this is not proof of safety)." if not ev else \
                 f"{len(ev)} verifiable risk factor(s): " + "; ".join(e.claim for e in ev[:3])
        conf = min(1.0, completeness(d) * (0.5 + 0.5 * min(1, sum(e.strength for e in ev) / 3)))
        return AgentReport(self.name, thesis, ev, unc, round(conf, 2), d.retrieved_ms, sorted({e.source for e in ev}))


class IndependentJudge:
    """Re-verifies every claim from raw data with its OWN verifier table, then decides BUY/WAIT/AVOID."""
    name = "Independent Final Investment Judge"

    def _verify(self, key: str, d: CoinData) -> Optional[bool]:
        """True/False if verifiable from raw data, None if raw data missing."""
        t = technicals(d.daily)
        den = d.max_supply or d.total_supply
        checks = {
            "circ_ratio": lambda: None if d.circulating is None or not den else d.circulating / den,
            "fdv_mc": lambda: None if d.fdv is None or not d.market_cap else d.fdv / d.market_cap,
        }
        if key in ("circ_ratio", "fdv_mc"):
            v = checks[key]()
            return None if v is None else True  # value existence verified; thresholds are checked below
        raw = {"tvl": d.tvl_change_90d_pct, "addr": d.active_addr_change_90d_pct, "rev": d.protocol_revenue_30d,
               "audit": d.audits, "dev": d.dev_activity_change_pct, "unlock": d.unlock_next_12m_pct, "conc": d.top10_holder_pct,
               "sec": d.security_incident_12m, "reg": d.regulatory_flag, "liq": d.volume_24h,
               "above200d": t["price_vs_200d"], "below200d": t["price_vs_200d"], "wrsi": t["weekly_rsi"],
               "struct": t["structure"], "overheat": t["weekly_rsi"]}
        return None if raw.get(key) is None else True

    def _recheck_thresholds(self, key: str, d: CoinData) -> bool:
        t = technicals(d.daily); den = d.max_supply or d.total_supply
        f = {
            "circ_ratio": lambda: d.circulating / den >= 0.7 if (d.circulating and den) else False,
            "fdv_mc": lambda: d.fdv / d.market_cap > 3 if (d.fdv and d.market_cap) else False,
        }
        return f[key]() if key in f else True

    def judge(self, d: CoinData, bull: AgentReport, bear: AgentReport) -> dict:
        comp, notes = completeness(d), []
        stale = d.retrieved_ms is not None and d.retrieved_ms < 0
        valid_b, invalid_b, valid_r, invalid_r = [], [], [], []
        # circ_ratio & fdv_mc appear on both sides with opposite thresholds -> contradiction check
        for e in bull.evidence:
            ok = self._verify(e.key, d)
            if e.key == "circ_ratio": ok = ok and self._recheck_thresholds("circ_ratio", d)
            if e.key == "fdv_mc": ok = ok and bool(d.fdv and d.market_cap and d.fdv / d.market_cap <= 1.5)
            (valid_b if ok else invalid_b).append(e)
        for e in bear.evidence:
            ok = self._verify(e.key, d)
            if e.key == "fdv_mc": ok = ok and self._recheck_thresholds("fdv_mc", d)
            if e.key == "circ_ratio": ok = ok and bool(d.circulating and (d.max_supply or d.total_supply) and d.circulating / (d.max_supply or d.total_supply) < 0.4)
            (valid_r if ok else invalid_r).append(e)
        contradictions = [k for k in {e.key for e in valid_b} & {e.key for e in valid_r}]
        if d.market_cap and d.circulating and d.price:
            calc = d.circulating * d.price
            if abs(calc - d.market_cap) / d.market_cap > 0.05:
                notes.append(f"Provider market cap differs from price x circulating by {abs(calc - d.market_cap) / d.market_cap:.0%} - data inconsistency")
        if d.fdv and d.market_cap and d.fdv < d.market_cap * 0.99:
            notes.append("FDV < market cap: inconsistent data")
        critical = [e for e in valid_r if e.critical]
        bull_score = sum(e.strength for e in valid_b)
        bear_score = sum(e.strength for e in valid_r)
        notes += [f"Rejected unverifiable/incorrect bullish claim: {e.claim}" for e in invalid_b]
        notes += [f"Rejected unverifiable/incorrect bearish claim: {e.claim}" for e in invalid_r]
        # Decision logic (documented in docs/AGENTS.md)
        if critical:
            decision, why = "AVOID", "Critical verified risk: " + "; ".join(e.claim for e in critical)
        elif comp < 0.4 or d.price is None:
            decision, why = "WAIT", f"Insufficient evidence (data completeness {comp:.0%}); need more research before any BUY."
        elif bear_score > bull_score + 0.5 or bear_score >= 2.0:
            decision, why = "AVOID", f"Verified risks outweigh verified strengths (bear {bear_score:.1f} vs bull {bull_score:.1f})."
        elif bull_score >= 2.0 and bear_score < 1.0 and comp >= 0.6 and not stale:
            decision, why = "BUY", f"Verified strengths ({bull_score:.1f}) clearly exceed verified risks ({bear_score:.1f}) with adequate data ({comp:.0%})."
        else:
            decision, why = "WAIT", f"Mixed or incomplete evidence (bull {bull_score:.1f}, bear {bear_score:.1f}, completeness {comp:.0%}); valuation/timing not compelling."
        t = technicals(d.daily)
        return dict(agent=self.name, decision=decision, rationale=why, valid_bullish=[asdict(e) for e in valid_b],
                    invalid_bullish=[asdict(e) for e in invalid_b], valid_bearish=[asdict(e) for e in valid_r],
                    invalid_bearish=[asdict(e) for e in invalid_r], contradictions=contradictions, notes=notes,
                    technical=t, data_completeness=round(comp, 2), critical_risks=[e.claim for e in critical],
                    invalidation=["Verified security incident", "Material tokenomics change (unlock/inflation)", "Sustained decline in on-chain activity",
                                  "Weekly close below 200-week MA (if available) with deteriorating fundamentals"],
                    disclaimer="Not investment advice. No returns are guaranteed.")


def research(d: CoinData) -> dict:
    """Runs the three agents in order; bull/bear never see each other's output."""
    bull, bear = BullishAnalyst().analyze(d), BearishAnalyst().analyze(d)
    return {"symbol": d.symbol, "bullish": bull.to_dict(), "bearish": bear.to_dict(), "judge": IndependentJudge().judge(d, bull, bear)}
    
