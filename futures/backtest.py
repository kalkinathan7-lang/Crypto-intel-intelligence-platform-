"""Walk-forward futures backtest using the SAME engine (strategy.analyze). Uses completed candles only; analyze() slices
by `now` so no future data can enter. Entry = signal-candle close adjusted by slippage. Constant funding assumption.
Limitations: 1H-resolution fills (stop assumed first when both hit), constant fees/funding, one position per symbol."""
from __future__ import annotations
import pandas as pd
from .indicators import ema
from .strategy import analyze
from .trade_mgmt import PaperTrade, IV


def backtest(symbol: str, df1h: pd.DataFrame, df4h: pd.DataFrame, equity: float = 1000.0, risk_pct: float = 0.015,
             fee_rate: float = 0.0005, slippage_pct: float = 0.0005, funding_rate: float = 0.0,
             funding_interval_h: float = 8.0, start_index: int = 300) -> dict:
    d1 = df1h.sort_values("time").reset_index(drop=True)
    e21 = ema(d1["close"], 21)
    trades, open_t, eq, peak, max_dd, curve = [], None, equity, equity, 0.0, []
    for i in range(start_index, len(d1)):
        c = d1.iloc[i].to_dict()
        now = int(c["time"] + IV)
        if open_t is not None:
            open_t.on_candle(c, float(e21.iloc[i]))
            if open_t.stage == "CLOSED":
                hours = (now - open_t.entry_time_ms) / IV
                fund = abs(funding_rate) * open_t.entry * open_t.qty * hours / funding_interval_h
                net = open_t.net_pnl - fund
                eq += net
                trades.append(dict(direction=open_t.direction, entry_ms=open_t.entry_time_ms, exit_ms=now, net=net,
                                   R_mult=net / (open_t.R * open_t.qty), reason=open_t.exit_reason, hours=hours, funding=fund))
                open_t = None
                peak = max(peak, eq); max_dd = max(max_dd, (peak - eq) / peak); curve.append(eq)
            continue
        a = analyze(symbol, d1.iloc[max(0, i - 299):i + 1], df4h, funding_rate, funding_interval_h, now)
        if a.direction and a.status.startswith("ENTRY"):
            p = a.plan
            sgn = 1 if a.direction == "LONG" else -1
            entry = p["entry"] * (1 + sgn * slippage_pct)
            R = abs(entry - p["sl"])
            if R <= 0: continue
            qty = eq * risk_pct / R
            open_t = PaperTrade(symbol, a.direction, entry, p["sl"], p["tp1"], p["tp2"], qty, now, fee_rate, slippage_pct)
    return {"symbol": symbol, "metrics": metrics(trades, max_dd), "trades": trades, "final_equity": eq,
            "assumptions": "completed candles only; entry at signal-candle close +slippage; stop-before-target in ambiguous candles; "
                           "constant fee/slippage/funding; no liquidation modelling; in-sample unless split by caller"}


def metrics(trades: list, max_dd: float) -> dict:
    if not trades:
        return {"total_trades": 0}
    net = [t["net"] for t in trades]
    wins, losses = [x for x in net if x > 0], [x for x in net if x <= 0]
    streak = best = 0
    for x in net:
        streak = streak + 1 if x <= 0 else 0; best = max(best, streak)
    by = lambda d: [t["net"] for t in trades if t["direction"] == d]
    return dict(total_trades=len(net), winners=len(wins), losers=len(losses), win_rate=len(wins) / len(net),
                profit_factor=(sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else None,
                max_drawdown=max_dd, avg_R=sum(t["R_mult"] for t in trades) / len(net), net_profit=sum(net),
                avg_hours=sum(t["hours"] for t in trades) / len(net), long_net=sum(by("LONG")), short_net=sum(by("SHORT")),
                largest_win=max(net), largest_loss=min(net), max_consecutive_losses=best)
          
