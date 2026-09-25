"""Configuration: secrets from the environment, tunables from config.toml,
and what to hunt for from watchlist.toml."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dealcore.config import overlay, read_config

from .catalog import BY_KEY, Part, in_class

ROOT = Path(__file__).resolve().parent.parent




class ConfigError(RuntimeError):
    pass




def _query_for(part: Part) -> str:
    """The search string for a part.

    The catalog name carries capacity ("RTX 3090 24GB"), which narrows eBay
    usefully but over-narrows Slickdeals, so search on the model designation
    alone. Shared by search_queries and query_price_floors so the two always
    key off identical strings.
    """
    query = part.name.split("(")[0].strip()
    for suffix in (" 24GB", " 32GB", " 48GB", " 96GB", " 16GB"):
        query = query.replace(suffix, "")
    return query.strip()






@dataclass(frozen=True)
class Thresholds:
    """How cheap something has to be, in percentile terms, to earn each verdict."""

    grail_pct: float = 3.0
    exceptional_pct: float = 10.0
    strong_pct: float = 20.0
    good_pct: float = 35.0
    min_observations: int = 8
    # Days the log must span before percentiles mean anything. Rows alone were
    # enough when the log filled a listing at a time; eBay deposits ~180 per
    # run, so a part clears any row count inside one snapshot of current
    # inventory, and ranking that against itself makes the cheapest 3% GRAIL
    # by construction. See PriceStats.trustworthy.
    min_observation_days: float = 14.0
    max_price_ratio: float = 1.6
    # The ceiling when the anchor is still the catalog constant rather than the
    # part's own median. It was 3.0 while those constants were unverified and
    # proving 35-58% low -- a tight multiple of a wrong number rejected 67% of
    # real listings and censored the log along with them. The constants are now
    # sold-sourced, so the slack has to come back out: asking prices run 23-49%
    # above sold, meaning a legitimate listing reaches ~1.5x and the audit's
    # 2.5x-and-up tail was noise nobody will ever buy.
    reference_max_price_ratio: float = 2.0
    min_price_ratio: float = 0.25
    # Between min_price_ratio and this, a price is plausible enough to show you
    # but too good to record. Real scam listings sit at 40-60% of market, because
    # bait has to be believable -- and that is exactly the band a genuine steal
    # lives in too. Price alone cannot tell them apart, so the tool shows both
    # and protects the log rather than guessing.
    #
    # Was 0.5 until 2026-08-17, when it turned out to be measured in the wrong
    # unit. It is compared against a *sold* anchor but fed *asking* prices, so
    # in ask terms it only fired below about a third of the going rate -- far
    # under where believable bait sits. Everything the tool had ever alerted on
    # cleared it: a zero-feedback Mac Studio at 0.512x missed by about $115.
    # See reference_exceptional_ratio for why this must stay below that band.
    suspicious_price_ratio: float = 0.70

    # ------------------------------------------------- reference-path bands
    # What "cheap" means when the anchor is the catalog constant rather than
    # the part's own history. These are ratios against *sold* value, and they
    # replaced a set (0.60 / 0.75 / 0.88 / 1.05) that had been read as though
    # asking and sold prices were the same number.
    #
    # They were not. Audited over 1,417 observations on 2026-08-17, logged
    # asking prices ran at a median of 1.50x their sold-based reference, and
    # the 1st percentile was 0.91x -- while the old STRONG line sat at 0.75x.
    # The honest population never reached the alert band at all, so the only
    # listings that could clear it were the ones that were not what they
    # claimed: 4 of 1,417 made it, and all four were bait or mismatches.
    #
    # The property these have to keep is that the alert band *overlaps the
    # honest distribution*. A threshold no real listing can reach does not
    # filter for good deals, it filters for broken data.
    #
    # The GRAIL band is the one that has to stay above suspicious_price_ratio:
    # the two are adjacent by construction, since "too good to be true" is
    # defined as the far side of "as good as it ever gets". Overlap them and
    # the tool's best verdict and its bait warning describe the same price.
    # tests/test_threshold_bands.py holds them apart.
    reference_grail_ratio: float = 0.75
    reference_exceptional_ratio: float = 0.85
    reference_strong_ratio: float = 0.95
    reference_good_ratio: float = 1.05
    reference_fair_ratio: float = 1.20

    # A sold anchor only means what it says while asks still sit above it. Once
    # the last 30 days of asks have fallen to it, a successor has usually
    # shipped and the anchor describes the old market: every ratio against it
    # reads a band too generous and the tool rings phones over the going rate.
    # Measured 2026-09-17, after the M5 Ultra: Mac Studio M3 Ultra asks ran
    # 0.95-1.01x their August sold averages, while the 512GB part it did not
    # replace still asked 1.78x. Anything between those separates them; 1.05
    # leaves a little margin on the stale side.
    stale_anchor_ask_ratio: float = 1.05
    stale_anchor_min_recent: int = 5


@dataclass(frozen=True)
class Hunt:
    """One rule from watchlist.toml, resolved to concrete catalog parts."""

    name: str
    parts: tuple[Part, ...]
    target: float | None = None
    quantity_wanted: int = 1
    max_dollars_per_gb: float | None = None
    note: str = ""


@dataclass(frozen=True)
class Config:


    ebay_client_id: str
    ebay_client_secret: str
    reddit_client_id: str
    reddit_client_secret: str

    country: str
    currency_symbol: str
    max_listing_age_hours: int

    digest_at: str
    push_at: str
    remind_after_days: int

    enforce_fit: bool
    psu_headroom_w: int

    hunts: tuple[Hunt, ...] = ()
    thresholds: Thresholds = field(default_factory=Thresholds)
    reddit_subs: tuple[str, ...] = ("buildapcsales", "homelabsales", "hardwareswap")
    prebuilt_push_margin_pct: float = 5.0

    @property
    def search_queries(self) -> tuple[str, ...]:
        """Queries for the sources that need one (eBay, Slickdeals).

        Derived from the watchlist rather than configured separately, so adding
        a hunt automatically starts searching for it. Deduplicated and capped,
        because each query is a round trip and Slickdeals in particular gets
        unhappy about a dozen searches a minute.
        """
        seen: dict[str, None] = {}
        for hunt in self.hunts:
            for part in hunt.parts:
                seen.setdefault(_query_for(part), None)
        return tuple(list(seen)[:24])

    @property
    def query_price_floors(self) -> dict[str, float]:
        """Lowest plausible price per query, for sources that can filter server-side.

        The same floor `assess()` applies after the fact, moved in front of the
        result window. It has to be: "RTX 3090" matches thousands of items on
        eBay, and sorted cheapest-first the top 50 are $3 stickers and brackets,
        so the actual cards never come back at all. Filtering server-side spends
        the window on things that could plausibly be the part.

        Where several parts share a query the cheapest floor wins -- a floor
        that hides a real part is a worse failure than one that lets some junk
        through, since junk still gets rejected downstream.
        """
        floors: dict[str, float] = {}
        for hunt in self.hunts:
            for part in hunt.parts:
                query = _query_for(part)
                floor = part.reference_price * self.thresholds.min_price_ratio
                floors[query] = min(floors.get(query, floor), floor)
        return floors

    def all_watched_parts(self) -> dict[str, Hunt]:
        """part key -> the hunt that wants it. First hunt wins on overlap."""
        mapping: dict[str, Hunt] = {}
        for hunt in self.hunts:
            for part in hunt.parts:
                mapping.setdefault(part.key, hunt)
        return mapping

    @classmethod
    def load(cls, config_path: Path, watchlist_path: Path) -> "Config":
        raw = read_config(config_path)
        general, alerts, fit = raw.get("general", {}), raw.get("alerts", {}), raw.get("fit", {})
        return cls(
            ebay_client_id=os.environ.get("EBAY_CLIENT_ID", "").strip(),
            ebay_client_secret=os.environ.get("EBAY_CLIENT_SECRET", "").strip(),
            reddit_client_id=os.environ.get("REDDIT_CLIENT_ID", "").strip(),
            reddit_client_secret=os.environ.get("REDDIT_CLIENT_SECRET", "").strip(),
            country=general.get("country", "US"),
            currency_symbol=general.get("currency_symbol", "$"),
            max_listing_age_hours=int(general.get("max_listing_age_hours", 72)),
            digest_at=alerts.get("digest_at", "GOOD"),
            push_at=alerts.get("push_at", "STRONG"),
            remind_after_days=int(alerts.get("remind_after_days", 7)),
            prebuilt_push_margin_pct=float(alerts.get("prebuilt_push_margin_pct", 5.0)),
            enforce_fit=bool(fit.get("enforce", False)),
            psu_headroom_w=int(fit.get("psu_headroom_w", 150)),
            hunts=load_watchlist(watchlist_path),
            thresholds=overlay(Thresholds(), raw.get("thresholds", {})))





def load_watchlist(path: Path = ROOT / "watchlist.toml") -> tuple[Hunt, ...]:
    """Resolve watchlist.toml into Hunts with concrete catalog parts.

    An unknown part key is a typo, and silently hunting for nothing is the kind
    of bug you don't notice for three months, so it raises.
    """
    if not path.exists():
        raise ConfigError(f"No watchlist at {path}. Copy the example and edit it.")

    raw = read_config(path)
    hunts: list[Hunt] = []

    for entry in raw.get("hunt", []):
        name = entry.get("name", "unnamed")
        parts: list[Part] = []

        for key in entry.get("parts", []):
            part = BY_KEY.get(key)
            if part is None:
                known = ", ".join(sorted(BY_KEY)[:6])
                raise ConfigError(
                    f"watchlist.toml hunt {name!r} references unknown part "
                    f"{key!r}. Valid keys live in ada/catalog.py, e.g. {known}..."
                )
            parts.append(part)

        if "class" in entry:
            candidates = in_class(entry["class"])
            floor = float(entry.get("min_vram_gb", 0))
            parts.extend(p for p in candidates if p.vram_gb >= floor)

        if not parts:
            raise ConfigError(
                f"watchlist.toml hunt {name!r} matches no parts. Give it either "
                "`parts = [...]` or a `class` filter."
            )

        # Dedupe while keeping order, so a part named explicitly and also caught
        # by a class filter is only hunted once.
        unique = tuple({p.key: p for p in parts}.values())

        hunts.append(
            Hunt(
                name=name,
                parts=unique,
                target=float(entry["target"]) if "target" in entry else None,
                quantity_wanted=int(entry.get("quantity_wanted", 1)),
                max_dollars_per_gb=(
                    float(entry["max_dollars_per_gb"])
                    if "max_dollars_per_gb" in entry
                    else None
                ),
                note=entry.get("note", ""),
            )
        )

    if not hunts:
        raise ConfigError("watchlist.toml has no [[hunt]] entries.")
    return tuple(hunts)
