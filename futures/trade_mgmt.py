"""Paper-trade lifecycle (spec section 9). Processes COMPLETED 1H candles only. Stop is checked before targets (conservative)."""
from __future__ import annotations
from dataclasses import dataclass, field

H48 = 48 * 3_600_000
IV = 3_600_000


@dataclass
class PaperTrade:
    symbol: str
    direction: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    qty: float
    entry_time_ms: int
    fee_rate: float = 0.0005
    slippage_pct: float = 0.0
    stop: float = 0.0
    R: float = 0.0
    remaining: float = 1.0          # fraction of original position
    stage: str = "OPEN"             # OPEN -> TP1_DONE -> TRAILING -> CLOSED
    realized: float = 0.0
    fees_paid: float = 0.0
    events: list = field(default_factory=list)
    exit_reason: str = ""

    def __post_init__(self):
        self.stop = self.sl
        self.R = abs(self.entry - self.sl)
        self.sgn = 1 if self.direction == "LONG" else -1
        self.fees_paid = self.fee_rate * self.entry * self.qty        # entry fee
        self.events.append((self.entry_time_ms, "ENTRY", f"entry {self.entry}, SL {self.sl}, TP1 {self.tp1}, TP2 {self.tp2}"))

    def break_even(self) -> float:
        return self.entry + self.sgn * 2 * self.fee_rate * self.entry     # entry+exit fee per unit

    def _close(self, frac: float, px: float, ts: int, kind: str, slip: bool = False) -> None:
        if slip:
            px = px * (1 - self.sgn * self.slippage_pct)
        q = self.qty * frac
        self.realized += self.sgn * (px - self.entry) * q
        self.fees_paid += self.fee_rate * px * q
        self.remaining = round(self.remaining - frac, 12)
        self.events.append((ts, kind, f"closed {frac:.0%} @ {px:.8g}"))

    @property
    def net_pnl(self) -> float:
        return self.realized - self.fees_paid

    def on_candle(self, c: dict, ema21: float) -> None:
        """c: completed 1H candle dict(time, open, high, low, close)."""
        if self.stage == "CLOSED":
            return
        close_ts = c["time"] + IV
        hit_stop = c["low"] <= self.stop if self.sgn == 1 else c["high"] >= self.stop
        hi_fav = c["high"] if self.sgn == 1 else c["low"]
        reached = lambda lvl: hi_fav >= lvl if self.sgn == 1 else hi_fav <= lvl
        if hit_stop:
            kind = "BREAKEVEN_STOP" if self.stage != "OPEN" and abs(self.stop - self.break_even()) < 1e-12 else \
                   ("TRAILING_STOP" if self.stage == "TRAILING" else "STOP_LOSS")
            self._close(self.remaining, self.stop, close_ts, kind, slip=True); self._finish(kind); return
        if self.stage == "OPEN" and reached(self.tp1):
            self._close(0.5, self.tp1, close_ts, "TP1")
            self.stop = self.break_even(); self.stage = "TP1_DONE"
            self.events.append((close_ts, "MOVE_STOP_BE", f"stop -> {self.stop:.8g} (entry +/- fees)"))
        if self.stage == "TP1_DONE" and reached(self.entry + self.sgn * 2 * self.R):
            self.stage = "TRAILING"; self.events.append((close_ts, "TRAIL_START", "2R reached; trailing 1H EMA21"))
        if self.stage in ("TP1_DONE", "TRAILING") and reached(self.tp2):
            self._close(self.remaining, self.tp2, close_ts, "TP2"); self._finish("TP2"); return
        if close_ts - self.entry_time_ms >= H48:
            self._close(self.remaining, c["close"], close_ts, "TIME_EXIT_48H", slip=True); self._finish("TIME_EXIT_48H"); return
        if self.stage == "TRAILING" and ema21 == ema21:      # NaN-safe
            better = ema21 > self.stop if self.sgn == 1 else ema21 < self.stop
            valid = ema21 < c["close"] if self.sgn == 1 else ema21 > c["close"]
            if better and valid:                              # never loosen
                self.stop = ema21; self.events.append((close_ts, "TRAIL_UPDATE", f"stop -> {ema21:.8g}"))

    def _finish(self, reason: str) -> None:
        self.stage, self.exit_reason = "CLOSED", reason
