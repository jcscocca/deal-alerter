"""Bounded public deal feeds for the local dashboard, independent of alert delivery."""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import re
import threading
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

from dealcore.state import atomic_write
from .deal_overlap import amazon_asin
from .monitor_bridge import categories, number, stamp

INTERVAL = 900
MAX_AGE = 72 * 3600
MAX_BYTES = 2_000_000
USER_AGENT = "TechScout-feed-evaluation/1.0"
SOURCES = {
    "bensbargains": {"label": "Ben's Bargains", "host": "bensbargains.com",
                    "feeds": ["https://bensbargains.com/s/amazon/rss/",
                              "https://bensbargains.com/c/desktop-computers/rss/",
                              "https://bensbargains.com/c/memory/rss/"]},
    "dealnews": {"label": "DealNews", "host": "www.dealnews.com",
                 "feeds": ["https://www.dealnews.com/c39/Computers/?rss=1", "https://www.dealnews.com/?rss=1&sort=time"]},
    "nine-to-five-toys": {"label": "9to5Toys", "host": "9to5toys.com", "feeds": ["https://9to5toys.com/feed/"]},
}
TECH = re.compile(r"\b(?:DDR[345]|RAM|SSD|NVMe|DIMM|CPU|GPU|Ryzen|GeForce|Radeon|RTX|motherboard|"
                  r"laptop|notebook|desktop|computer|MacBook|Mac mini|Mac Studio|iMac|iPad|tablet|Galaxy Tab|"
                  r"monitor|keyboard|mouse|mice|router|Wi-?Fi|USB|Thunderbolt|charger|charging|power bank|"
                  r"power strip|docking|dock|hub|headphones|earbuds|AirPods|webcam|printer|microphone|"
                  r"smart ?home|smart ?plug|smart ?bulb|security camera|SD card|microSD|flash drive|"
                  r"Ethernet|NAS|power supply|PC case|gaming PC)\b", re.I)
ROUNDUP = re.compile(r"\b(?:roundup|deals|lineup|collection|sale|up to|starting (?:at|from))\b", re.I)
MERCHANTS = {"Amazon": r"amazon(?:\.com)?", "Walmart": r"walmart(?:\.com)?",
             "Newegg": r"newegg(?:\.com)?", "Best Buy": r"best\s*buy",
             "B&H": r"b\s*&\s*h(?:\s+photo(?:\s+video)?)?", "Adorama": r"adorama",
             "iBUYPOWER": r"ibuypower", "CyberPowerPC": r"cyberpowerpc", "Skytech": r"skytech(?:\s+gaming)?",
             "Dell": r"dell", "Lenovo": r"lenovo", "HP": r"hp", "Costco": r"costco",
             "Micro Center": r"micro\s*center", "Target": r"target", "Woot": r"woot!?"}


def merchant_name(value):
    if not isinstance(value, str):
        return None
    return next((name for name, pattern in MERCHANTS.items() if re.fullmatch(pattern, value.strip(), re.I)), None)


def reported_merchant(fields, title, description):
    # Structured publisher attribution takes precedence over comparison prose.
    if fields.get("retailer"):
        return merchant_name(plain(fields["retailer"]))
    for content in (title, description):
        matches = {name for name, pattern in MERCHANTS.items()
                   if re.search(r"\b(?:at|from|via)\s+" + pattern + r"\b|\b" + pattern + r"\s+(?:offers|has|is offering)\b", content, re.I)}
        if matches:
            return matches.pop() if len(matches) == 1 else None
    return None


def public_link(value, hosts=None):
    if not isinstance(value, str) or len(value) > 4000 or any(ord(c) < 33 for c in value):
        return None
    try:
        p = urlsplit(value)
        if p.scheme != "https" or p.username or p.password or p.port or not p.hostname:
            return None
        if hosts is not None and p.hostname not in hosts:
            return None
        return value  # Preserve publisher referral codes and original links.
    except ValueError:
        return None


