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
        SlickdealsSource(queries=cfg.search_queries),
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
    return sources
