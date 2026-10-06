from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from alerters.hardware.hp_browser import (
    BrowserFailure, HPBrowserReader, clean_environment, discover_hp_rendered, hp_page_url, main,
    parse_hp_rendered, render_page, resource_allowed, stop_worker, worker_python,
)
from alerters.hardware.retail_http import Deferred, PublicClient, Robots
from alerters.hardware.monitor_sources import fetch_job

URL = "https://www.hp.com/us-en/shop/pdp/omen-max-45l-gaming-dt-gt23-0990m-pc-ck4n6aa-aba"
NOW = datetime(2026, 10, 6, 23, tzinfo=timezone.utc)
FIXTURE = Path(__file__).with_name("fixtures") / "hp_rendered_5090.html"


def test_rendered_offer_requires_matching_primary_evidence():
    body = FIXTURE.read_text(encoding="utf-8")
    offer = parse_hp_rendered(body, URL, NOW)
    assert offer.confirmed and offer.sku == "CK4N6AA#ABA"
    assert offer.base_price == 8099.99 and offer.shipping == 0
    assert offer.stock == "in_stock" and offer.coupon is None
    assert "rendered" in offer.evidence


def test_rendered_out_of_stock_is_a_successful_observation():
    body = FIXTURE.read_text(encoding="utf-8").replace("InStock", "OutOfStock")
    body = body.replace("Add to cart", "Out of stock").replace('id="pdpAddToCartBtn"', 'id="pdpAddToCartBtn" disabled')
    offer = parse_hp_rendered(body, URL, NOW)
    assert offer.confirmed and offer.stock == "out_of_stock"


@pytest.mark.parametrize(("old", "new"), [
    (">$8,099.99</span>", ">$0.00</span>"),
    (">$8,099.99</span>", ">$4,999.99</span>"),
    (">$8,099.99</span>", ">From $8,099.99</span>"),
    ("Product # CK4N6AA#ABA", "Product # OTHER#ABA"),
    ("CK4N6AA#ABA", "CF1E5AV_1"),
    ("InStock", "OutOfStock"),
    ('id="pdpAddToCartBtn"', 'id="pdpAddToCartBtn" disabled'),
    ("Add to cart for OMEN", "Add to cart for different OMEN"),
    ("sale-subscription-price\"", "missing-price\""),
    ('"priceCurrency":"USD"', '"priceCurrency":"CAD"'),
])
def test_partial_stale_or_conflicting_render_fails_closed(old, new):
    body = FIXTURE.read_text(encoding="utf-8").replace(old, new)
    with pytest.raises(Deferred):
        parse_hp_rendered(body, URL, NOW)


def test_recommendation_cannot_complete_missing_main_price():
    body = FIXTURE.read_text(encoding="utf-8").replace('class="sale-subscription-price"', 'class="pending"')
    body += '<div id="similarProducts"><span class="sale-subscription-price">$499.00</span></div>'
    with pytest.raises(Deferred):
        parse_hp_rendered(body, URL, NOW)


def test_rendered_discovery_ignores_navigation_custom_and_wrong_gpu():
    title = "OMEN MAX 45L Gaming Desktop RTX 5090"
    body = f'<nav><a href="{URL}">{title}</a></nav>'
    with pytest.raises(Deferred, match="category"):
        discover_hp_rendered(body)
    body += f'<div id="pageContent"><a href="{URL}">{title}</a><a href="{URL}?config=1">{title}</a><a href="{URL}">OMEN RTX 5080 desktop</a></div>'
    assert discover_hp_rendered(body) == [URL]


@pytest.mark.parametrize("url", [
    "http://www.hp.com/us-en/shop/pdp/test", "https://www.hp.com.evil.test/us-en/shop/pdp/test",
    "https://www.hp.com/us-en/shop/cart", "https://www.hp.com/us-en/shop/custom/test",
    URL + "?config=5090", "https://user@www.hp.com/us-en/shop/pdp/test",
])
def test_browser_url_scope(url):
    with pytest.raises(ValueError):
        hp_page_url(url)


def test_resource_policy_blocks_api_cart_posts_and_external_navigation():
    robots = Robots("User-agent: *\nDisallow: /*api/\nDisallow: /private")
    assert resource_allowed(URL, "GET", "document", robots)
    assert resource_allowed("https://www.hp.com/wcsstore/main.js", "GET", "script", robots)
    for url, method, kind in [
        (URL, "POST", "document"), ("https://www.hp.com/us-en/shop/api/price", "GET", "xhr"),
        ("https://www.hp.com/us-en/shop/cart", "GET", "document"),
        ("https://localhost/test", "GET", "script"), ("https://other.test/", "GET", "document"),
        ("https://www.hp.com/private/script.js", "GET", "script"), (URL, "GET", "websocket"),
    ]:
        assert not resource_allowed(url, method, kind, robots)


