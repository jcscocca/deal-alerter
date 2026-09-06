"""Steam thresholds stay beside the Steam judgment, not in a universal ladder."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from dealcore.config import overlay, read_config


@dataclass(frozen=True)
class Thresholds:
    # Within this % of the all-time low counts as matching it. Covers rounding
    # and tiny regional price changes between sales.
    matches_low_pct: float = 2.0
    near_low_pct: float = 10.0
    best_this_year_pct: float = 2.0
    decent_cut: int = 50
    min_cut: int = 10


@dataclass(frozen=True)
class General:
    country: str = "US"
    currency_symbol: str = "$"
    history_years: int = 5


@dataclass(frozen=True)
class Alerts:
    alert_at: str = "NEAR_LOW"
    remind_after_days: int = 30


@dataclass(frozen=True)
class Config:
    general: General
    alerts: Alerts
    thresholds: Thresholds

    @classmethod
    def load(cls, path: Path) -> Config:
        raw = read_config(path)
        cfg = cls(overlay(General(), raw.get("general", {})),
                  overlay(Alerts(), raw.get("alerts", {})),
                  overlay(Thresholds(), raw.get("thresholds", {})))
        if cfg.general.history_years <= 0 or cfg.alerts.remind_after_days < 0:
            raise ValueError("history_years must be positive; reminder days nonnegative")
        if not 0 <= cfg.thresholds.matches_low_pct <= cfg.thresholds.near_low_pct:
            raise ValueError("matches_low_pct must be between zero and near_low_pct")
        if not all(0 <= value <= 100 for value in (cfg.thresholds.min_cut, cfg.thresholds.decent_cut)):
            raise ValueError("Discount thresholds must be in [0, 100]")
        return cfg


def load_targets(path: Path) -> dict[int, float]:
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {int(key): float(value) for key, value in raw.items() if not key.startswith("_")}