def plain(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("script,style,iframe"):
        tag.decompose()
    return soup.get_text(" ", strip=True)


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def fingerprint(row):
    return hashlib.sha256((row["title"]+"\n"+row["description"]+"\n"+(row.get("merchant") or "")).encode()).hexdigest()


def cached_row(raw, source):
    """Validate the persisted public projection before serving it to the browser."""
    if not isinstance(raw, dict) or raw.get("source") != source:
        return None
    if not isinstance(raw.get("id"), str) or not re.fullmatch(re.escape(source)+r":[a-f0-9]{24}", raw["id"]):
        return None
    if not public_link(raw.get("url"), {SOURCES[source]["host"]}):
        return None
    for key, limit in (("title", 1500), ("description", 24000)):
        if not isinstance(raw.get(key), str) or len(raw[key]) > limit:
            return None
    if stamp(raw.get("published_at")) is None or stamp(raw.get("checked_at")) is None:
        return None
    row = {key: raw[key] for key in ("id", "source", "url", "title", "description", "published_at", "checked_at")}
    merchant = merchant_name(raw.get("merchant"))
    asin, name = raw.get("asin") if merchant == "Amazon" else None, raw.get("product_name")
    row.update(asin=asin if isinstance(asin, str) and re.fullmatch(r"[A-Z0-9]{10}", asin) else None,
               product_name=name if isinstance(name, str) and len(name) <= 1500 else None,
               expires_at=number(raw.get("expires_at")) or 0, price=number(raw.get("price")),
               source=source, retailer=SOURCES[source]["label"], merchant=merchant, lead=True,
               total=None, shipping=None, available=False, seller="Not established", condition="Not published",
               gpu=None, ram=None, potential=None, cpu="Not established", storage="Not established",
               fit="Not assessed", fit_summary="", layout_documented=False, warnings=[], rank=None,
               categories=sorted(categories(raw["title"])), reasons=["Publisher quote; retailer price and availability unverified"])
    row["terms"] = [term for term in raw.get("terms", []) if isinstance(term, str) and len(term) <= 150][:10] if isinstance(raw.get("terms"), list) else []
    return row


def parse_feed(body, source, now):
    if len(body) > MAX_BYTES or re.search(br"<!\s*(?:DOCTYPE|ENTITY)", body, re.I):
        raise ValueError("Feed exceeds supported limits")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise ValueError("Unreadable RSS feed") from exc
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("Expected RSS feed")
    items = root.findall("./channel/item")
    if len(items) > 200:
        raise ValueError("Feed exceeds supported limits")
    rows = []
    for item in items:
        fields = {node.tag.rsplit("}", 1)[-1]: node.text or "" for node in item}
        title, description = plain(fields.get("title", "")), plain(fields.get("description", ""))
        url = public_link(fields.get("link"), {SOURCES[source]["host"]})
        try:
            date = parsedate_to_datetime(fields.get("pubDate", ""))
            published = date.timestamp() if date.tzinfo else None
        except (ValueError, TypeError, OverflowError):
            published = None
        if not url or not title or len(title) > 1500 or len(description) > 24000 or published is None or not 0 <= now-published <= MAX_AGE:
            continue
        # All feeds are discovery. Keep tech from any retailer; unknown merchant
        # attribution stays unknown instead of guessing from comparison prices.
        merchant = reported_merchant(fields, title, description)
        if not TECH.search(title):
            continue
        price = None
        if fields.get("price"):
            try:
                node = next(n for n in item if n.tag.rsplit("}", 1)[-1] == "price")
                price = number(float(fields["price"])) if node.get("currency") == "USD" else None
            except (ValueError, StopIteration):
                pass
        else:
            prices = re.findall(r"\$([\d,]+(?:\.\d{1,2})?)", title)
            # A headline about savings is not the purchase price.
            if len(prices) == 1 and not re.search(r"\b(?:off|save|savings)\b", title, re.I):
                price = number(float(prices[0].replace(",", "")))
        if price is not None and not 0 < price < 1_000_000:
            price = None
        expires = stamp(fields.get("expires"))
        if expires is not None and expires <= now:
            continue
        identity = source + ":" + hashlib.sha256(url.split("#")[0].encode()).hexdigest()[:24]
        links = [a.get("href") for a in BeautifulSoup(fields.get("description", ""), "html.parser").select("a[href]")]
        asins = ({amazon_asin(link) for link in links} - {None}) if merchant == "Amazon" else set()
        terms = [label for pattern, label in [(r"\bPrime\b", "Prime terms mentioned"),
                 (r"coupon|promo code|clip|check.{0,15}box", "Coupon or code mentioned"),
                 (r"Subscribe|S&S", "Subscription terms mentioned")]
                 if re.search(pattern, title + " " + description, re.I)]
        rows.append({"id": identity, "source": source, "retailer": SOURCES[source]["label"],
                     "merchant": merchant, "title": title, "description": description, "url": url,
                     "price": price, "published_at": iso(published), "checked_at": iso(now),
                     "expires_at": min(now + INTERVAL * 2, published + MAX_AGE, expires or float("inf")),
                     "asin": next(iter(asins)) if len(asins) == 1 and not ROUNDUP.search(title) else None,
                     "terms": terms, "categories": sorted(categories(title)),
                     "lead": True, "total": None, "shipping": None, "available": False,
                     "seller": "Not established", "condition": "Not published", "gpu": None,
                     "ram": None, "potential": None, "cpu": "Not established", "storage": "Not established",
                     "fit_summary": "", "fit": "Not assessed", "layout_documented": False,
                     "rank": None, "warnings": [], "reasons": ["Publisher quote; retailer price and availability unverified"]})
    return rows


class FeedClient:
    """Only the declared feeds/articles; no Amazon pages, forms, or arbitrary redirects."""
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.robots = {}
        self.host_times = {}

    def get(self, url, *, limit=MAX_BYTES):
        hosts = {s["host"] for s in SOURCES.values()} | {"amzn.to"}
        if not public_link(url, hosts):
            raise ValueError("Unsupported host")
        host = urlsplit(url).hostname
        delay = 1 - (time.monotonic() - self.host_times.get(host, 0))
        if delay > 0:
            time.sleep(delay)
        self.host_times[host] = time.monotonic()
        with self.session.get(url, timeout=(5, 15), allow_redirects=False, stream=True) as response:
            if 300 <= response.status_code < 400:
                return b"", response.headers.get("Location", "")
            response.raise_for_status()
            chunks, size = [], 0
            started = time.monotonic()
            for chunk in response.iter_content(32768):
                size += len(chunk)
                if size > limit or time.monotonic()-started > 20:
                    raise ValueError("Response exceeds supported limits")
                chunks.append(chunk)
            return b"".join(chunks), None

    def article_allowed(self, url):
        host = urlsplit(url).hostname
        if host not in self.robots:
            try:
                body, redirect = self.get("https://" + host + "/robots.txt", limit=100_000)
                robot = RobotFileParser()
                robot.parse(body.decode("utf-8", "replace").splitlines())
                self.robots[host] = robot if body and not redirect else None
            except (requests.RequestException, ValueError):
                self.robots[host] = None
        robot = self.robots[host]
        return robot is not None and robot.can_fetch("TechScout", url)

    def enrich(self, row):
        if ROUNDUP.search(row["title"]) or not self.article_allowed(row["url"]):
            return {}
        body, redirect = self.get(row["url"])
        if redirect:
            return {}
        soup = BeautifulSoup(body, "html.parser")
        result = {}
        # Structured Product names improve exact matching without guessing from prose.
        products = []
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or script.get_text())
                nodes = data if isinstance(data, list) else [data]
                for node in nodes:
                    if isinstance(node, dict) and node.get("@type") == "Product":
                        products.append(node)
            except (ValueError, TypeError):
                pass
        if len(products) == 1 and isinstance(products[0].get("name"), str):
            result["product_name"] = products[0]["name"][:1500]
        # Read only the article body, excluding sidebar recommendations and related posts.
        scope = soup.select_one(".entry-content") if row["source"] == "nine-to-five-toys" else None
        if scope and row.get("merchant") == "Amazon":
            paragraph = next((p for p in scope.select("p") if p.select_one('a[href*="amzn.to/"], a[href*="amazon.com/"]')), None)
            if paragraph:
                links = list(dict.fromkeys(a["href"] for a in paragraph.select("a[href]")
                                          if amazon_asin(a["href"]) or public_link(a["href"], {"amzn.to"})))
                if len(links) == 1:
                    asin = amazon_asin(links[0])
                    if not asin and public_link(links[0], {"amzn.to"}):
                        _, destination = self.get(links[0], limit=100_000)
                        asin = amazon_asin(destination)
                    if asin:
                        result["asin"] = asin
        return result

    def close(self):
        self.session.close()


