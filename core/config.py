"""Configuration with validation. Secrets come only from environment variables."""
from __future__ import annotations
import os
from dataclasses import dataclass, asdict, fields


class ConfigError(ValueError):
    pass


@dataclass
class Config:
    account_equity: float = 1000.0
    risk_pct: float = 0.015            # 1.5% planned risk per trade (spec)
    fee_rate: float = 0.0005           # per side; USER ASSUMPTION - replace with your real CoinDCX fee tier
    slippage_pct: float = 0.0005       # per fill; USER ASSUMPTION
    leverage: float = 3.0
    available_balance: float = 1000.0
    execution_mode: str = "paper"      # "paper" | "live" (live disabled unless explicitly enabled)
    concurrency: int = 8
    max_retries: int = 3
    timeout_s: float = 15.0
    funding_unit: str = ""             # "decimal" | "percent" (must be set)
    core_pct: float = 0.65
    satellite_pct: float = 0.35
    dca_tranches: int = 5
    exit_levels: tuple = (0.5, 1.0, 2.0, 3.0)   # profit multiples (illustrative)
    exit_sell_pct: float = 0.25
    news_max_age_days: int = 14

    def validate(self) -> "Config":
        if self.account_equity <= 0: raise ConfigError("account_equity must be > 0")
        if not 0 < self.risk_pct <= 0.05: raise ConfigError("risk_pct must be in (0, 0.05]")
        if not 0 <= self.fee_rate < 0.01: raise ConfigError("fee_rate unrealistic")
        if not 0 <= self.slippage_pct < 0.05: raise ConfigError("slippage_pct unrealistic")
        if self.leverage < 1: raise ConfigError("leverage must be >= 1")
        if self.execution_mode not in ("paper", "live"): raise ConfigError("execution_mode invalid")
        if self.execution_mode == "live" and os.getenv("LIVE_EXECUTION_ENABLED", "false").lower() != "true":
            raise ConfigError("Live mode requires LIVE_EXECUTION_ENABLED=true in the environment")
        if self.funding_unit not in ("", "decimal", "percent"): raise ConfigError("funding_unit invalid")
        if abs(self.core_pct + self.satellite_pct - 1) > 1e-9: raise ConfigError("core+satellite must equal 100%")
        if not 4 <= self.dca_tranches <= 6: raise ConfigError("dca_tranches must be 4-6")
        if not 0 < self.exit_sell_pct <= 0.5: raise ConfigError("exit_sell_pct must be in (0, 0.5]")
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Config":
        names = {f.name for f in fields(cls)}
        kw = {k: v for k, v in (d or {}).items() if k in names}
        if "exit_levels" in kw: kw["exit_levels"] = tuple(kw["exit_levels"])
        return cls(**kw)

    @classmethod
    def from_env(cls) -> "Config":
        return cls(funding_unit=os.getenv("COINDCX_FUNDING_UNIT", "").lower())


def secret_status() -> dict:
    """Which secrets are configured (booleans only - values are never exposed)."""
    return {k: bool(os.getenv(k)) for k in
            ("COINDCX_API_KEY", "COINDCX_API_SECRET", "COINDCX_FUNDING_UNIT", "COINGECKO_API_KEY")}
