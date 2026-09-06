"""Source-specific identity stays in the hardware plugin."""
from __future__ import annotations


def group_id(listing_id: str) -> str:
    """The listing behind an id, with any variation option stripped off.

    eBay ids are `v1|<listing>|<variation>`, so every option of one listing
    shares the middle segment and nothing else. That segment is what dedup and
    the alert history have to key on: eBay hands back a *different* option for
    the same listing depending on which query found it -- group 147488693237
    came back as option ...036 under one query and ...039 under another in a
    single run -- so keying on the full id makes one listing look like several
    and defeats remind_after_days entirely.

    Ids from sources with no such structure come back untouched.
    """
    segments = listing_id.split("|")
    if len(segments) >= 3 and segments[-1].isdigit():
        return "|".join(segments[:-1])
    return listing_id


def normalise_key(key: str) -> str:
    source, _, listing_id = key.partition(":")
    return f"{source}:{group_id(listing_id)}" if listing_id else key
