"""Transparent scoring. Each sub-score 0-100 or None (unavailable). Missing data is never scored as good.
Composite = weighted mean of AVAILABLE scores minus a missing-data penalty (up to 30 pts), see docs/AGENTS.md."""
from __future__ import annotations
from .models import CoinData, completeness
from .technical import technicals

WEIGHTS = dict(fundamental=.2, tokenomics=.2, onchain=.15, technical=.15, adoption=.1, security=.1, news=.1)
clip = lambda x: max(0.0, min(100.0, x))


def _avg(parts):
    p = [x for x in parts if x is not None]
    return round(sum(p) / len(p), 1) if p else None


def sub_scores(d: CoinData) -> dict:
    t = technicals(d.daily)
    den = d.max_supply or d.total_supply
    circ = d.circulating / den if d.circulating and den else None
    fdv = d.fdv / d.market_cap if d.fdv and d.market_cap else None
    tok = _avg([None if circ is None else clip(circ * 100),
                None if fdv is None else clip(110 - 25 * fdv),
                None if d.unlock_next_12m_pct is None else clip(100 - 5 * d.unlock_next_12m_pct),
                None if d.top10_holder_pct is None else clip(130 - d.top10_holder_pct)])
    onc = _avg([None if d.tvl_change_90d_pct is None else clip(50 + d.tvl_change_90d_pct),
                None if d.active_addr_change_90d_pct is None else clip(50 + d.active_addr_change_90d_pct)])
    tech = _avg([None if t["price_vs_200d"] is None else clip(50 + 100 * t["price_vs_200d"]),
                 None if t["structure"] is None else {"higher highs/higher lows": 80, "mixed/range": 50, "lower highs/lower lows": 20}[t["structure"]],
                 None if t["weekly_rsi"] is None else clip(100 - abs(t["weekly_rsi"] - 50) * 1.5)])
    sec = _avg([None if d.audits is None else (80 if d.audits else 30),
                None if d.security_incident_12m is None else (10 if d.security_incident_12m else 90)])
    ful = _avg([None if d.protocol_revenue_30d is None else (70 if d.protocol_revenue_30d > 0 else 30),
                None if d.dev_activity_change_pct is None else clip(50 + d.dev_activity_change_pct)])
    adopt = None if d.active_addr_change_90d_pct is None else clip(50 + d.active_addr_change_90d_pct)
    liq = d.volume_24h / d.market_cap if d.volume_24h and d.market_cap else None
    risk = _avg([None if liq is None else clip(liq * 2000), None if d.regulatory_flag is None else (20 if d.regulatory_flag else 80)])
    return dict(fundamental=ful, tokenomics=tok, onchain=onc, technical=tech, adoption=adopt, security=sec,
                news=None, risk=risk)   # news score requires verified news feed; unavailable => None


def composite(scores: dict, d: CoinData) -> dict:
    avail = {k: v for k, v in scores.items() if k in WEIGHTS and v is not None}
    if not avail:
        return dict(score=None, coverage=0.0, penalty=30.0)
    w = sum(WEIGHTS[k] for k in avail)
    raw = sum(WEIGHTS[k] * v for k, v in avail.items()) / w
    cov = w / sum(WEIGHTS.values())
    penalty = (1 - min(cov, completeness(d))) * 30
    return dict(score=round(max(0, raw - penalty), 1), raw=round(raw, 1), coverage=round(cov, 2), penalty=round(penalty, 1))


DECISION_RANK = {"BUY": 0, "WAIT": 1, "AVOID": 2}


def rank(items: list[dict]) -> list[dict]:
    """items: dict(symbol, judge, scores, composite). Sort by decision tier, then score; unscored last. Evidence quality first."""
    key = lambda x: (DECISION_RANK[x["judge"]["decision"]], -(x["composite"]["score"] or -1), -x["judge"]["data_completeness"])
    out = sorted(items, key=key)
    for i, x in enumerate(out, 1): x["rank"] = i
    return out
