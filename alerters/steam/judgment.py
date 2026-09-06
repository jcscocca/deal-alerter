"""Turning price history into a buy / wait call.

The whole point of this project: Steam tells you "-40%!" but not whether -40% is
good *for that game*. A 40% cut on something that hits -75% every summer is
noise; a 40% cut on something that has never gone below -30% is the best chance
you will get this year. Everything here is about supplying that context.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum

from .config import Thresholds
from .sources import GamePrices, HistoryPoint, StoreLow
from dealcore.verdict import ago as _ago, money as _fmt

# Prices within this many cents are treated as equal, so a $19.99 vs $19.99
# comparison isn't defeated by float noise or a one-cent currency adjustment.
CENT = 0.011


class Verdict(IntEnum):
    """Ordered worst to best so alert thresholds can be a simple >= compare."""

    WAIT = 0
    DECENT = 1
    BEST_THIS_YEAR = 2
    NEAR_LOW = 3
    MATCHES_LOW = 4
    ALL_TIME_LOW = 5

    @property
    def label(self) -> str:
        return {
            Verdict.WAIT: "WAIT",
            Verdict.DECENT: "DECENT",
            Verdict.BEST_THIS_YEAR: "BEST THIS YEAR",
            Verdict.NEAR_LOW: "NEAR LOW",
            Verdict.MATCHES_LOW: "MATCHES BEST EVER",
            Verdict.ALL_TIME_LOW: "ALL-TIME LOW",
        }[self]


@dataclass
class HistoryStats:
    """What the price log says about how often this deal comes around."""

    # Sale episodes at or below the current price, *excluding* the one running
    # right now -- i.e. how many chances you have already missed.
    times_this_cheap: int = 0
    # When it was last this cheap, excluding the sale running right now.
    last_this_cheap: datetime | None = None
    # True when the price log ends in a dip, meaning the current sale is in it.
    ongoing_sale: bool = False
    # Whether we have any price log at all to reason from.
    has_history: bool = False
    # Median of each past sale's floor -- "a typical sale lands here".
    typical_sale_price: float | None = None
    # Deepest cut ever recorded in the window.
    best_cut: int = 0
    # Sale episodes per year, averaged over the tracked window.
    sales_per_year: float | None = None
    tracked_since: datetime | None = None


@dataclass
class Assessment:
    appid: int
    itad_id: str
    title: str
    url: str
    boxart: str | None

    price: float
    regular: float
    cut: int
    currency: str
    expiry: datetime | None

    verdict: Verdict
    headline: str
    reason: str

    steam_low: float | None = None
    steam_low_at: datetime | None = None
    steam_low_cut: int = 0
    low_all: float | None = None
    low_y1: float | None = None

    target_price: float | None = None
    target_hit: bool = False
    history: HistoryStats = field(default_factory=HistoryStats)

    @property
    def pct_above_low(self) -> float | None:
        """How far above the all-time low this price sits, in percent."""
        if not self.steam_low or self.steam_low <= 0:
            return None
        return (self.price - self.steam_low) / self.steam_low * 100.0

    @property
    def should_alert_score(self) -> tuple[int, float]:
        """Sort key: best verdict first, then deepest cut."""
        return (int(self.verdict), float(self.cut))


def summarize_history(
    points: list[HistoryPoint], current_price: float
) -> HistoryStats:
    """Collapse a raw price log into decision-useful statistics.

    A "sale episode" is a contiguous run of points at or below a price. Counting
    episodes rather than individual price-change rows matters because ITAD logs
    several rows during a single sale (regional adjustments, sale extensions),
    and counting rows would badly overstate how often a deal recurs.
    """
    stats = HistoryStats()
    if not points:
        return stats

    stats.has_history = True
    stats.tracked_since = points[0].at
    stats.best_cut = max(p.cut for p in points)

    threshold = current_price + CENT
    episodes: list[tuple[datetime, datetime, float]] = []  # start, end, floor
    start: datetime | None = None
    floor = float("inf")

    for point in points:
        if point.price <= threshold:
            if start is None:
                start = point.at
                floor = point.price
            else:
                floor = min(floor, point.price)
            last_at = point.at
        elif start is not None:
            episodes.append((start, last_at, floor))
            start, floor = None, float("inf")
    if start is not None:
        episodes.append((start, points[-1].at, floor))

    # If the log ends inside a dip, that dip is the sale running right now, and
    # it must not be counted as a past opportunity. Deciding this by looking at
    # the data beats assuming the last episode is always the current one -- a
    # sale that started hours ago may not be in the log yet.
    now = datetime.now(timezone.utc)
    if episodes and (now - episodes[-1][1]).days <= 3:
        stats.ongoing_sale = True
    past = episodes[:-1] if stats.ongoing_sale else episodes

    stats.times_this_cheap = len(past)
    stats.last_this_cheap = past[-1][1] if past else None

    # Median floor across *all* discounted episodes, not just the cheap ones.
    all_floors: list[float] = []
    in_sale = False
    sale_floor = float("inf")
    for point in points:
        if point.cut > 0:
            in_sale = True
            sale_floor = min(sale_floor, point.price)
        elif in_sale:
            all_floors.append(sale_floor)
            in_sale, sale_floor = False, float("inf")
    if in_sale:
        all_floors.append(sale_floor)
    if all_floors:
        stats.typical_sale_price = statistics.median(all_floors)
        span_days = (points[-1].at - points[0].at).days
        if span_days > 90:
            stats.sales_per_year = len(all_floors) / (span_days / 365.25)

    return stats


def _times(count: int) -> str:
    return {1: "once", 2: "twice"}.get(count, f"{count} times")


def assess(
    *,
    appid: int,
    title: str,
    boxart: str | None,
    prices: GamePrices,
    store_low: StoreLow | None,
    history: list[HistoryPoint],
    thresholds: Thresholds,
    target_price: float | None = None,
    symbol: str = "$",
) -> Assessment | None:
    """Score one currently-discounted game. Returns None if it isn't on sale."""
    deal = prices.deal
    if deal is None:
        return None

    price = deal.price.amount
    stats = summarize_history(history, price)

    # Prefer storelow/v2 (it carries a date); fall back to the price embedded in
    # the deal, then to whatever the history log shows.
    steam_low = store_low.price.amount if store_low else None
    if steam_low is None and deal.store_low:
        steam_low = deal.store_low.amount
    if steam_low is None and history:
        steam_low = min(p.price for p in history)

    low_all = prices.low_all.amount if prices.low_all else None
    low_y1 = prices.low_y1.amount if prices.low_y1 else None

    verdict, headline, reason = _decide(
        price=price,
        cut=deal.cut,
        steam_low=steam_low,
        steam_low_at=store_low.at if store_low else None,
        steam_low_cut=store_low.cut if store_low else 0,
        low_all=low_all,
        low_y1=low_y1,
        stats=stats,
        thresholds=thresholds,
        symbol=symbol,
    )
    # The reason sentences are assembled from optional fragments, so collapse
    # the gaps left behind when a fragment is empty.
    reason = " ".join(reason.split())

    target_hit = target_price is not None and price <= target_price + CENT

    return Assessment(
        appid=appid,
        itad_id=prices.itad_id,
        title=title,
        url=deal.url or f"https://store.steampowered.com/app/{appid}/",
        boxart=boxart,
        price=price,
        regular=deal.regular.amount,
        cut=deal.cut,
        currency=deal.price.currency,
        expiry=deal.expiry,
        verdict=verdict,
        headline=headline,
        reason=reason,
        steam_low=steam_low,
        steam_low_at=store_low.at if store_low else None,
        steam_low_cut=store_low.cut if store_low else 0,
        low_all=low_all,
        low_y1=low_y1,
        target_price=target_price,
        target_hit=target_hit,
        history=stats,
    )


