"""Evidence from the public Slickdeals Computers category, a bounded discovery page."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from dealcore.types import Listing
from .retail_http import Deferred

SLICKDEALS_COMPUTERS = "https://slickdeals.net/computer-deals/?sort=newest"
SLICKDEALS_COVERAGE = "Slickdeals: latest public Computers category page only; search RSS unavailable"


def parse_slickdeals_computers(body: str, now: datetime) -> list[Listing]:
    soup = BeautifulSoup(body, "html.parser")
    grid = soup.select_one(".bp-p-filterGrid_items")
    if grid is None:
        raise Deferred("Slickdeals Computers category schema changed", 900)
    cards = grid.select("li.bp-p-dealCard[data-catalog-item='DealCard']")
    if not cards or len(cards) > 100:
        raise Deferred("Slickdeals Computers category has no bounded deal evidence", 900)
    out, seen = [], set()
    for card in cards:
        # Unknown status is insufficient evidence, even for an unverified notice.
        if card.get("data-label-expired") != "0":
            continue
        link = card.select_one("a.bp-c-card_title[href]")
        if link is None:
            continue
        url = urljoin(SLICKDEALS_COMPUTERS, link["href"])
        parsed = urlsplit(url)
        match = re.fullmatch(r"/f/(\d+)-[^/]+", parsed.path)
        if (parsed.scheme != "https" or parsed.netloc != "slickdeals.net"
                or not match or parsed.query or parsed.fragment):
            continue
        title = link.get_text(" ", strip=True)
        try:
            posted = datetime.fromtimestamp(int(card["data-posted-at"]), timezone.utc)
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
        identity = match[1]
        if not title or identity in seen or not 0 <= (now - posted).total_seconds() <= 72 * 3600:
            continue
        price = card.select_one(".bp-p-dealCard_price")
        if "$" not in title and price and re.fullmatch(r"\$\d[\d,]*(?:\.\d{2})?", price.get_text(strip=True)):
            title += " - " + price.get_text(strip=True)
        store = card.select_one(".bp-c-card_subtitle")
        out.append(Listing(identity, "slickdeals", title, url, posted,
                           body=store.get_text(" ", strip=True) if store else "",
                           extra={"coverage": "computers-category-first-page"}))
        seen.add(identity)
    return out