def test_browser_has_no_monitor_secrets_or_injected_python_path(monkeypatch):
    for key in ("NTFY_TOKEN", "SMTP_PASSWORD", "EBAY_CLIENT_SECRET", "PYTHONPATH", "NODE_OPTIONS"):
        monkeypatch.setenv(key, "never pass this")
    env = clean_environment()
    assert not any("never pass this" == value for value in env.values())
    assert env["PYTHONNOUSERSITE"] == "1"


def test_windowless_monitor_uses_pipe_capable_worker(monkeypatch):
    path = Path("runtime") / "Scripts" / "pythonw.exe"
    monkeypatch.setattr(sys, "executable", str(path))
    assert worker_python() == str(path.with_name("python.exe"))


def test_monitor_opt_in_is_explicit_preserves_backoff_and_bounds_cadence(tmp_path, monkeypatch):
    from alerters.hardware.monitor import Monitor
    monkeypatch.setattr("alerters.hardware.monitor.channels", lambda **_: ())
    root = Path(__file__).resolve().parents[1]
    config = tmp_path / "monitor.toml"
    original = (root / "config/monitor.toml").read_text()
    config.write_text(original)
    runtime = tmp_path / "runtime"
    default = Monitor(config, tmp_path / "state", runtime, dry_run=False)
    assert default.client.hp_reader is None
    default.client.host("www.hp.com")["blocked_until"] = 9999999999
    default.write_health()
    config.write_text(original.replace("enabled = false", "enabled = true"))
    enabled = Monitor(config, tmp_path / "state", runtime, dry_run=False)
    assert enabled.client.hp_reader.channel == "msedge"
    assert enabled.client.host("www.hp.com")["blocked_until"] == 9999999999
    assert all(job["interval"] >= 300 for job in enabled.jobs.values() if job["kind"] == "hp")
    assert enabled.add_product("https://www.hp.com/us-en/shop/custom/omen-example") is None
    assert any("custom/configuration" in problem for problem in enabled.problems)


