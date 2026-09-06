"""Slickdeals search feeds -- the source that found you the ThinkPad.

Slickdeals has no public API, but every search has an RSS view, which is stable
and unauthenticated. The feed is community-vetted, so a post appearing at all is
already a signal.

Two quirks worth knowing, both observed live while building this:

  * Search is loose. A query for "rtx 3090" returns 3070 Tis and any prebuilt
    whose spec sheet mentions a 3090. That's fine -- match.py re-checks every
    title against the catalog, and system_listing() catches the prebuilts.
  * The feed carries no price field. The price is in the title, so match.py
    scrapes it, and titles without one get dropped downstream.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

from .base import Listing, SourceError

SEARCH_URL = "https://slickdeals.net/newsearch.php"
TIMEOUT = 30
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class SlickdealsSource:
    def __init__(self, queries: tuple[str, ...]) -> None:
        self.name = "slickdeals"
        self.queries = queries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA})

    def fetch(self) -> list[Listing]:
        listings: list[Listing] = []
        failures: list[str] = []
        seen: set[str] = set()

        for query in self.queries:
            try:
                for listing in self._search(query):
                    # The same thread turns up under several queries; keep the
                    # first sighting so the observation log stays one-per-deal.
                    if listing.listing_id in seen:
                        continue
                    seen.add(listing.listing_id)
                    listings.append(listing)
            except SourceError as exc:
                failures.append(f"{query!r}: {exc}")

        if failures and not listings:
            raise SourceError("; ".join(failures))
        return listings

    def _search(self, query: str) -> list[Listing]:
        try:
            resp = self.session.get(
                SEARCH_URL,
                params={
                    "q": query,
                    "searcharea": "deals",
                    "searchin": "first",
                    "rss": 1,
                },
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            raise SourceError(f"request failed: {exc}") from exc
        if resp.status_code != 200:
            raise SourceError(f"HTTP {resp.status_code}")

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as exc:
            raise SourceError(f"malformed feed: {exc}") from exc

        out: list[Listing] = []
        for item in root.findall(".//item"):
            title = _text(item, "title")
            link = _text(item, "link")
            if not title or not link:
                continue
            # guid looks like "thread-19849290"; the numeric part is stable.
            guid = _text(item, "guid") or link
            posted = _parse_rfc822(_text(item, "pubDate"))
            if posted is None:
                continue
            out.append(
                Listing(
                    listing_id=guid.replace("thread-", ""),
                    source="slickdeals",
                    title=html.unescape(title),
                    url=link,
                    posted_at=posted,
                    body=_strip_html(_text(item, "description"))[:1500],
                )
            )
        return out


def _text(element: ET.Element, tag: str) -> str:
    found = element.find(tag)
    return (found.text or "").strip() if found is not None else ""


def _strip_html(raw: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html.unescape(raw)).split())


def _parse_rfc822(raw: str) -> datetime | None:
    """Slickdeals sends "Thu, 06 Aug 26 09:20:08 +0000" -- a two-digit year.

    email.utils handles it, but returns naive datetimes for some malformed
    variants, so normalise to UTC either way.
    """
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