class DealFeeds:
    def __init__(self, directory, *, clock=time.time, client_factory=FeedClient):
        self.path = directory / "deal-feeds.json"
        self.clock, self.client_factory = clock, client_factory
        self.lock, self.stop_event = threading.Lock(), threading.Event()
        self.running, self.thread = False, None
        self.data = {"sources": {}, "metadata": {}}
        try:
            if self.path.stat().st_size <= 6_000_000:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("sources"), dict) and isinstance(data.get("metadata"), dict):
                    for source, batch in data["sources"].items():
                        if source not in SOURCES or not isinstance(batch, dict) or not isinstance(batch.get("rows"), list):
                            continue
                        self.data["sources"][source] = {"rows": [row for raw in batch["rows"][:200] if (row := cached_row(raw, source))],
                            "checked_at": batch.get("checked_at") if stamp(batch.get("checked_at")) is not None else None,
                            "attempted_at": number(batch.get("attempted_at")) or 0, "failed": batch.get("failed") is not False}
                    for batch in self.data["sources"].values():
                        for row in batch["rows"]:
                            self.data["metadata"][row["id"]] = {"fingerprint": fingerprint(row), **{k: row[k] for k in ("asin", "product_name") if row.get(k)}}
        except (OSError, ValueError):
            pass

    def start(self):
        self.thread = threading.Thread(target=self._loop, name="TechScout-deal-feeds", daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()

    def _loop(self):
        while not self.stop_event.is_set():
            self.check()
            self.stop_event.wait(30)

    def check(self):
        with self.lock:
            if self.running:
                return
            self.running = True
        client = self.client_factory()
        try:
            for source, config in SOURCES.items():
                if self.stop_event.is_set():
                    break
                with self.lock:
                    previous = self.data["sources"].get(source, {})
                last = number(previous.get("attempted_at")) or 0
                if 0 <= self.clock()-last < INTERVAL:
                    continue
                now, rows, error = self.clock(), [], False
                try:
                    for feed in config["feeds"]:
                        body, redirect = client.get(feed)
                        if redirect:
                            raise ValueError("Feed redirected")
                        rows += parse_feed(body, source, now)
                    rows = list({r["id"]: r for r in sorted(rows, key=lambda r: r["published_at"])}.values())
                except (requests.RequestException, ValueError, ET.ParseError):
                    error = True
                    rows = []
                # A small, bounded metadata pass. No outbound click tracking or Amazon fetches.
                budget = 8
                for row in rows:
                    metadata = self.data["metadata"].get(row["id"])
                    if metadata is not None and metadata.get("fingerprint") != fingerprint(row):
                        metadata = None
                    if metadata is None and budget and not self.stop_event.is_set():
                        budget -= 1
                        try:
                            metadata = client.enrich(row)
                        except (requests.RequestException, ValueError):
                            metadata = {}
                        metadata["fingerprint"] = fingerprint(row)
                        self.data["metadata"][row["id"]] = metadata
                    if isinstance(metadata, dict):
                        row.update({k: v for k, v in metadata.items() if k == "product_name" or k == "asin" and row.get("merchant") == "Amazon"})
                with self.lock:
                    self.data["sources"][source] = {"rows": previous.get("rows", []) if error else rows,
                        "checked_at": previous.get("checked_at") if error else iso(now), "failed": error,
                        "attempted_at": now}
                    active = {r["id"] for batch in self.data["sources"].values() for r in batch.get("rows", []) if isinstance(r, dict) and "id" in r}
                    self.data["metadata"] = {key: val for key, val in self.data["metadata"].items() if key in active}
                    try:
                        atomic_write(self.path, json.dumps(self.data, ensure_ascii=False, allow_nan=False))
                    except (OSError, ValueError):
                        self.data["sources"][source]["failed"] = True
        finally:
            client.close()
            with self.lock:
                self.running = False

    def snapshot(self, category, now):
        result = {"rows": [], "sources": []}
        with self.lock:
            for source, config in SOURCES.items():
                batch = self.data["sources"].get(source, {})
                checked = stamp(batch.get("checked_at"))
                fresh = checked is not None and 0 <= now-checked <= INTERVAL*2 and batch.get("failed") is False
                rows = []
                for raw in batch.get("rows", [])[:200]:
                    row = cached_row(raw, source)
                    if row is None:
                        continue
                    published = stamp(raw.get("published_at"))
                    if published is None or not 0 <= now-published <= MAX_AGE:
                        continue
                    row["expires_at"] = min(number(raw.get("expires_at")) or 0, checked + INTERVAL*2 if fresh else 0)
                    if not fresh:
                        row["reasons"] = ["Publisher feed needs a successful check"]
                    rows.append(row)
                    if category == "monitor" or category == "amazon" and row.get("merchant") == "Amazon" or category in categories(row["title"]):
                        result["rows"].append(row)
                result["sources"].append({"source": source, "label": config["label"], "jobs": 1,
                    "status": "Current" if fresh else "Last feed check failed" if batch.get("failed") else "Feed check overdue" if checked else "Not checked yet",
                    "ready": int(fresh), "count": len(rows), "checked_at": batch.get("checked_at"), "truncated": False})
        return result
