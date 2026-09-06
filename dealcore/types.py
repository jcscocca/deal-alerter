"""Small contracts. Domain payloads remain typed Python, not rule dictionaries."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Callable, Generic, Protocol, TypeVar

B = TypeVar("B", bound=IntEnum)
C = TypeVar("C")  # a domain's matched candidate
E = TypeVar("E")  # that domain's evidence, not a universal PriceStats
D = TypeVar("D")  # its full assessment, retained for presentation and recording


@dataclass
class Listing:
    """One thing, for sale, somewhere."""
    # Stable per source. Used for dedup and for the observation log's UNIQUE
    # constraint, so it must not change between runs for the same listing.
    listing_id: str
    source: str
    title: str
    url: str
    posted_at: datetime
    # None when the source doesn't publish a structured price and the title
    # doesn't carry one either; match.py will try to scrape it.
    price: float | None = None
    body: str = ""
    # eBay-style condition strings, when the source states one outright.
    condition_hint: str = ""
    # True when this is a completed sale rather than an active listing --
    # the difference between what someone asked and what someone paid.
    sold: bool = False
    # False when the source knows its own results are not a fair sample of the
    # market, so the listing may be shown but must never enter the price log.
    # eBay's active search sorts by price ascending, which is the right slice to
    # hunt in and the wrong one to measure from.
    loggable: bool = True
    # True when this row is one option out of several priced behind a single
    # listing. The title then describes the group and the price describes only
    # the option the search happened to surface, so the two cannot be put
    # together into an observation.
    multi_variant: bool = False
    # low / moderate / high, from whatever the source knows about the seller.
    # Sources that publish nothing about sellers leave this alone.
    seller_risk: str = "low"
    seller_note: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def age_hours(self) -> float:
        return (datetime.now(timezone.utc) - self.posted_at).total_seconds() / 3600


@dataclass
class FetchResult:
    listings: list[Listing]
    # Only a complete enumeration can prove absence. A failed request or the
    # first fifty search hits cannot prove that an earlier listing disappeared.
    complete_sources: frozenset[str] = frozenset()


class Source(Protocol):
    name: str
    fetch: Callable[[], FetchResult]


class SourceError(RuntimeError):
    """One dead source should never cost you the other four."""


@dataclass(frozen=True)
class Assessment(Generic[B, D]):
    """Only the facts the workflow needs; the domain keeps everything else."""
    key: str
    price: float
    verdict: B
    detail: D
    # Compared only within this domain, after the verdict. No universal score.
    rank: tuple[float, ...] = ()
    target_override: bool = False
    alertable: bool = True
    loggable: bool = False
    axes: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Card:
    title: str
    url: str
    price: str
    badge: str
    headline: str
    reason: str
    facts: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    image: str | None = None
    # Percentages and captions are calculated by the plugin; core just draws.
    bar: tuple[tuple[int, str], ...] = ()
    bar_labels: tuple[str, str] = ("", "")
    foreground: str = "#1c5d99"
    background: str = "#dbebfa"
    priority: int = 3


@dataclass(frozen=True)
class Report:
    subject: str
    heading: str
    summary: str
    footer: str
    buys: tuple[Card, ...]
    others: tuple[Card, ...] = ()
    problems: tuple[str, ...] = ()


@dataclass(frozen=True)
class DelegatedHistory(Generic[C, E]):
    """Read evidence somebody else collected. There is no append operation."""
    read: Callable[[C], E]


@dataclass(frozen=True)
class AccumulatedHistory(Generic[C, E, B, D]):
    """Read first; append the entire approved cohort only after judging it."""
    read: Callable[[C], E]
    append: Callable[[list[tuple[C, Assessment[B, D]]]], None]


class Domain(Protocol[C, E, B, D]):
    name: str
    bands: type[B]
    axes: tuple[str, ...]
    sources: tuple[Source, ...]
    history: DelegatedHistory[C, E] | AccumulatedHistory[C, E, B, D]
    key: Callable[[Listing], str]
    normalise_key: Callable[[str], str]
    prepare: Callable[[Listing], C | None]
    judge: Callable[[C, E], Assessment[B, D] | None]
    card: Callable[[Assessment[B, D]], Card]
    report: Callable[[list[Assessment[B, D]], list[Assessment[B, D]], list[str]], Report]
    # Persist caches/logs only on real runs; close resources even after failure.
    persist: Callable[[], None]
    close: Callable[[], None]
