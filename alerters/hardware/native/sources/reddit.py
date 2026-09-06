"""r/buildapcsales, r/homelabsales and r/hardwareswap.

The best signal-to-noise of any source here: humans have already filtered for
"this is a deal", titles are conventionally formatted as
`[GPU] Brand Model - $Price (Retailer)`, and homelabsales is where used A6000s
and A100s actually change hands.

hardwareswap follows a different convention -- `[H]ave ... [W]ant ...` -- and
needs care, because the same title format covers both "selling a 5090" and
"looking to buy a 5090". match.split_have_want handles the direction; prices
there usually live in the post body rather than the title.

Access is the awkward part, and the answer is the opposite of what it looks like.

The obvious path -- register a script app, get a client ID, use OAuth -- is no
longer available. As of August 2026 Reddit has effectively stopped issuing new
OAuth client IDs: the form at /prefs/apps submits and creates nothing, on both
the new and legacy versions. Devvit is a different product (apps that run inside
Reddit) and yields nothing usable here.

So RSS is not the fallback, it is the path. The OAuth branch below is kept
because it costs nothing and works instantly if credentials ever become
obtainable again, but nothing depends on it.

That makes anonymous reliability the whole game. Reddit blocks the `.json`
endpoints outright from most IPs (403) and throttles `.rss` erratically --
measured while building this, the same URL returned 200 and then 429 seconds
apart. Hence the backoff and request spacing in _fetch_rss: with them, both
subreddits return reliably in about 30 seconds.
"""

from __future__ import annotations

import html
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

from .base import Listing, SourceError

ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}
TIMEOUT = 30

# Anonymous-mode pacing. All unused when credentials are present.
ANON_SPACING_SECONDS = 2.5
RSS_ATTEMPTS = 3
RSS_BACKOFF_SECONDS = 4
# Reddit occasionally sends a multi-minute Retry-After. Waiting that long inside
# a 15-minute cron just collides with the next run, so cap it and try again then.
MAX_RETRY_WAIT_SECONDS = 30

# Reddit requires a descriptive UA for API access and rejects obviously
# scripted ones on the public feeds. This is the documented format.
API_UA = "python:ai-deal-alerter:0.1 (by /u/ai-deal-alerter)"
FEED_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Flairs worth reading. buildapcsales tags everything; anything not in here is
# a monitor, a case or a keyboard and can be skipped before parsing.
INTERESTING_FLAIRS = {"gpu", "cpu", "ssd", "ram", "prebuilt", "laptop", "psu"}


