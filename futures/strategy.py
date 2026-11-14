"""THE single futures analysis engine. Used by the scanner AND the single-coin page.
Strategy: Multi-Timeframe EMA Trend Pullback + RSI & Volume Confirmation (spec sections 4-7)."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
import pandas as pd
from .indicators import ema, rsi, atr, sma
from .validation import validate_candles, IV_MS

FUNDING_LIMIT = 0.0003   # 0.03% expressed as a DECIMAL fraction
WAIT_MIN_PASSED = 4      # documented WAIT definition: macro trend passes AND >=4 of 6 conditions pass


@dataclass
class Cond:
    id: int
    name: str
    passed: bool
    value: str
    threshold: str
    explanation: str


@dataclass
class Analysis:
    symbol: str
    status: str                      # ENTRY — LONG | ENTRY — SHORT | WAIT | NO SIGNAL | DATA UNAVAILABLE
    direction: Optional[str] = None
    price: Optional[float] = None
    signal_candle_ms: Optional[int] = None
    data_ts_ms: Optional[int] = None
    metrics: dict = field(default_factory=dict)
    long_conds: list = field(default_factory=list)
    short_conds: list = field(default_factory=list)
    plan: Optional[dict] = None
    reasons: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _fmt(x, p=6):
    return "n/a" if x is None else f"{x:.{p}g}"


def candle_ratio(o, h, l, c) -> Optional[float]:
    if h - l <= 0:
        return None
    return (c - l) / (h - l)


def build_plan(direction: str, entry: float, d1: pd.DataFrame, d4: pd.DataFrame, atr1: float, atr4: float) -> dict:
    """SL/TP per spec sections 6-7. Returns {'valid': bool, 'reject': reason, ...}."""
    out: dict = {"valid": False, "direction": direction, "entry": entry}
    vals = [entry, atr1, atr4]
    if any(v is None or pd.isna(v) or v <= 0 for v in vals) or len(d1) < 12 or len(d4) < 50:
        out["reject"] = "Missing/invalid data for SL/TP calculation"
        return out
    last12, last50 = d1.tail(12), d4.tail(50)
    long = direction == "LONG"
    if long:
        swing = float(last12["low"].min()); sl = swing - 0.5 * atr1
        resist = float(last50["high"].max())
    else:
        swing = float(last12["high"].max()); sl = swing + 0.5 * atr1
        support = float(last50["low"].min())
    if (long and sl >= entry) or (not long and sl <= entry):
        out["reject"] = "Stop-loss on wrong side of entry"; return out
    R = abs(entry - sl)
    out.update(swing=swing, sl=sl, R=R, sl_atr_multiple=R / atr1)
    if R < 0.8 * atr1 or R > 3.5 * atr1:
        out["reject"] = f"SL distance {R / atr1:.2f}x ATR outside [0.8, 3.5]"; return out
    if long:
        tp1, base2 = entry + 1.5 * R, entry + 3 * R
        tp2 = min(base2, resist - 0.25 * atr4); out.update(major_level=resist, base_tp2=base2)
        ok_side = tp1 > entry and tp2 > entry
    else:
        tp1, base2 = entry - 1.5 * R, entry - 3 * R
        tp2 = max(base2, support + 0.25 * atr4); out.update(major_level=support, base_tp2=base2)
        ok_side = tp1 < entry and tp2 < entry
    out.update(tp1=tp1, tp2=tp2)
    rr = abs(tp2 - entry) / R
    out["rr_tp2"] = rr
    if not ok_side:
        out["reject"] = "TP on wrong side of entry after S/R adjustment"; return out
    if rr < 2.0:
        out["reject"] = f"Final TP2 gives only {rr:.2f}R (< 2R) after major S/R adjustment"; return out
    if not ((tp1 < tp2) if long else (tp1 > tp2)):
        out["reject"] = "Target ordering invalid (TP1 must come before TP2)"; return out
    out["valid"] = True
    return out


def analyze(symbol: str, df1h, df4h, funding_rate: Optional[float], funding_interval_h: Optional[float],
            now_ms: int) -> Analysis:
    """funding_rate must be a DECIMAL fraction (0.0001 = 0.01%)."""
    a = Analysis(symbol=symbol, status="DATA UNAVAILABLE")
    d1, i1 = validate_candles(df1h, "1h", now_ms, 60)
    d4, i4 = validate_candles(df4h, "4h", now_ms, 250)
    issues = i1 + i4
    if funding_rate is None or pd.isna(funding_rate):
        issues.append("Funding rate unavailable")
    if issues:
        a.reasons = issues
        return a
    e50, e200, a4 = ema(d4["close"], 50), ema(d4["close"], 200), atr(d4, 14)
    e21, r1, a1, vs = ema(d1["close"], 21), rsi(d1["close"], 14), atr(d1, 14), sma(d1["volume"], 20)
    cur, prev = d1.iloc[-1], d1.iloc[-2]
    m = dict(close4=float(d4["close"].iloc[-1]), ema50_4h=e50.iloc[-1], ema200_4h=e200.iloc[-1], atr4h=a4.iloc[-1],
             ema21_1h=e21.iloc[-1], ema21_1h_prev=e21.iloc[-2], rsi=r1.iloc[-1], rsi_prev=r1.iloc[-2], atr1h=a1.iloc[-1],
             volume=float(cur["volume"]), vol_sma20=vs.iloc[-1], funding_rate=funding_rate,
             funding_pct=funding_rate * 100, funding_interval_h=funding_interval_h,
             open=float(cur["open"]), high=float(cur["high"]), low=float(cur["low"]), close=float(cur["close"]),
             prev_low=float(prev["low"]), prev_high=float(prev["high"]))
    m = {k: (float(v) if v is not None and not isinstance(v, (int, float)) else v) for k, v in m.items()}
    if any(m[k] is None or pd.isna(m[k]) for k in ("ema50_4h", "ema200_4h", "atr4h", "ema21_1h", "ema21_1h_prev", "rsi", "rsi_prev", "atr1h", "vol_sma20")):
        a.reasons = ["Indicator values could not be computed from available history"]
        return a
    a.metrics, a.price = m, m["close"]
    a.signal_candle_ms = int(cur["time"]); a.data_ts_ms = int(cur["time"] + IV_MS["1h"])
    ratio = candle_ratio(cur["open"], cur["high"], cur["low"], cur["close"])
    ri = "invalid (High-Low = 0)" if ratio is None else f"{ratio:.3f}"
    vol_ok = m["volume"] > 1.2 * m["vol_sma20"]
    fi = f" (interval {funding_interval_h}h)" if funding_interval_h else " (interval unknown)"
    L = [
        Cond(1, "4H macro uptrend", m["close4"] > m["ema50_4h"] and m["ema50_4h"] > m["ema200_4h"],
             f"close {_fmt(m['close4'])}, EMA50 {_fmt(m['ema50_4h'])}, EMA200 {_fmt(m['ema200_4h'])}", "close > EMA50 > EMA200", "4H trend filter"),
        Cond(2, "1H pullback to EMA21", m["prev_low"] <= m["ema21_1h_prev"] and m["close"] > m["ema21_1h"],
             f"prev low {_fmt(m['prev_low'])} vs EMA21 {_fmt(m['ema21_1h_prev'])}; close {_fmt(m['close'])} vs EMA21 {_fmt(m['ema21_1h'])}",
             "prev Low <= EMA21 and Close > EMA21", "Price touched EMA21 and reclaimed it"),
        Cond(3, "1H RSI rising in 40-55", 40 < m["rsi"] < 55 and m["rsi"] > m["rsi_prev"],
             f"RSI {m['rsi']:.2f} (prev {m['rsi_prev']:.2f})", "40 < RSI < 55 and RSI > prev", "Momentum recovering, not overbought"),
        Cond(4, "Volume confirmation", vol_ok, f"vol {_fmt(m['volume'])} vs 1.2x SMA20 = {_fmt(1.2 * m['vol_sma20'])}", "vol > 1.2 x SMA20", "Participation on signal candle"),
        Cond(5, "Bullish candle in top 30%", ratio is not None and m["close"] > m["open"] and ratio >= 0.70,
             f"close>open: {m['close'] > m['open']}, position ratio {ri}", "close > open and (C-L)/(H-L) >= 0.70", "Strong bullish close"),
        Cond(6, "Funding < +0.03%", funding_rate < FUNDING_LIMIT, f"{m['funding_pct']:.4f}%{fi}", "< +0.03%", "Longs not crowded"),
    ]
    S = [
        Cond(1, "4H macro downtrend", m["close4"] < m["ema50_4h"] and m["ema50_4h"] < m["ema200_4h"],
             f"close {_fmt(m['close4'])}, EMA50 {_fmt(m['ema50_4h'])}, EMA200 {_fmt(m['ema200_4h'])}", "close < EMA50 < EMA200", "4H trend filter"),
        Cond(2, "1H pullback to EMA21", m["prev_high"] >= m["ema21_1h_prev"] and m["close"] < m["ema21_1h"],
             f"prev high {_fmt(m['prev_high'])} vs EMA21 {_fmt(m['ema21_1h_prev'])}; close {_fmt(m['close'])} vs EMA21 {_fmt(m['ema21_1h'])}",
             "prev High >= EMA21 and Close < EMA21", "Price touched EMA21 and rejected it"),
        Cond(3, "1H RSI falling in 45-60", 45 < m["rsi"] < 60 and m["rsi"] < m["rsi_prev"],
             f"RSI {m['rsi']:.2f} (prev {m['rsi_prev']:.2f})", "45 < RSI < 60 and RSI < prev", "Momentum fading, not oversold"),
        Cond(4, "Volume confirmation", vol_ok, f"vol {_fmt(m['volume'])} vs 1.2x SMA20 = {_fmt(1.2 * m['vol_sma20'])}", "vol > 1.2 x SMA20", "Participation on signal candle"),
        Cond(5, "Bearish candle in bottom 30%", ratio is not None and m["close"] < m["open"] and ratio <= 0.30,
             f"close<open: {m['close'] < m['open']}, position ratio {ri}", "close < open and (C-L)/(H-L) <= 0.30", "Strong bearish close"),
        Cond(6, "Funding > -0.03%", funding_rate > -FUNDING_LIMIT, f"{m['funding_pct']:.4f}%{fi}", "> -0.03%", "Shorts not crowded"),
    ]
    a.long_conds, a.short_conds = L, S
    for direction, conds in (("LONG", L), ("SHORT", S)):
        if all(c.passed for c in conds):
            plan = build_plan(direction, m["close"], d1, d4, m["atr1h"], m["atr4h"])
            a.plan = plan
            if plan["valid"]:
                a.status, a.direction = f"ENTRY — {direction}", direction
                a.reasons = [f"All six {direction} conditions passed; risk/target validation passed."]
            else:
                a.status = "NO SIGNAL"
                a.reasons = [f"All six {direction} conditions passed but trade rejected: {plan.get('reject')}"]
            return a
    for direction, conds in (("LONG", L), ("SHORT", S)):
        n = sum(c.passed for c in conds)
        if conds[0].passed and n >= WAIT_MIN_PASSED:
            missing = [c.name for c in conds if not c.passed]
            a.status, a.direction = "WAIT", direction
            a.reasons = [f"{direction} setup developing ({n}/6 passed). Missing: {', '.join(missing)}. WAIT is NOT an entry."]
            return a
    a.status = "NO SIGNAL"
    a.reasons = [f"LONG {sum(c.passed for c in L)}/6 and SHORT {sum(c.passed for c in S)}/6 conditions passed; no justified setup."]
    return a
