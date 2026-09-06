"""Comparison and presentation mechanics. No knowledge of any band's name."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from math import isfinite

from .types import Assessment, B


def ago(when: datetime | None, *, now: datetime | None = None) -> str:
    if not when:
        return "at an unknown date"
    days = ((now or datetime.now(timezone.utc)) - when).days
    if days < 2:
        return "today"
    if days < 45:
        return f"{days} days ago"
    if days < 330:
        return f"{max(days // 30, 2)} months ago"
    years = days / 365.25
    if years < 1.3:
        return "about a year ago"
    rounded = round(years)
    if abs(years - rounded) < 0.25:
        return f"about {rounded} years ago"
    return f"{years:.1f} years ago"


def money(amount: float, symbol: str = "$", *, decimals: int = 2,
          whole_above: float | None = None) -> str:
    places = 0 if whole_above is not None and amount >= whole_above else decimals
    return f"{symbol}{amount:,.{places}f}"


def band(enum: type[B], name: str) -> B:
    try:
        return enum[name]
    except KeyError as exc:
        raise ValueError(f"Unknown band {name!r}; use {', '.join(enum.__members__)}") from exc


def qualifies(item: Assessment, floor: IntEnum) -> bool:
    # IntEnum permits comparisons across unrelated enums. That convenience is
    # dangerous here: a Steam band must never satisfy a hardware threshold.
    if type(item.verdict) is not type(floor):
        raise TypeError("Assessment and alert threshold use different bands")
    return item.alertable and (item.verdict >= floor or item.target_override)


@dataclass(frozen=True)
class Improvement:
    epsilon: float
    drop_pct: float | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.epsilon) or self.epsilon < 0:
            raise ValueError("epsilon must be finite and nonnegative")
        if self.drop_pct is not None and not 0 < self.drop_pct <= 100:
            raise ValueError("drop_pct must be in (0, 100]")

    def better(self, price: float, verdict: int, old_price: float, old_verdict: int) -> bool:
        if verdict > old_verdict:
            return True
        if self.drop_pct is None:
            return price < old_price - self.epsilon
        # Hardware's 4% rule is not Steam's cent rule with a larger epsilon.
        return old_price > 0 and (old_price - price) / old_price * 100 >= self.drop_pct
