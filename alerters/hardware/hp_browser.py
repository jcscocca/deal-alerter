"""Opt-in, isolated HP page renderer and notification-free access probe.

    python -m alerters.hardware.hp_browser --probe URL --channel msedge

The worker has a fresh browser context, no personal profile or monitor secrets,
and a hard parent deadline. A successful interactive check does not establish
that a fresh headless browser or the SYSTEM task can access HP.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .retail_http import Deferred, PublicClient, Robots, public_url, retry_after
from .retailers import canonical_product, parse_hp
from .prebuilt import dollars, exact_desktop

ROOT = Path(__file__).resolve().parents[2]
CHANNELS = ("msedge", "chrome", "chromium")
MAX_BODY = 8_000_000
WORKER_SECONDS = 75


def hp_page_url(url: str) -> str:
    url = public_url(url)
    p = urlsplit(url)
    if p.hostname != "www.hp.com" or not re.fullmatch(r"/us-en/shop/(?:pdp|mdp)/[^?#]+", p.path):
        raise ValueError("HP browser only supports public US product/category pages")
    if p.query:
        raise ValueError("HP browser requires a fixed public URL without configuration selectors")
    return url


def parse_hp_rendered(body: str, url: str, now: datetime):
    """Require agreement between selected schema and the hydrated purchase area.

    HP's generic price aria-label says 'starting at' even on fixed SKUs. The
    actual sale span, exact SKU and matching purchase button must all agree;
    financing, crossed-out prices, accessory cards and stale schema cannot win.
    """
    hp_page_url(url)
    soup = BeautifulSoup(body, "html.parser")
    overview = soup.select("#pdpOverview")
    if len(overview) != 1 or len(overview[0].select("h1")) != 1:
        raise Deferred("HP rendered selected product is not ready", 300)
    cart = overview[0].select("#addtocart")
    if len(cart) != 1:
        raise Deferred("HP rendered purchase area is not ready", 300)
    cart = cart[0]
    prices = cart.select(".price-block-variations .sale-subscription-price")
    skus = cart.select(".sku")
    buttons = cart.select("#pdpAddToCartBtn")
    if len(prices) != 1 or len(skus) != 1 or len(buttons) != 1:
        raise Deferred("HP rendered price, SKU or stock is not ready", 300)
    price_text = prices[0].get_text(" ", strip=True)
    if not re.fullmatch(r"\$[\d,]+\.\d{2}", price_text):
        raise Deferred("HP rendered price is not an exact USD amount", 300)
    # Scope the existing parser to the selected product, excluding recommendations.
    selected = str(overview[0]) + "".join(str(n) for n in soup.select('script[type="application/ld+json"]'))
    offer = parse_hp(selected, url, now)
    if offer is None:
        raise Deferred("HP rendered selected product is not an OMEN desktop", 300)
    sku = skus[0].get_text(" ", strip=True).removeprefix("Product #").strip()
    if sku != offer.sku or dollars(price_text) != offer.base_price:
        raise Deferred("HP rendered price/SKU conflicts with product schema", 300)
    button = buttons[0]
    text = button.get_text(" ", strip=True).casefold()
    label = " ".join(str(button.get("aria-label", "")).split()).casefold()
    title = " ".join(offer.title.split()).casefold()
    states = {"add to cart": ("in_stock", False), "out of stock": ("out_of_stock", True),
              "sold out": ("out_of_stock", True), "pre-order": ("preorder", False)}
    if text not in states or label != text + " for " + title:
        raise Deferred("HP rendered stock does not identify the selected product", 300)
    stock, disabled = states[text]
    if stock != offer.stock or button.has_attr("disabled") != disabled or (button.get("aria-disabled") == "true" and not disabled):
        raise Deferred("HP rendered stock conflicts with product schema", 300)
    from dataclasses import replace
    return replace(offer, evidence="HP rendered fixed-SKU purchase area agrees with Product/Offer schema")


def discover_hp_rendered(body: str) -> list[str]:
    from urllib.parse import urljoin
    soup = BeautifulSoup(body, "html.parser")
    links = []
    for anchor in soup.select("#pageContent a[href]"):
        title = anchor.get_text(" ", strip=True) or anchor.get("aria-label", "")
        if "omen" not in title.lower() or not exact_desktop(title):
            continue
        try:
            url = hp_page_url(canonical_product(urljoin("https://www.hp.com", anchor["href"])))
        except ValueError:
            continue
        if "/pdp/" in url:
            links.append(url)
    if not links:
        raise Deferred("HP rendered category has no verifiable fixed-product RTX 5090 links", 300)
    return list(dict.fromkeys(links))


def clean_environment() -> dict[str, str]:
    # Explicit allowlist: never pass ntfy/eBay/SMTP credentials to browser/driver.
    allowed = {"systemroot", "windir", "comspec", "path", "pathext", "temp", "tmp",
               "tmpdir", "home", "userprofile", "localappdata", "appdata", "programfiles",
               "programfiles(x86)", "programdata", "lang", "lc_all"}
    env = {k: v for k, v in os.environ.items() if k.lower() in allowed}
    env.update(PYTHONNOUSERSITE="1", PYTHONIOENCODING="utf-8")
    return env


def stop_worker(process):
    if os.name == "nt":
        try:
            subprocess.run([str(Path(os.environ["SystemRoot"]) / "System32/taskkill.exe"),
                            "/PID", str(process.pid), "/T", "/F"], capture_output=True,
                           timeout=10, creationflags=subprocess.CREATE_NO_WINDOW, check=False)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()


def worker_python() -> str:
    executable = Path(sys.executable)
    # The service runs pythonw; the worker needs real pipe-backed stdio.
    return str(executable.with_name("python.exe") if executable.name.lower() == "pythonw.exe" else executable)


class HPBrowserReader:
    def __init__(self, channel="msedge"):
        if channel not in CHANNELS:
            raise ValueError("Unsupported HP browser channel")
        self.channel = channel

    def __call__(self, url: str, robots: Robots) -> str:
        hp_page_url(url)
        payload = json.dumps({"url": url, "channel": self.channel, "rules": robots.rules})
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        with subprocess.Popen([worker_python(), "-m", "alerters.hardware.hp_browser", "--worker"], cwd=ROOT,
                              env=clean_environment(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, text=True, encoding="utf-8", **options) as process:
            try:
                output, _ = process.communicate(payload, timeout=WORKER_SECONDS)
            except subprocess.TimeoutExpired:
                stop_worker(process)
                process.communicate(timeout=10)
                raise Deferred("HP browser exceeded its deadline; worker stopped", 300) from None
        try:
            value = json.loads(output) if len(output) <= MAX_BODY * 2 else {}
            if not isinstance(value, dict):
                raise ValueError()
            if value.get("error") in WORKER_ERRORS:
                raise Deferred(WORKER_ERRORS[value["error"]], max(300, float(value.get("retry", 300))))
            body = value["body"]
            if process.returncode or not isinstance(body, str) or len(body.encode("utf-8")) > MAX_BODY:
                raise ValueError()
            return body
        except (ValueError, KeyError, TypeError):
            raise Deferred("HP browser returned no valid page", 300) from None


WORKER_ERRORS = {
    "dependency": "HP browser dependency missing; install requirements-browser.txt",
    "browser": "HP headless browser unavailable or navigation failed",
    "timeout": "HP browser timed out waiting for verified price/stock",
    "policy": "HP browser navigation/resource disallowed by public-page policy",
    "denied": "HP browser access denied or challenge; no bypass attempted",
    "rate": "HP browser server backoff",
    "markup": "HP browser product/category evidence unavailable",
}


class BrowserFailure(Exception):
    def __init__(self, code, retry=300):
        self.code, self.retry = code, retry


def resource_allowed(url, method, resource_type, robots):
    """Read-only first-party page resources; no API, cart, login or tracking calls."""
    p = urlsplit(url)
    if method != "GET" or p.scheme != "https" or p.hostname != "www.hp.com" or p.port not in (None, 443) or p.username or p.password:
        return False
    if not robots.allows(url) or re.search(r"/(?:api|cart|checkout|login)(?:/|$)", p.path, re.I):
        return False
    if resource_type == "document":
        try:
            hp_page_url(url)
        except ValueError:
            return False
    return resource_type in {"document", "script", "stylesheet", "fetch", "xhr", "font", "image"}


def render_page(url, channel, robots):
    hp_page_url(url)
    if not robots.allows(url):
        raise BrowserFailure("policy", 21600)
    try:
        from playwright.sync_api import sync_playwright, Error, TimeoutError as BrowserTimeout
    except ImportError:
        raise BrowserFailure("dependency", 3600) from None
    with sync_playwright() as playwright:
        browser = None
        failure = []
        try:
            browser = playwright.chromium.launch(channel=channel, headless=True, chromium_sandbox=True, timeout=15000)
            context = browser.new_context(accept_downloads=False, service_workers="block")
            page = context.new_page()
            def route_request(route):
                request = route.request
                if resource_allowed(request.url, request.method, request.resource_type, robots):
                    route.continue_()
                else:
                    if request.resource_type == "document":
                        failure.append(BrowserFailure("policy", 3600))
                    route.abort()
            def response_received(response):
                if urlsplit(response.url).hostname != "www.hp.com":
                    return
                if response.status in (401, 403):
                    failure.append(BrowserFailure("denied", 3600))
                elif response.status in (429, 503):
                    failure.append(BrowserFailure("rate", max(300, retry_after(response.headers.get("retry-after")))))
            context.route("**/*", route_request)
            context.route_web_socket("**/*", lambda websocket: websocket.close())
            context.on("response", response_received)
            context.on("page", lambda popup: popup.close() if popup != page else None)
            page.on("dialog", lambda dialog: dialog.dismiss())
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if failure:
                raise failure[0]
            if response is None or response.status != 200 or page.url != url:
                raise BrowserFailure("markup")
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if failure:
                    raise failure[0]
                if re.search(r"access denied|robot check|captcha|are you a human", page.title(), re.I) or page.locator("#challenge-form").count():
                    raise BrowserFailure("denied", 3600)
                body = page.content()
                if len(body.encode("utf-8")) > MAX_BODY:
                    raise BrowserFailure("markup")
                try:
                    if "/pdp/" in url:
                        parse_hp_rendered(body, url, datetime.now(timezone.utc))
                        # Hidden/stub purchase controls cannot establish readiness.
                        if not all(page.locator(selector).is_visible() for selector in (
                            "#pdpOverview h1", "#addtocart .sku", "#addtocart .sale-subscription-price", "#pdpAddToCartBtn")):
                            raise Deferred("Purchase area not visible")
                    else:
                        discover_hp_rendered(body)
                    return body
                except Deferred:
                    page.wait_for_timeout(500)
            raise BrowserFailure("timeout")
        except BrowserTimeout:
            raise failure[0] if failure else BrowserFailure("timeout") from None
        except Error:
            raise failure[0] if failure else BrowserFailure("browser") from None
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Error:
                    pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--probe")
    parser.add_argument("--channel", choices=CHANNELS, default="msedge")
    args = parser.parse_args(argv)
    if args.worker:
        try:
            request = json.load(sys.stdin)
            robots = Robots("")
            robots.rules = request["rules"]
            body = render_page(request["url"], request["channel"], robots)
            print(json.dumps({"body": body}))
            return 0
        except BrowserFailure as exc:
            print(json.dumps({"error": exc.code, "retry": exc.retry}))
            return 1
        except Exception:
            print(json.dumps({"error": "browser", "retry": 300}))
            return 1
    if not args.probe:
        parser.error("--probe URL is required")
    try:
        url = hp_page_url(args.probe)
        body = PublicClient(hp_reader=HPBrowserReader(args.channel)).get(url)
        value = asdict(parse_hp_rendered(body, url, datetime.now(timezone.utc))) if "/pdp/" in url else {"discovered": discover_hp_rendered(body)}
        print(json.dumps({"status": "verified", "result": value}, indent=2))
        return 0
    except (Deferred, ValueError) as exc:
        print(json.dumps({"status": "unavailable", "reason": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
