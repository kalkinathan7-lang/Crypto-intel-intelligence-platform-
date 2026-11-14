"""Daily/weekly long-term technical metrics. Returns None for anything that cannot be computed from available history."""
from __future__ import annotations
import pandas as pd
from futures.indicators import rsi


def technicals(daily: pd.DataFrame | None) -> dict:
    out = dict(ma200d=None, ma200w=None, weekly_rsi=None, structure=None, price_vs_200d=None, drawdown_from_high=None)
    if daily is None or len(daily) < 30:
        return out
    d = daily.sort_values("time").copy()
    d["dt"] = pd.to_datetime(d["time"], unit="ms")
    c = d["close"].astype(float)
    last = float(c.iloc[-1])
    if len(c) >= 200:
        out["ma200d"] = float(c.tail(200).mean()); out["price_vs_200d"] = last / out["ma200d"] - 1
    w = d.set_index("dt")["close"].astype(float).resample("W").last().dropna()
    if len(w) >= 200: out["ma200w"] = float(w.tail(200).mean())
    if len(w) >= 15: out["weekly_rsi"] = float(rsi(w, 14).iloc[-1])
    out["drawdown_from_high"] = last / float(c.max()) - 1
    if len(w) >= 26:                                      # crude structure: compare last two 13-week windows
        a, b = w.tail(13), w.tail(26).head(13)
        hh, hl = a.max() > b.max(), a.min() > b.min()
        lh, ll = a.max() < b.max(), a.min() < b.min()
        out["structure"] = "higher highs/higher lows" if hh and hl else "lower highs/lower lows" if lh and ll else "mixed/range"
    return out
