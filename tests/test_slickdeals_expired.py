"""An expired Slickdeals thread is not a deal.

The 2026-09-21 digest carried "CyberPowerPC Gaming PC, AMD Ryzen 7 9850X3D,
NVIDIA GeForce RTX 5090 32GB, 32GB DDR5, 2TB SSD, SLC8400WST - $4299" (thread
20043531) with an "undercuts the cheapest loose RTX 5090" headline, hours after
Slickdeals had marked it expired. The RSS feed says nothing about expiry; the
thread page does, as "isExpiredDeal":"Yes" in its embedded data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import requests

from alerters.hardware.native.sources.slickdeals import SlickdealsSource

EXPIRED = "20043531"
LIVE = "20042181"
OLD = "20014782"


def _item(thread: str, title: str, age_hours: float) -> str:
    posted = format_datetime(datetime.now(timezone.utc) - timedelta(hours=age_hours))
    return (
        f"<item><title>{title}</title>"
        f"<link>https://slickdeals.net/f/{thread}-x?utm_source=rss</link>"
        f"<guid>thread-{thread}</guid><pubDate>{posted}</pubDate>"
        "<description>d</description></item>"
    )


FEED = (
    "<rss><channel>"
    + _item(EXPIRED, "CyberPowerPC Gaming PC, AMD Ryzen 7 9850X3D, NVIDIA GeForce "
            "RTX 5090 32GB, 32GB DDR5, 2TB SSD, SLC8400WST - $4299", 3)
    + _item(LIVE, "Acer Predator Helios 18 AI RTX 5090 $3964.99", 10)
    + _item(OLD, "HyperX OMEN MAX 16 RTX 5090 $3524.99", 24 * 7)
    + "</channel></rss>"
).encode()

PAGES = {
    EXPIRED: '..."primaryCategory":"Computers","isExpiredDeal":"Yes","threadId":20043531...',
    LIVE: '..."subCategory":"Laptops","isExpiredDeal":"No","threadId":20042181...',
}


class FakeResponse:
    def __init__(self, status_code: int, content: bytes = b"", text: str = "") -> None:
        self.status_code = status_code
        self.content = content
        self.text = text


def _source(pages: dict[str, str], fetched: list[str] | None = None) -> SlickdealsSource:
    source = SlickdealsSource(("rtx 5090",), max_age_hours=72)

    def get(url, **kwargs):
        if "newsearch.php" in url:
            return FakeResponse(200, content=FEED)
        thread = url.rstrip("/").rsplit("/", 1)[-1].split("-", 1)[0]
        if fetched is not None:
            fetched.append(thread)
        if thread not in pages:
            raise requests.ConnectionError("down")
        return FakeResponse(200, text=pages[thread])

    source.session.get = get  # type: ignore[assignment]
    return source


def test_an_expired_thread_is_dropped() -> None:
    ids = [l.listing_id for l in _source(PAGES).fetch()]
    assert EXPIRED not in ids
    assert LIVE in ids


def test_threads_too_old_to_be_used_are_not_fetched() -> None:
    """The age filter drops them downstream anyway; a page fetch per stale
    thread would be ~160 wasted requests a run."""
    fetched: list[str] = []
    ids = [l.listing_id for l in _source(PAGES, fetched).fetch()]
    assert OLD not in fetched
    assert OLD in ids


def test_an_unreadable_thread_page_keeps_the_deal() -> None:
    ids = [l.listing_id for l in _source({}).fetch()]
    assert {EXPIRED, LIVE} <= set(ids)
