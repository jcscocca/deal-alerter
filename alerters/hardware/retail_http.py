"""Polite public-page transport: no cart calls, login, or bot-challenge bypass."""
from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit

import requests

from dealcore.types import SourceError

USER_AGENT = "DealAlerter/1.0 (+https://github.com/jcscocca/deal-alerter)"
ALLOWED_HOSTS = {"www.hp.com", "www.newegg.com", "slickdeals.net", "www.reddit.com",
                 "www.cyberpowerpc.com", "skytechgaming.com", "www.ibuypower.com"}


class Deferred(SourceError):
    def __init__(self, reason: str, seconds: float = 60):
        super().__init__(reason)
        self.seconds = seconds


def retry_after(value: str | None, now: datetime | None = None) -> float:
    if not value:
        return 0
    try:
        return max(0, float(value))
    except ValueError:
        try:
            return max(0, (parsedate_to_datetime(value) - (now or datetime.now(timezone.utc))).total_seconds())
        except (ValueError, TypeError):
            return 0


def public_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("Only configured public retailer/feed HTTPS hosts are allowed")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


class Robots:
    """Longest-match robots rules including * and $, unlike urllib.robotparser."""
    def __init__(self, text: str):
        groups, agents, directives = [], [], []
        for line in text.splitlines():
            key, _, value = line.partition("#")[0].partition(":")
            key, value = key.strip().lower(), value.strip()
            if key == "user-agent":
                if directives:
                    groups.append((agents, directives))
                    agents, directives = [], []
                agents.append(value.lower())
            elif agents and key in ("allow", "disallow", "crawl-delay", "request-rate"):
                directives.append((key, value))
        groups.append((agents, directives))
        specific = [d for a, d in groups if any(x != "*" and x in USER_AGENT.lower() for x in a)]
        self.rules = [rule for group in (specific or [d for a, d in groups if "*" in a]) for rule in group]

    def delay(self) -> float:
        delays = [2.0]
        for key, value in self.rules:
            try:
                if key == "crawl-delay":
                    delays.append(float(value))
                elif key == "request-rate":
                    count, seconds = value.split("/")
                    delays.append(float(seconds) / float(count))
            except (ValueError, ZeroDivisionError):
                continue
        return max(delays)

    def allows(self, url: str) -> bool:
        p = urlsplit(url)
        path = p.path + ("?" + p.query if p.query else "")
        matches = []
        for key, pattern in self.rules:
            if key not in ("allow", "disallow") or not pattern:
                continue
            regex = re.escape(pattern.removesuffix("$")).replace(r"\*", ".*")
            if pattern.endswith("$"):
                regex += "$"
            if re.match(regex, path):
                matches.append((len(pattern.replace("*", "")), key == "allow"))
        return max(matches)[1] if matches else True


class PublicClient:
    def __init__(self, clock=time.time, sleeper=time.sleep, *, hp_reader=None):
        self.clock, self.sleep = clock, sleeper
        self.hp_reader = hp_reader
        self.hosts, self.cache, self.guard = {}, {}, threading.Lock()

    def host(self, name):
        with self.guard:
            return self.hosts.setdefault(name, {"lock": threading.Lock(), "next": 0, "robots_until": 0})

    def _request(self, url, headers=None):
        try:
            # Redirects must be checked for host and robots permission before following.
            response = requests.get(url, headers={"User-Agent": USER_AGENT, **(headers or {})},
                                    timeout=(8, 20), allow_redirects=False)
        except requests.RequestException:
            raise Deferred("Network request failed", 60) from None
        if response.status_code in (401, 403):
            raise Deferred(f"Access denied (HTTP {response.status_code}); no bypass attempted", 3600)
        if response.status_code in (429, 503):
            raise Deferred(f"HTTP {response.status_code}; server backoff", max(120, retry_after(response.headers.get("Retry-After"))))
        if response.status_code not in (200, 304, 301, 302, 303, 307, 308):
            raise Deferred(f"HTTP {response.status_code}", 900 if response.status_code in (404, 410) else 60)
        return response

    def get(self, url: str, *, redirects: int = 0) -> str:
        url = public_url(url)
        name = urlsplit(url).netloc
        host = self.host(name)
        redirect = None
        with host["lock"]:
            now = self.clock()
            if host.get("blocked_until", 0) > now:
                raise Deferred("Host is backing off", host["blocked_until"] - now)
            if host["robots_until"] <= now:
                try:
                    r = self._request(f"https://{name}/robots.txt")
                    if r.status_code != 200:
                        raise Deferred("Cannot verify robots policy", 3600)
                    host["robots"] = Robots(r.text)
                    host["robots_until"] = now + 21600
                    host["next"] = self.clock() + host["robots"].delay()
                except Deferred as exc:
                    host["blocked_until"] = self.clock() + exc.seconds
                    raise
            if not host["robots"].allows(url):
                raise Deferred("Path disallowed by robots.txt", 21600)
            wait = host["next"] - self.clock()
            if wait > 30:
                raise Deferred("Waiting for published crawl delay", wait)
            if wait > 0:
                self.sleep(wait)
            if self.hp_reader is not None and name == "www.hp.com" and urlsplit(url).path.startswith(("/us-en/shop/pdp/", "/us-en/shop/mdp/")):
                # Choose the configured transport once, before any product fetch.
                # Never respond to an HTTP denial by retrying in another client.
                try:
                    body = self.hp_reader(url, host["robots"])
                    if len(body.encode("utf-8")) > 8_000_000:
                        raise Deferred("Unexpectedly large rendered response", 3600)
                    return body
                except Deferred as exc:
                    host["blocked_until"] = self.clock() + exc.seconds
                    raise
                finally:
                    host["next"] = self.clock() + host["robots"].delay()
            prior = self.cache.get(url, {})
            headers = {k: prior[v] for k, v in (("If-None-Match", "etag"), ("If-Modified-Since", "modified")) if prior.get(v)}
            try:
                response = self._request(url, headers)
            except Deferred as exc:
                host["blocked_until"] = self.clock() + exc.seconds
                raise
            finally:
                host["next"] = self.clock() + host["robots"].delay()
            if response.status_code in (301, 302, 303, 307, 308):
                from urllib.parse import urljoin
                redirect = public_url(urljoin(url, response.headers.get("Location", "")))
            elif response.status_code == 304:
                if "body" not in prior:
                    raise Deferred("304 without cached representation", 120)
                return prior["body"]
            else:
                body = response.text
                if len(response.content) > 8_000_000:
                    raise Deferred("Unexpectedly large response", 3600)
                if re.search(r"<title>[^<]*(?:access denied|robot check|captcha|are you a human)|id=[\"']challenge-form", body, re.I):
                    host["blocked_until"] = self.clock() + 3600
                    raise Deferred("Bot challenge; manual access review required", 3600)
                self.cache[url] = {"body": body, "etag": response.headers.get("ETag"), "modified": response.headers.get("Last-Modified")}
                return body
        if redirects >= 3:
            raise Deferred("Too many redirects", 3600)
        return self.get(redirect, redirects=redirects + 1)