def transport(monkeypatch, *, policy="User-agent: *\nAllow: /", reader=None):
    calls, clock = [], [1000.0]
    def request(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(status_code=200, text=policy if url.endswith("robots.txt") else "http body", content=b"", headers={})
    monkeypatch.setattr("requests.get", request)
    client = PublicClient(clock=lambda: clock[0], sleeper=lambda seconds: clock.__setitem__(0, clock[0] + seconds), hp_reader=reader)
    return client, calls, clock


def test_browser_transport_shares_robots_delay_and_host_backoff(monkeypatch):
    rendered = []
    def reader(url, robots):
        rendered.append(url)
        raise Deferred("browser server cooldown", 7200)
    client, calls, clock = transport(monkeypatch, reader=reader)
    with pytest.raises(Deferred, match="server cooldown"):
        client.get(URL)
    assert clock[0] == 1002
    assert client.host("www.hp.com")["blocked_until"] == 8202
    with pytest.raises(Deferred, match="backing off"):
        client.get(URL)
    assert len(rendered) == 1 and calls == ["https://www.hp.com/robots.txt"]


def test_denied_robots_never_launches_browser(monkeypatch):
    client, _, _ = transport(monkeypatch, policy="User-agent: *\nDisallow: /us-en/shop", reader=lambda *_: pytest.fail("browser must not launch"))
    with pytest.raises(Deferred, match="robots"):
        client.get(URL)


def test_hp_reader_does_not_replace_other_retailers(monkeypatch):
    client, calls, _ = transport(monkeypatch, reader=lambda *_: pytest.fail("HP reader used for Newegg"))
    assert client.get("https://www.newegg.com/p/test") == "http body"
    assert len(calls) == 2


def test_fetch_job_uses_rendered_confirmation(monkeypatch):
    client, _, _ = transport(monkeypatch, reader=lambda *_: FIXTURE.read_text(encoding="utf-8"))
    batch = fetch_job({"kind": "hp", "url": URL}, client, [])
    assert len(batch.offers) == 1 and "rendered" in batch.offers[0].evidence


def test_worker_result_and_failure_are_sanitized(monkeypatch):
    class Worker:
        returncode = 0
        def __init__(self, command, **kwargs):
            assert command[2] == "alerters.hardware.hp_browser"
            assert kwargs["stderr"] == subprocess.DEVNULL
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def communicate(self, payload, timeout): return json.dumps(result), None
    monkeypatch.setattr(subprocess, "Popen", Worker)
    result = {"body": "rendered page"}
    reader = HPBrowserReader()
    assert reader(URL, Robots("")) == "rendered page"
    result = {"error": "rate", "retry": 7200}
    with pytest.raises(Deferred) as exc:
        reader(URL, Robots(""))
    assert exc.value.seconds == 7200
    result = {"error": "sensitive exception details"}
    with pytest.raises(Deferred, match="no valid page"):
        reader(URL, Robots(""))


def test_timeout_stops_worker_before_reporting_failure(monkeypatch):
    stopped = []
    class Worker:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def communicate(self, payload=None, timeout=None):
            if payload:
                raise subprocess.TimeoutExpired("worker", timeout)
            assert stopped == [self]
            return "", None
    monkeypatch.setattr(subprocess, "Popen", Worker)
    monkeypatch.setattr("alerters.hardware.hp_browser.stop_worker", stopped.append)
    with pytest.raises(Deferred, match="deadline"):
        HPBrowserReader()(URL, Robots(""))


def test_real_worker_process_is_stopped():
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    with subprocess.Popen([sys.executable, "-c", "import time; print('ready',flush=True); time.sleep(60)"], stdout=subprocess.PIPE, text=True, **options) as process:
        assert process.stdout.readline().strip() == "ready"
        stop_worker(process)
        process.wait(timeout=10)


def test_probe_failure_is_nonzero_and_does_not_claim_verification(monkeypatch, capsys):
    monkeypatch.setattr(PublicClient, "get", lambda *_: (_ for _ in ()).throw(Deferred("unavailable")))
    assert main(["--probe", URL]) == 1
    assert json.loads(capsys.readouterr().out) == {"status": "unavailable", "reason": "unavailable"}


def test_browser_launch_failure_is_reported_without_cleanup_error(monkeypatch):
    from contextlib import contextmanager
    playwright = pytest.importorskip("playwright.sync_api")
    def launch(**kwargs):
        assert kwargs["headless"] and kwargs["chromium_sandbox"]
        raise playwright.Error("local machine detail must not escape")
    @contextmanager
    def fake_playwright():
        yield SimpleNamespace(chromium=SimpleNamespace(launch=launch))
    monkeypatch.setattr(playwright, "sync_playwright", fake_playwright)
    with pytest.raises(BrowserFailure) as exc:
        render_page(URL, "msedge", Robots("User-agent: *\nAllow: /"))
    assert exc.value.code == "browser"


@pytest.mark.skipif(sys.platform != "win32", reason="Local Windows Edge renderer acceptance")
@pytest.mark.parametrize("status", [200, 302, 403, 429])
def test_real_edge_hydration_and_denials_without_network(monkeypatch, status):
    playwright = pytest.importorskip("playwright.sync_api")
    edge = Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe"
    if not edge.is_file():
        pytest.skip("System Edge not installed")
    original_context = playwright.Browser.new_context
    fixture = FIXTURE.read_text(encoding="utf-8")
    encoded = json.dumps(fixture).replace("<", "\\u003c")
    delayed = f'<h1>Loading</h1><script>setTimeout(() => document.body.innerHTML={encoded},250)</script>'
    navigated = []
    def offline_context(browser, **kwargs):
        context = original_context(browser, **kwargs)
        original_route = context.route
        def route(pattern, handler):
            def intercept(real_route):
                navigated.append(real_route.request.url)
                assert real_route.request.url in (URL, "http://127.0.0.1:1/blocked")
                handler(SimpleNamespace(request=real_route.request, abort=real_route.abort,
                        continue_=lambda: real_route.fulfill(status=status, headers={"Retry-After": "7200", "Location": "http://127.0.0.1:1/blocked"}, content_type="text/html", body=delayed)))
            original_route(pattern, intercept)
        context.route = route
        return context
    monkeypatch.setattr(playwright.Browser, "new_context", offline_context)
    if status == 200:
        body = render_page(URL, "msedge", Robots("User-agent: *\nAllow: /"))
        assert parse_hp_rendered(body, URL, NOW).base_price == 8099.99
    else:
        with pytest.raises(BrowserFailure) as exc:
            render_page(URL, "msedge", Robots("User-agent: *\nAllow: /"))
        assert exc.value.code == {302: "policy", 403: "denied", 429: "rate"}[status]
        assert exc.value.retry == (7200 if status == 429 else 3600)
    # Redirect responses are stopped before Chromium requests their destination.
    assert navigated == [URL]
