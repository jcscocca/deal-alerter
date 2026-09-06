"""Apple Certified Refurbished -- the only sane way to buy a big-memory Mac.

Apple discounts refurbs 15-20% off new, they carry the full warranty, and
high-memory Mac Studio configurations are the ones that actually show up there,
because few people order 256GB and fewer keep them.

Stock is the whole story: a 512GB Studio appears, sells within hours, and is
gone. Checked while building this, the Mac Studio refurb stock was zero -- which
is the normal state, and exactly the case for watching it on a cron.

There is no public API (the obvious /shop/api/refurb path 404s). The grid is
server-rendered into a `window.REFURB_GRID_BOOTSTRAP` blob, which is what this
parses. The /mac page carries every Mac family in one payload, so one request
covers Studio, Mini and Pro rather than three.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import requests

from .base import Listing, SourceError

GRID_URL = "https://www.apple.com/shop/refurbished/mac"
BOOTSTRAP_RE = re.compile(
    r"window\.REFURB_GRID_BOOTSTRAP\s*=\s*(\{.*?\});\s*\n", re.DOTALL
)
TIMEOUT = 30
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Families worth surfacing. MacBooks are excluded on purpose: a refurb MacBook
# Pro is a fine machine but it is not the "bigger piece of tech" this tool is
# for, and including them buries the Studios in noise.
WANTED = ("Mac Studio", "Mac Pro", "Mac mini")


class AppleRefurbSource:
    def __init__(self, families: tuple[str, ...] = WANTED) -> None:
        self.name = "apple-refurb"
        self.families = families
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA})

    def fetch(self) -> list[Listing]:
        try:
            resp = self.session.get(GRID_URL, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise SourceError(f"request failed: {exc}") from exc
        if resp.status_code != 200:
            raise SourceError(f"HTTP {resp.status_code}")

        found = BOOTSTRAP_RE.search(resp.text)
        if not found:
            raise SourceError(
                "REFURB_GRID_BOOTSTRAP not found -- Apple changed the page "
                "structure and this parser needs updating."
            )
        try:
            tiles = json.loads(found.group(1)).get("tiles") or []
        except json.JSONDecodeError as exc:
            raise SourceError(f"bootstrap JSON did not parse: {exc}") from exc

        now = datetime.now(timezone.utc)
        out: list[Listing] = []
        for tile in tiles:
            title = (tile.get("title") or "").strip()
            if not any(family in title for family in self.families):
                continue
            price = _price_of(tile)
            if price is None:
                continue
            part_number = tile.get("partNumber") or ""
            url = tile.get("productDetailsUrl") or ""
            out.append(
                Listing(
                    listing_id=part_number or url,
                    source="apple-refurb",
                    title=title,
                    url=f"https://www.apple.com{url}" if url.startswith("/") else url,
                    # Apple publishes no listing date. Refurb stock is by
                    # definition currently available, so treat it as fresh --
                    # otherwise the age filter would drop everything.
                    posted_at=now,
                    price=price,
                    condition_hint="refurbished",
                    extra={"part_number": part_number},
                )
            )
        return out


def _price_of(tile: dict) -> float | None:
    """Dig $599.00 out of price.currentPrice.raw_amount."""
    current = ((tile.get("price") or {}).get("currentPrice") or {})
    raw = current.get("raw_amount")
    if raw is None:
        # Older payloads only carried the formatted string.
        amount = current.get("amount") or ""
        raw = amount.replace("$", "").replace(",", "") or None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
