"""Human-readable explanation generated from the Analysis object (never recomputes strategy)."""
from __future__ import annotations
from .strategy import Analysis


def explain(a: Analysis) -> str:
    L = [f"### {a.symbol} — {a.status}"]
    L += [f"- {r}" for r in a.reasons]
    if a.metrics:
        m = a.metrics
        L.append(f"\nPrice {m['close']:.6g} | 4H EMA50 {m['ema50_4h']:.6g} EMA200 {m['ema200_4h']:.6g} ATR14 {m['atr4h']:.6g} | "
                 f"1H EMA21 {m['ema21_1h']:.6g} RSI {m['rsi']:.2f} (prev {m['rsi_prev']:.2f}) ATR14 {m['atr1h']:.6g} | "
                 f"Vol {m['volume']:.6g} / SMA20 {m['vol_sma20']:.6g} | Funding {m['funding_pct']:.4f}% (interval {m['funding_interval_h']}h)")
    for title, conds in (("LONG conditions", a.long_conds), ("SHORT conditions", a.short_conds)):
        if conds:
            L.append(f"\n**{title}**")
            for c in conds:
                L.append(f"- {'PASS' if c.passed else 'FAIL'} · {c.id}. {c.name} — value: {c.value}; required: {c.threshold}. {c.explanation}")
    p = a.plan
    if p:
        if p.get("valid"):
            L.append(f"\n**Plan** entry {p['entry']:.6g}, SL {p['sl']:.6g} (R={p['R']:.6g}, {p['sl_atr_multiple']:.2f}x ATR), "
                     f"TP1 {p['tp1']:.6g}, TP2 {p['tp2']:.6g}, R:R(TP2) {p['rr_tp2']:.2f}")
        else:
            L.append(f"\n**Plan rejected:** {p.get('reject')}")
    return "\n".join(L)
