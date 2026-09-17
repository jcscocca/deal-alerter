"""Listings you found yourself, kept in a file you can read and edit.

Every other source is a search: it decides what you get shown, and the good
listings it misses are invisible. A used 3090 posted to a local Facebook group,
a card a colleague is selling, an eBay listing somebody sent you -- none of
these reach the tool, and the price log that every future verdict is measured
against never learns they existed.

So this is the manual path in. Paste a URL and a price and the listing goes
through exactly the same matcher, verdict engine and history log as anything
eBay returned. Nothing is fetched: the URL is stored, never opened. The title
you supply is the only evidence about what the thing is, which is the same
contract every other source works under.

The store is JSONL at `state/hardware/<country>/manual.jsonl`, one entry per
line, ordered by when you added it. Deleting a line deletes the entry. Adding
the same URL twice replaces the earlier entry rather than making a second one,
so correcting a typo means re-adding it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dealcore.state import atomic_write
from dealcore.types import Listing, SourceError

# Parameters that identify the click, not the thing being sold. Two links to one
# listing differ only by these, and keeping them would file the same card twice
# under two ids -- once per route you happened to arrive by.
TRACKING = ("utm_", "fbclid", "gclid", "campid", "customid", "mkcid", "mkevt",
            "mkrid", "toolid", "siteid", "hash", "_trksid", "_trkparms",
            "ssspo", "sssrc", "ssuid", "amdata")

CONDITIONS = ("new", "open_box", "refurbished", "used", "parts", "unknown")


def canonical_url(raw: str) -> str:
    """One listing, one URL.

    Strips the fragment and the tracking parameters, then sorts what remains so
    that parameter order cannot make two identical links look different. What
    is left is kept: an option or variant id is part of *which* thing is for
    sale, and dropping it would merge two different products.
    """
    url = urlsplit(raw.strip())
    if url.scheme not in ("http", "https") or not url.netloc:
        raise ValueError("A listing URL must be http(s) and name a host")
    if "@" in url.netloc:
        raise ValueError("Refusing a URL carrying credentials")
    kept = sorted((key, value) for key, value in parse_qsl(url.query, keep_blank_values=True)
                  if not any(key.lower().startswith(bad) for bad in TRACKING))
    return urlunsplit((url.scheme, url.netloc, url.path, urlencode(kept), ""))


def entry_id(url: str) -> str:
    """Stable id for a canonical URL, and the reason re-adding replaces."""
    return sha256(url.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Entry:
    url: str
    title: str
    price: float
    condition: str = "unknown"
    # True only when you watched this actually change hands. Asking prices and
    # sold prices are different populations and the log keeps them apart, so
    # claiming a sale that did not happen quietly corrupts every later verdict
    # for the part. Nothing here can verify it; this is your word.
    sold: bool = False
    note: str = ""
    added_at: str = ""

    @property
    def listing_id(self) -> str:
        return entry_id(self.url)

    def as_listing(self) -> Listing:
        added = datetime.fromisoformat(self.added_at) if self.added_at else datetime.now(timezone.utc)
        return Listing(
            listing_id=self.listing_id,
            source="manual",
            title=self.title,
            url=self.url,
            posted_at=added if added.tzinfo else added.replace(tzinfo=timezone.utc),
            price=self.price,
            body=self.note,
            condition_hint=self.condition if self.condition != "unknown" else "",
            sold=self.sold,
            # You looked at this listing and chose to type it in. That is a
            # better sample than any search sorted by price, so it is evidence.
            loggable=True,
        )


def read(path: Path) -> list[Entry]:
    """Every entry in the store, last write per URL winning.

    A malformed line is a line you edited by hand, so it is reported rather
    than skipped: silently ignoring it would make a typo look like a deletion.
    """
    if not path.exists():
        return []
    entries: dict[str, Entry] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            entry = Entry(url=canonical_url(row["url"]), title=str(row["title"]),
                          price=float(row["price"]), condition=str(row.get("condition", "unknown")),
                          sold=bool(row.get("sold", False)), note=str(row.get("note", "")),
                          added_at=str(row.get("added_at", "")))
        except (ValueError, KeyError, TypeError) as exc:
            raise SourceError(f"{path.name} line {number}: {type(exc).__name__}") from None
        entries[entry.listing_id] = entry
    return list(entries.values())


def add(path: Path, *, url: str, price: float, title: str, condition: str = "unknown",
        sold: bool = False, note: str = "", now: datetime | None = None) -> Entry:
    """Append one entry, replacing any earlier one for the same URL."""
    if price <= 0:
        raise ValueError("Price must be positive")
    if condition not in CONDITIONS:
        raise ValueError(f"Condition must be one of: {', '.join(CONDITIONS)}")
    if not title.strip():
        raise ValueError("A title is required: it is the only evidence of what this is")
    entry = Entry(url=canonical_url(url), title=title.strip(), price=float(price),
                  condition=condition, sold=sold, note=note.strip(),
                  added_at=(now or datetime.now(timezone.utc)).isoformat())
    kept = [row for row in read(path) if row.listing_id != entry.listing_id] + [entry]
    lines = [json.dumps({"url": row.url, "title": row.title, "price": row.price,
                         "condition": row.condition, "sold": row.sold, "note": row.note,
                         "added_at": row.added_at}, sort_keys=True) for row in kept]
    atomic_write(path, "\n".join(lines) + "\n")
    return entry


class ManualSource:
    """Reads the store. Never makes a request; a stored URL is never fetched."""

    name = "manual"

    def __init__(self, path: Path) -> None:
        self.path = path

    def fetch(self) -> list[Listing]:
        return [entry.as_listing() for entry in read(self.path)]
