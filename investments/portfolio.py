"""Core-satellite allocation, DCA tranches, staggered exits, concentration/volatility/correlation."""
from __future__ import annotations
import math
import pandas as pd


def allocate(capital: float, core: list[str], satellite: list[str], core_pct=0.65, sat_pct=0.35, vol: dict | None = None) -> dict:
    """Core/satellite split; inside buckets inverse-volatility weights if vol given else equal. Empty bucket => cash stays unallocated."""
    out, warnings = {}, []
    for names, pct in ((core, core_pct), (satellite, sat_pct)):
        if not names:
            warnings.append(f"No eligible holdings for a {pct:.0%} bucket - left unallocated (not forced)."); continue
        w = {n: 1 / vol[n] for n in names if vol and vol.get(n)} or {n: 1.0 for n in names}
        s = sum(w.values())
        for n in names: out[n] = capital * pct * w[n] / s
    for n, v in out.items():
        if v / capital > 0.4: warnings.append(f"Concentration warning: {n} is {v / capital:.0%} of capital")
    if len(satellite) > 6: warnings.append("More than 6 satellite holdings - diluted conviction")
    return dict(allocation=out, unallocated=capital - sum(out.values()), warnings=warnings)


def risk_stats(prices: dict[str, pd.Series], weights: dict[str, float]) -> dict:
    """Daily-close series per coin -> volatility, max drawdown, correlation matrix (None if < 30 aligned points)."""
    df = pd.DataFrame(prices).dropna()
    if len(df) < 30: return dict(available=False, reason="fewer than 30 aligned daily observations")
    r = df.pct_change().dropna()
    w = pd.Series({k: weights[k] for k in df.columns}); w /= w.sum()
    port = (r * w).sum(axis=1)
    curve = (1 + port).cumprod()
    return dict(available=True, annual_vol=float(port.std() * math.sqrt(365)), max_drawdown=float((curve / curve.cummax() - 1).min()),
                correlation=r.corr().round(2).to_dict(), observations=len(r))


def dca_plan(price: float, zone_low: float | None, zone_high: float | None, capital: float, tranches: int = 5, thesis_ok: bool = True) -> dict:
    if not thesis_ok: return dict(active=False, message="Accumulation paused: fundamental thesis deteriorated.")
    if zone_low is None or zone_high is None or zone_low >= zone_high:
        return dict(active=False, message="No justified accumulation zone is currently available.")
    step = (zone_high - zone_low) / max(tranches - 1, 1)
    rows = []
    for i in range(tranches):
        px = zone_high - i * step
        rows.append(dict(tranche=i + 1, allocation=capital / tranches, entry=round(px, 8), distance_pct=round((px / price - 1) * 100, 2)))
    return dict(active=True, tranches=rows, note="Reaching a tranche price is not an instruction to buy; re-check thesis first.")


def exit_plan(avg_price: float, qty: float, price: float, levels=(0.5, 1.0, 2.0, 3.0), sell_pct=0.25) -> dict:
    invested, value = avg_price * qty, price * qty
    rows, remaining = [], qty
    for lv in levels:
        if remaining <= 1e-12: break
        sell = min(qty * sell_pct, remaining); remaining -= sell
        px = avg_price * (1 + lv)
        rows.append(dict(profit_level=f"+{lv:.0%}", price=px, sell_qty=sell, sell_pct_of_original=sell / qty, remaining_qty=remaining,
                         remaining_value_at_level=remaining * px))
    return dict(invested=invested, value=value, unrealised=value - invested, unrealised_pct=(value / invested - 1) if invested else None, levels=rows,
                note="Levels are illustrative; override when thesis/market conditions justify. Taxes/fees not included.")


def zone_from_technicals(price: float, t: dict) -> tuple | tuple[None, None]:
    """Accumulation zone ONLY from computed support references (200d MA / 200w MA); otherwise None - never invented."""
    refs = [x for x in (t.get("ma200d"), t.get("ma200w")) if x]
    if not refs: return (None, None)
    lo, hi = min(refs) * 0.95, max(min(refs) * 1.05, min(max(refs), price))
    return (lo, hi) if lo < hi < price * 1.0001 else (None, None)
