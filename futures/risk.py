"""Position sizing against contract specifications. Never invents missing specs."""
from __future__ import annotations
import math
from typing import Optional


def size_position(equity: float, risk_pct: float, entry: float, sl: float, spec: Optional[dict], fee_rate: float,
                  slippage_pct: float, leverage: float, available_balance: float,
                  funding_rate: float = 0.0, hold_hours: float = 48, funding_interval_h: float = 8) -> dict:
    """spec keys: min_qty, qty_step, max_leverage (optional), contract_multiplier (optional, default 1)."""
    if not spec or not spec.get("min_qty") or not spec.get("qty_step"):
        return {"ok": False, "reject": "Contract specification unavailable (min_qty/qty_step) - cannot size position"}
    dist = abs(entry - sl)
    if dist <= 0:
        return {"ok": False, "reject": "SL distance is zero"}
    planned = equity * risk_pct
    raw = planned / dist
    step, mn = spec["qty_step"], spec["min_qty"]
    qty = math.floor(raw / step + 1e-12) * step
    qty = round(qty, 12)
    if qty < mn:
        return {"ok": False, "reject": f"Quantity {qty:.8g} below exchange minimum {mn}", "raw_qty": raw}
    lev = min(leverage, spec.get("max_leverage") or leverage)
    notional = qty * entry
    margin = notional / lev
    fees = fee_rate * notional * 2
    slip = slippage_pct * notional * 2
    funding = abs(funding_rate) * notional * (hold_hours / funding_interval_h)
    if margin + fees > available_balance:
        return {"ok": False, "reject": f"Required margin+fees {margin + fees:.2f} exceeds available balance {available_balance:.2f}",
                "notional": notional, "margin": margin}
    return {"ok": True, "qty": qty, "raw_qty": raw, "planned_risk": planned, "actual_price_risk": qty * dist,
            "notional": notional, "initial_margin": margin, "leverage": lev, "est_fees_round_trip": fees,
            "est_slippage": slip, "est_funding_worst_case": funding,
            "note": "Planned risk is not a guaranteed max loss: gaps, slippage, fees, funding and liquidation can increase losses. "
                    "Check liquidation price on the exchange - not modelled here."}
