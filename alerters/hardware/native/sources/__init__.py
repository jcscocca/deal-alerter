"""Deal sources. Each one fetches and parses; none of them judge."""

from __future__ import annotations

from .apple import AppleRefurbSource
from .base import Listing, Source, SourceError
from .ebay import EbaySource
from .reddit import RedditSource
from .slickdeals import SlickdealsSource

__all__ = [
    "AppleRefurbSource",
    "EbaySource",
    "Listing",
    "RedditSource",
    "SlickdealsSource",
    "Source",
    "SourceError",
]


SOURCE_NAMES = frozenset({"reddit", "slickdeals", "apple-refurb", "ebay"})


def build_sources(cfg) -> list[Source]:
    """Assemble the source list from config, skipping any that lack credentials.

    A missing eBay keyset is not an error -- it just means that source sits out
    and the rest of the run proceeds. Only Reddit-without-credentials is worth
    warning about, since it will work intermittently rather than not at all.
    """
    sources: list[Source] = [
        RedditSource(
            subreddits=cfg.reddit_subs,
            client_id=cfg.reddit_client_id,
            client_secret=cfg.reddit_client_secret,
        ),
        SlickdealsSource(
            queries=cfg.search_queries, max_age_hours=cfg.max_listing_age_hours
        ),
        AppleRefurbSource(),
    ]
    if cfg.ebay_client_id and cfg.ebay_client_secret:
        sources.append(
            EbaySource(
                queries=cfg.search_queries,
                client_id=cfg.ebay_client_id,
                client_secret=cfg.ebay_client_secret,
                price_floors=cfg.query_price_floors,
            )
        )
    # HARDWARE_SOURCES narrows a run to some of them, so Reddit's throttled
    # anonymous feed can run on its own loop instead of holding up eBay's. A
    # name that matches nothing is refused: a typo would otherwise run nothing,
    # every 15 minutes, without a word.
    if cfg.sources:
        unknown = cfg.sources - SOURCE_NAMES
        if unknown:
            raise ValueError(f"Unknown HARDWARE_SOURCES: {', '.join(sorted(unknown))}")
        sources = [source for source in sources if source.name in cfg.sources]
    return sources
