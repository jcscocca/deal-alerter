"""Fetch-only jobs. Workers never write hardware history or send notifications."""
from __future__ import annotations

import html
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone

from dealcore.types import Listing
from .native.sources.reddit import ATOM_NS, _parse_iso, _strip_html
from .community import SLICKDEALS_COMPUTERS, SLICKDEALS_COVERAGE, parse_slickdeals_computers
from .retail_http import Deferred, PublicClient, retry_after
from .retailers import discover_hp, discover_newegg, parse_hp, parse_newegg, reviewed_coupon


@dataclass
class Batch:
    listings: list[Listing] = field(default_factory=list)
    offers: list = field(default_factory=list)
    discovered: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def fetch_feed(kind: str, client: PublicClient, now: datetime) -> Batch:
    if kind == "slickdeals":
        return Batch(listings=parse_slickdeals_computers(client.get(SLICKDEALS_COMPUTERS), now),
                     notes=[SLICKDEALS_COVERAGE])
    if kind != "reddit":
        raise ValueError("Unknown community source")
    if kind == "reddit":
        if os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET"):
            from .native.sources.reddit import RedditSource
            import requests
            class RateSession(requests.Session):
                def request(self, method, url, **kwargs):
                    kwargs.setdefault("headers", {})["User-Agent"] = os.environ.get(
                        "REDDIT_USER_AGENT", "windows:deal-alerter:1.0 (+https://github.com/jcscocca/deal-alerter)")
                    response = super().request(method, url, **kwargs)
                    if response.status_code in (429, 503):
                        wait = max(retry_after(response.headers.get("Retry-After")),
                                   retry_after(response.headers.get("x-ratelimit-reset")), 300)
                        raise Deferred("Reddit API rate limit; server backoff", wait)
                    return response
            source = RedditSource(client_id=os.environ["REDDIT_CLIENT_ID"], client_secret=os.environ["REDDIT_CLIENT_SECRET"])
            source.session.close()
            source.session = RateSession()
            try:
                return Batch(listings=source.fetch())
            finally:
                source.session.close()
        raw = client.get("https://www.reddit.com/r/buildapcsales/new.rss?limit=100")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise Deferred("Feed parse failed; possible bot challenge", 900) from None
    out = []
    if kind == "reddit":
        if root.tag != "{http://www.w3.org/2005/Atom}feed":
            raise Deferred("Reddit feed schema changed", 900)
        for entry in root.findall("a:entry", ATOM_NS):
            def value(tag):
                return entry.findtext("a:" + tag, "", ATOM_NS)
            link = entry.find("a:link", ATOM_NS)
            posted = _parse_iso(value("published") or value("updated"))
            if posted and value("id") and value("title"):
                out.append(Listing(value("id").rsplit("_", 1)[-1], "reddit/buildapcsales",
                                   html.unescape(value("title")), link.get("href", "") if link is not None else "",
                                   posted, body=_strip_html(value("content"))))
    out = [row for row in out if 0 <= (now - row.posted_at).total_seconds() <= 72 * 3600]
    # Feed notices are unverified; the fast loop never treats absence as delisting.
    return Batch(listings=out)


def fetch_job(job: dict, client: PublicClient, coupons: list[dict]) -> Batch:
    now = datetime.now(timezone.utc)
    kind = job["kind"]
    if kind in ("reddit", "slickdeals"):
        return fetch_feed(kind, client, now)
    if kind == "legacy":
        from .native.config import Config
        from .native.sources import build_sources
        from pathlib import Path
        cfg = Config.load(Path(job["config"]), Path(job["config"]).with_name("watchlist.toml"))
        sources = [s for s in build_sources(cfg) if s.name == job["source"]]
        if not sources:
            raise Deferred("Source credentials unavailable", 3600)
        # Existing broad-watchlist eBay/Apple collection continues at its original
        # cadence. The 5-minute feeds are separate and never block retailer jobs.
        import requests
        import time
        class StopFetch(Exception):
            # Deliberately not SourceError: legacy query loops catch that and
            # continue, which would ignore a server asking the whole client to wait.
            def __init__(self, seconds):
                self.seconds = seconds
        class RateSession(requests.Session):
            def request(self, method, url, **kwargs):
                time.sleep(1)
                try:
                    response = super().request(method, url, **kwargs)
                except requests.RequestException:
                    raise StopFetch(60) from None
                if response.status_code in (429, 503):
                    raise StopFetch(max(300, retry_after(response.headers.get("Retry-After"))))
                return response
        source = sources[0]
        session = RateSession()
        session.headers.update(source.session.headers)
        source.session.close()
        source.session = session
        try:
            return Batch(listings=source.fetch())
        except StopFetch as exc:
            raise Deferred("Legacy source unavailable/rate limited; collection deferred", exc.seconds) from None
        finally:
            session.close()
    body = client.get(job["url"])
    if kind in ("discover-cyberpowerpc", "discover-skytech", "cyberpowerpc", "skytech", "ibuypower"):
        from .builders import discover_cyberpowerpc, discover_skytech, parse_cyberpowerpc, parse_skytech, parse_ibuypower_catalog
        if kind.startswith("discover-"):
            parser = discover_cyberpowerpc if kind == "discover-cyberpowerpc" else discover_skytech
            return Batch(discovered=parser(body))
        if kind == "ibuypower":
            offers = parse_ibuypower_catalog(body, now)
            limit = job.get("limit", 48)
            return Batch(offers=offers[:limit], notes=["iBUYPOWER catalog only; individual product access unverified"] +
                         (["iBUYPOWER catalog cap reached"] if len(offers) > limit else []))
        parser = parse_cyberpowerpc if kind == "cyberpowerpc" else parse_skytech
        offer = parser(body, job["url"], now)
        return Batch(offers=[offer] if offer else [])
    if kind == "discover-newegg":
        return Batch(discovered=discover_newegg(body))
    if kind == "discover-hp":
        if getattr(client, "hp_reader", None) is not None:
            from .hp_browser import discover_hp_rendered
            return Batch(discovered=discover_hp_rendered(body))
        return Batch(discovered=discover_hp(body))
    if kind not in ("hp", "newegg"):
        raise ValueError("Unknown retailer job")
    parser = parse_hp if kind == "hp" else parse_newegg
    if kind == "hp" and getattr(client, "hp_reader", None) is not None:
        from .hp_browser import parse_hp_rendered
        parser = parse_hp_rendered
    offer = parser(body, job["url"], now)
    if not offer:
        return Batch(notes=["Selected product does not contain a qualifying desktop RTX 5080/5090"])
    offer = reviewed_coupon(offer, body, coupons, now)
    return Batch(offers=[offer])