class RedditSource:
    def __init__(
        self,
        subreddits: tuple[str, ...] = ("buildapcsales", "homelabsales", "hardwareswap"),
        *,
        client_id: str = "",
        client_secret: str = "",
        limit: int = 100,
    ) -> None:
        self.name = "reddit"
        self.subreddits = subreddits
        self.client_id = client_id
        self.client_secret = client_secret
        self.limit = limit
        self.session = requests.Session()
        self._token: str | None = None

    # ------------------------------------------------------------------ oauth

    def _authenticate(self) -> str | None:
        """Client-credentials token. Returns None when no credentials are set."""
        if not (self.client_id and self.client_secret):
            return None
        if self._token:
            return self._token
        try:
            resp = self.session.post(
                "https://www.reddit.com/api/v1/access_token",
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": API_UA},
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            raise SourceError(f"Reddit auth request failed: {exc}") from exc
        if resp.status_code != 200:
            raise SourceError(
                f"Reddit rejected the credentials ({resp.status_code}). Check "
                "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET -- the app must be the "
                "'script' type."
            )
        self._token = resp.json().get("access_token")
        return self._token

    # ------------------------------------------------------------------ fetch

    def fetch(self) -> list[Listing]:
        token = self._authenticate()
        listings: list[Listing] = []
        failures: list[str] = []

        for index, sub in enumerate(self.subreddits):
            # Anonymous requests are throttled per IP at roughly one every two
            # seconds, and two subreddits fired back to back is exactly the
            # burst that trips it. Spacing them costs nothing on a 15-minute
            # cron and is the difference between one subreddit and both.
            if index and not token:
                time.sleep(ANON_SPACING_SECONDS)
            try:
                if token:
                    listings.extend(self._fetch_api(sub, token))
                else:
                    listings.extend(self._fetch_rss(sub))
            except SourceError as exc:
                failures.append(f"{sub}: {exc}")

        if failures and not listings:
            raise SourceError("; ".join(failures))
        if failures:
            # Partial success. Worth saying out loud -- silently returning half
            # the sources looks identical to a quiet market.
            print(
                f"  reddit: partial ({'; '.join(failures)})",
                file=sys.stderr,
            )
        return listings

    def _fetch_api(self, sub: str, token: str) -> list[Listing]:
        try:
            resp = self.session.get(
                f"https://oauth.reddit.com/r/{sub}/new",
                params={"limit": self.limit},
                headers={"Authorization": f"Bearer {token}", "User-Agent": API_UA},
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            raise SourceError(f"request failed: {exc}") from exc
        if resp.status_code != 200:
            raise SourceError(f"HTTP {resp.status_code}")

        out: list[Listing] = []
        for child in resp.json().get("data", {}).get("children", []):
            post = child.get("data") or {}
            if post.get("over_18") or post.get("stickied"):
                continue
            flair = (post.get("link_flair_text") or "").strip().lower()
            if sub == "buildapcsales" and flair and flair not in INTERESTING_FLAIRS:
                continue
            created = post.get("created_utc")
            if not created:
                continue
            out.append(
                Listing(
                    listing_id=post["id"],
                    source=f"reddit/{sub}",
                    title=post.get("title", ""),
                    url=post.get("url_overridden_by_dest")
                    or f"https://reddit.com{post.get('permalink', '')}",
                    posted_at=datetime.fromtimestamp(float(created), tz=timezone.utc),
                    body=post.get("selftext", "")[:2000],
                    extra={"flair": flair, "score": post.get("score", 0)},
                )
            )
        return out

    def _fetch_rss(self, sub: str) -> list[Listing]:
        """Anonymous fallback.

        Reddit throttles unauthenticated feed requests hard and inconsistently:
        measured while building this, the same URL returned 200 and then 429
        within seconds. A single attempt therefore fails far more often than the
        underlying limit actually requires, so this retries with backoff and
        honours Retry-After when Reddit bothers to send one.

        Retrying is only reasonable because the alternative path is blocked for
        some accounts -- with credentials, none of this is needed.
        """
        last_error = "unknown"

        for attempt in range(RSS_ATTEMPTS):
            if attempt:
                time.sleep(RSS_BACKOFF_SECONDS * attempt)
            try:
                resp = self.session.get(
                    f"https://www.reddit.com/r/{sub}/new.rss",
                    params={"limit": self.limit},
                    headers={"User-Agent": FEED_UA},
                    timeout=TIMEOUT,
                )
            except requests.RequestException as exc:
                last_error = f"request failed: {exc}"
                continue

            if resp.status_code == 429:
                wait = _retry_after(resp)
                last_error = "rate-limited (429)"
                if wait and attempt < RSS_ATTEMPTS - 1:
                    time.sleep(min(wait, MAX_RETRY_WAIT_SECONDS))
                continue
            if resp.status_code != 200:
                last_error = f"HTTP {resp.status_code}"
                continue
            break
        else:
            raise SourceError(
                f"{last_error} after {RSS_ATTEMPTS} attempts. Anonymous feeds are "
                "throttled unpredictably; setting REDDIT_CLIENT_ID / "
                "REDDIT_CLIENT_SECRET in .env removes this entirely."
            )

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as exc:
            raise SourceError(f"malformed feed: {exc}") from exc

        out: list[Listing] = []
        for entry in root.findall("a:entry", ATOM_NS):
            title = _text(entry, "a:title")
            raw_id = _text(entry, "a:id")  # "t3_1abcdef"
            if not title or not raw_id:
                continue
            link = entry.find("a:link", ATOM_NS)
            posted = _parse_iso(_text(entry, "a:updated"))
            if posted is None:
                continue
            out.append(
                Listing(
                    listing_id=raw_id.rsplit("_", 1)[-1],
                    source=f"reddit/{sub}",
                    title=html.unescape(title),
                    url=(link.get("href") if link is not None else "") or "",
                    posted_at=posted,
                    body=_strip_html(_text(entry, "a:content"))[:2000],
                )
            )
        return out


def _retry_after(resp: "requests.Response") -> int | None:
    """Seconds Reddit asked us to wait, if it said. Header is often absent."""
    raw = resp.headers.get("Retry-After") or resp.headers.get("x-ratelimit-reset")
    try:
        return max(int(float(raw)), 1) if raw else None
    except (TypeError, ValueError):
        return None


def _text(element: ET.Element, path: str) -> str:
    found = element.find(path, ATOM_NS)
    return (found.text or "").strip() if found is not None else ""


def _strip_html(raw: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html.unescape(raw)).split())


def _parse_iso(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
