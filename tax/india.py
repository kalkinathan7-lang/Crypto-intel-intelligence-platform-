"""Educational India VDA tax estimator. Rates are read from data/tax_rules.json (user-verified), not hardcoded.
NOT tax advice. Provisions assumed (to be verified): flat tax on gains from VDA transfer (s.115BBH), deduction limited to cost of
acquisition, no set-off of VDA losses against any income (incl. other VDA), TDS on transfer (s.194S)."""
from __future__ import annotations
import json, os

RULES_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "tax_rules.json")


def load_rules(path: str = RULES_PATH) -> dict:
    with open(path) as f: return json.load(f)


def estimate(transactions: list[dict], rules: dict | None = None) -> dict:
    """transactions: dict(asset, buy_cost, sell_value, fees=0) per completed sale. Losses are NOT offset (per rules file)."""
    r = rules or load_rules()
    rows, gain_tax_base, tds, losses = [], 0.0, 0.0, 0.0
    for t in transactions:
        gain = t["sell_value"] - t["buy_cost"]          # transfer expenses other than cost are not deductible under the assumed rules
        taxable = gain if gain > 0 else 0.0
        if gain < 0 and not r["loss_offset_allowed"]: losses += -gain
        tds_row = t["sell_value"] * r["tds_194s_rate"]
        rows.append(dict(asset=t["asset"], gain=gain, taxable_gain=taxable, tds_194s=tds_row))
        gain_tax_base += taxable; tds += tds_row
    tax = gain_tax_base * r["vda_tax_rate"] * (1 + r["cess_rate"])
    verified = bool(r.get("last_verified"))
    return dict(rows=rows, taxable_gains=gain_tax_base, estimated_tax=tax, tds_deducted_total=tds, net_payable_after_tds=tax - tds,
                unusable_losses=losses, rules_verified=verified,
                disclaimers=["Educational estimate only; not professional tax advice or a final liability.",
                             "Rules file status: " + ("verified on " + str(r["last_verified"]) if verified else "UNVERIFIED - confirm with official sources"),
                             "Losses cannot be set off under the assumed rules; reporting obligations (Schedule VDA) not computed.",
                             "TDS actually deducted depends on exchange/payer and thresholds; shown figure is a simplification."])