def _decide(
    *,
    price: float,
    cut: int,
    steam_low: float | None,
    steam_low_at: datetime | None,
    steam_low_cut: int,
    low_all: float | None,
    low_y1: float | None,
    stats: HistoryStats,
    thresholds: Thresholds,
    symbol: str,
) -> tuple[Verdict, str, str]:
    """The actual buy/wait call, plus the sentences explaining it."""

    # Nothing to benchmark against. Either ITAD has no record of the game, or
    # the only price it has ever seen is the one on offer right now -- which is
    # a first-ever discount, not a hard-won all-time low. Saying "cheapest ever"
    # here would be technically true and completely useless.
    no_benchmark = steam_low is None or (
        not stats.has_history and price <= steam_low + CENT
    )
    if no_benchmark:
        verdict = Verdict.DECENT if cut >= thresholds.decent_cut else Verdict.WAIT
        return (
            verdict,
            f"{cut}% off, but no price history to judge it against",
            "IsThereAnyDeal has no earlier Steam sales on record for this game, so "
            "there is nothing to compare today's price against. Usually means a "
            "recent release having its first discount -- those tend to get deeper.",
        )

    frequency = _frequency_sentence(stats, symbol)

    # 1. At or below the cheapest Steam has ever sold it.
    if price <= steam_low + CENT:
        if stats.times_this_cheap == 0:
            prev = "It has never been this cheap before"
        else:
            prev = (
                f"It has been this low {_times(stats.times_this_cheap)} before, "
                f"most recently {_ago(stats.last_this_cheap)}"
            )
        return (
            Verdict.ALL_TIME_LOW,
            "Cheapest it has ever been on Steam",
            f"{_fmt(price, symbol)} ({cut}% off) matches or beats the all-time low "
            f"of {_fmt(steam_low, symbol)}. {prev}. {frequency}",
        )

    if steam_low is not None and steam_low > 0:
        gap_pct: float | None = (price - steam_low) / steam_low * 100.0

        # 2. Within noise of the all-time low -- effectively the same deal.
        if gap_pct <= thresholds.matches_low_pct:
            return (
                Verdict.MATCHES_LOW,
                "Effectively the best price ever",
                f"{_fmt(price, symbol)} ({cut}% off) is within {gap_pct:.0f}% of the "
                f"all-time low of {_fmt(steam_low, symbol)} ({steam_low_cut}% off, "
                f"{_ago(steam_low_at)}). Waiting saves you at most "
                f"{_fmt(price - steam_low, symbol)}. {frequency}",
            )

        # 3. Close enough that holding out is probably not worth it.
        if gap_pct <= thresholds.near_low_pct:
            return (
                Verdict.NEAR_LOW,
                f"Within {gap_pct:.0f}% of the all-time low",
                f"{_fmt(price, symbol)} ({cut}% off) versus a record low of "
                f"{_fmt(steam_low, symbol)} ({steam_low_cut}% off, {_ago(steam_low_at)}) "
                f"-- a {_fmt(price - steam_low, symbol)} difference. {frequency}",
            )
    else:
        gap_pct = None

    # 4. Best price in the last twelve months, even if not an all-time low.
    if low_y1 is not None and price <= low_y1 * (1 + thresholds.best_this_year_pct / 100):
        return (
            Verdict.BEST_THIS_YEAR,
            "Best price in the past year",
            f"{_fmt(price, symbol)} ({cut}% off) is the lowest this has gone in 12 "
            f"months, but it did reach {_fmt(steam_low, symbol)} "
            f"({steam_low_cut}% off) back in {_ago(steam_low_at)}. {frequency}",
        )

    # 5. Deep discount with no better benchmark to compare against.
    if cut >= thresholds.decent_cut:
        headline = (
            f"{cut}% off, but {gap_pct:.0f}% above the record low"
            if gap_pct is not None
            else f"{cut}% off, but record low was {_fmt(steam_low, symbol)}"
        )
        return (
            Verdict.DECENT,
            headline,
            f"{_fmt(price, symbol)} today versus {_fmt(steam_low, symbol)} "
            f"({steam_low_cut}% off) at its cheapest, {_ago(steam_low_at)}. "
            f"{frequency}",
        )

    # 6. Everything else: history says a better price is likely.
    headline = (
        f"Wait -- {gap_pct:.0f}% above the price it usually reaches"
        if gap_pct is not None
        else f"Wait -- record low was {_fmt(steam_low, symbol)}"
    )
    return (
        Verdict.WAIT,
        headline,
        f"{_fmt(price, symbol)} ({cut}% off) is well above the all-time low of "
        f"{_fmt(steam_low, symbol)} ({steam_low_cut}% off, {_ago(steam_low_at)}). "
        f"{frequency}",
    )


def _frequency_sentence(stats: HistoryStats, symbol: str) -> str:
    """One sentence on how often this game goes on sale, if we can tell."""
    parts: list[str] = []
    if stats.typical_sale_price is not None:
        parts.append(f"A typical sale lands around {_fmt(stats.typical_sale_price, symbol)}")
    if stats.sales_per_year:
        rate = stats.sales_per_year
        cadence = (
            "roughly monthly"
            if rate >= 10
            else f"about {rate:.0f}x a year"
            if rate >= 1.5
            else "roughly once a year"
        )
        parts.append(f"it goes on sale {cadence}")
    if not parts:
        return ""
    return "; ".join(parts).capitalize() + "."
