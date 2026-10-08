import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from dealcore.types import Listing
from alerters.hardware.monitor_sources import Batch
from alerters.hardware.prebuilt import Offer, Coupon
from alerters.hardware.shopping_export import ShoppingExport
from alerters.hardware.native.sources.ebay import _delivered_price, _shipping_of
from alerters.techscout.dashboard import Dashboard, snapshot
from alerters.techscout.monitor_bridge import safe_url

NOW = datetime(2026, 10, 7, 3, tzinfo=timezone.utc)
TITLE = "Gaming PC RTX 5080 Ryzen 9800X3D 32GB DDR5 2TB SSD"


def offer(**changes):
    return replace(Offer("newegg", "ABC", TITLE, "https://www.newegg.com/p/ABC?Item=ABC",
                         "Newegg", "new", {"Memory": "2x16GB DDR5", "Memory Slots": "4", "Maximum Memory": "128GB"},
                         2100, 20, "in_stock", True, NOW.isoformat()), **changes)


def listing(source="ebay", **changes):
    return replace(Listing("123", source, TITLE, "https://www.ebay.com/itm/123", NOW,
                           price=2100, condition_hint="new", extra={"seller": "Store", "shopping": {
                               "item_price": 2000, "shipping": 100, "available": True}}), **changes)


def assessment(row):
    return SimpleNamespace(detail=SimpleNamespace(source=row.source, listing_id=row.listing_id,
                                                  quantity=1, is_system=True, part=SimpleNamespace(name="RTX 5080")))


def publish(runtime, batch=None, *, source="newegg", at=NOW, failed=False, interval=120):
    exporter = ShoppingExport(runtime)
    batch = batch or Batch(offers=[offer()])
    exporter.record("job", batch, [assessment(row) for row in batch.listings], at)
    exporter.write({"job": {"kind": source, "interval": interval, "error": "error" if failed else "",
                            "last_success": at.timestamp()}}, NOW.timestamp())
    return exporter


def state(tmp_path, category="desktop-memory", now=None):
    return snapshot(tmp_path / "walmart", category, now=now or NOW.timestamp(), monitor_runtime=tmp_path)


def test_direct_source_ranks_without_any_walmart_report(tmp_path):
    publish(tmp_path)
    result = state(tmp_path)
    row = result["groups"][0]["rows"][0]
    assert result["fresh"] and row["source"] == "newegg"
    assert row["total"] == 2120 and row["potential"] == 96
    assert row["layout_documented"] and "unverified" in row["fit_summary"]


@pytest.mark.parametrize("stock", ["out_of_stock", "unknown", "preorder"])
def test_monitor_preserves_explicit_stock_without_promoting_unavailable_offer(tmp_path, stock):
    publish(tmp_path, Batch(offers=[offer(stock=stock)]))
    result = state(tmp_path)
    row = result["held"][0]
    assert not result["groups"] and row["stock"] == stock and not row["available"]
    assert ("Out of stock at last check" in row["verification_reasons"]) == (stock == "out_of_stock")


def test_independent_walmart_failure_does_not_hold_monitor(tmp_path):
    publish(tmp_path)
    app = Dashboard(tmp_path / "walmart", lambda _: 2, monitor_runtime=tmp_path, clock=lambda: NOW.timestamp())
    app.checks["desktop-memory"] = {"status": "failed", "at": NOW.timestamp()}
    assert app.state("desktop-memory")["snapshot"]["groups"][0]["rows"][0]["source"] == "newegg"
    assert app.start("monitor")[0] == 200 and app.running is None


@pytest.mark.parametrize("category", ["desktop-memory", "monitor"])
def test_build_preferences_are_separate_from_source_verification(tmp_path, category):
    publish(tmp_path, Batch(offers=[offer(title=TITLE.replace("32GB", "96GB"),
                                       specs={"Memory": "96GB DDR5"})]), failed=True)
    result = state(tmp_path, category)
    row = result["held"][0]
    assert row["preference_reasons"]
    assert row["verification_reasons"]
    assert set(row["preference_reasons"]).isdisjoint(row["verification_reasons"])
    source = next(s for s in result["sources"] if s["source"] == "newegg")
    assert source["status"] == "Checks need attention"


@pytest.mark.parametrize("failure", ["source", "heartbeat", "future", "dry_run", "expired"])
def test_failure_and_staleness_never_rank_old_stock(tmp_path, failure):
    publish(tmp_path, failed=failure == "source")
    path = tmp_path / "shopping-sources.json"
    data = json.loads(path.read_text())
    if failure == "heartbeat": data["heartbeat"] -= 91
    if failure == "future": data["sources"][0]["observed_at"] = "2099-01-01T00:00:00Z"
    if failure == "dry_run": data["dry_run"] = True
    if failure == "expired": data["sources"][0]["observed_at"] = "2026-10-07T01:00:00Z"
    path.write_text(json.dumps(data))
    assert not state(tmp_path)["groups"] and state(tmp_path)["held"]


def test_empty_success_replaces_prior_results_and_restart_clears_cache(tmp_path):
    exporter = publish(tmp_path)
    exporter.record("job", Batch(), [], NOW)
    jobs = {"job": {"kind": "newegg", "interval": 120, "error": "", "last_success": NOW.timestamp()}}
    exporter.write(jobs, NOW.timestamp())
    assert state(tmp_path)["count"] == 0
    publish(tmp_path)
    ShoppingExport(tmp_path).write(jobs, NOW.timestamp())
    assert state(tmp_path)["count"] == 0


def test_ebay_shipping_is_not_counted_twice_and_missing_is_held(tmp_path):
    row = listing()
    publish(tmp_path, Batch(listings=[row]), source="ebay", interval=900)
    result = state(tmp_path)
    assert result["groups"][0]["rows"][0]["total"] == 2100
    row.extra["shopping"]["shipping"] = None
    publish(tmp_path, Batch(listings=[row]), source="ebay")
    assert not state(tmp_path)["groups"]
    assert "Shipping" in " ".join(state(tmp_path)["held"][0]["reasons"])
    item = {"price": {"value": "100", "currency": "USD"}}
    assert _shipping_of(item) is None and _delivered_price(item) == 100
    item["shippingOptions"] = [{"shippingCost": {"value": "20", "currency": "USD"}}]
    assert _shipping_of(item) == 20 and _delivered_price(item) == 120


@pytest.mark.parametrize("changes", [{"multi_variant": True}, {"seller_risk": "high"}])
def test_ebay_variant_and_seller_guards(tmp_path, changes):
    publish(tmp_path, Batch(listings=[listing(**changes)]), source="ebay")
    assert not state(tmp_path)["groups"] and state(tmp_path)["held"]


def test_export_excludes_sold_unassessed_and_private_extra_fields(tmp_path):
    good = listing()
    good.extra["secret"] = "SECRET"
    exporter = ShoppingExport(tmp_path)
    exporter.record("job", Batch(listings=[good, listing(listing_id="rejected"), listing(sold=True)]), [assessment(good)], NOW)
    exporter.write({"job": {"kind": "ebay", "interval": 900}}, NOW.timestamp())
    data = json.loads(exporter.path.read_text())
    assert len(data["sources"][0]["rows"]) == 1
    assert "SECRET" not in exporter.path.read_text()


def test_community_leads_are_visible_but_not_confirmed_offers(tmp_path):
    row = listing("slickdeals", url="https://slickdeals.net/f/123-deal", title=TITLE + " $1000")
    publish(tmp_path, Batch(listings=[row]), source="slickdeals")
    result = state(tmp_path)
    assert not result["groups"] and not result["held"]
    assert result["leads"][0]["price"] == 1000 and result["leads"][0]["total"] is None


def test_apple_category_and_source_cadence(tmp_path):
    row = listing("apple-refurb", url="https://www.apple.com/shop/product/ABC", title="Refurbished Mac Studio M3 Ultra", condition_hint="refurbished", extra={})
    earlier = datetime.fromtimestamp(NOW.timestamp()-1800, timezone.utc)
    publish(tmp_path, Batch(listings=[row]), source="apple-refurb", at=earlier, interval=3600)
    assert state(tmp_path)["count"] == 0
    result = state(tmp_path, "computers")
    assert result["held"][0]["retailer"] == "Apple Refurbished"
    assert "Availability needs" not in " ".join(result["held"][0]["reasons"])
    assert state(tmp_path, "monitor")["count"] == 1


def test_coupon_expiry_recomputes_total(tmp_path):
    coupon = Coupon("SAVE", "Apply SAVE", 100, True, ends_at="2026-10-07T03:00:10Z")
    publish(tmp_path, Batch(offers=[offer(coupon=coupon)]))
    assert state(tmp_path)["groups"][0]["rows"][0]["total"] == 2020
    assert state(tmp_path, now=NOW.timestamp()+11)["groups"][0]["rows"][0]["total"] == 2120


def test_same_ids_from_different_sources_do_not_collide_and_duplicates_collapse(tmp_path):
    exporter = publish(tmp_path, Batch(listings=[listing(), listing()]), source="ebay")
    community = listing("slickdeals", url="https://slickdeals.net/f/123-deal")
    exporter.record("other", Batch(listings=[community]), [], NOW)
    jobs = {key: {"kind": source, "interval": 300, "error": ""} for key,source in [("job","ebay"),("other","slickdeals")]}
    exporter.write(jobs, NOW.timestamp())
    result = state(tmp_path)
    assert result["count"] == 2 and result["leads"][0]["id"] != result["groups"][0]["rows"][0]["id"]


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://www.newegg.com.evil.test/a", "https://www.newegg.com@evil.test/a", "http://www.newegg.com/a", "https://www.newegg.com:443/a", "https://www.newegg.com/\nfoo"])
def test_untrusted_links_cannot_escape_retailer(url):
    assert safe_url(url, "newegg") is None


def test_invalid_or_missing_export_fails_closed(tmp_path):
    for content in ("[]", "{}", "not json", '{"version":1,"sources":[null]}'):
        (tmp_path / "shopping-sources.json").write_text(content)
        assert not state(tmp_path)["groups"]


def test_newer_duplicate_wins_and_pc_component_groups_stay_separate(tmp_path):
    exporter = publish(tmp_path, at=datetime.fromtimestamp(NOW.timestamp()-30, timezone.utc))
    exporter.record("new", Batch(offers=[offer(base_price=1900)]), [], NOW)
    gpu = listing(title="NVIDIA RTX 5080 graphics card", listing_id="gpu")
    assessed = assessment(gpu)
    assessed.detail.is_system = False
    exporter.record("gpu", Batch(listings=[gpu]), [assessed], NOW)
    jobs = {key: {"kind": source, "interval": 120, "error": ""} for key, source in
            [("job", "newegg"), ("new", "newegg"), ("gpu", "ebay")]}
    exporter.write(jobs, NOW.timestamp())
    result = state(tmp_path, "monitor")
    assert result["count"] == 2 and len(result["groups"]) == 2
    desktop = next(g for g in result["groups"] if g["name"].startswith("Desktops"))
    assert desktop["rows"][0]["total"] == 1920


def test_initial_legacy_snapshot_does_not_override_failure_backoff(tmp_path, monkeypatch):
    from pathlib import Path
    from alerters.hardware import monitor
    monkeypatch.setattr(monitor, "channels", lambda **kwargs: [])
    monkeypatch.setenv("EBAY_CLIENT_ID", "test")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "test")
    future = NOW.timestamp()+3600
    jobs = {monitor.job_id("legacy", source): {"next": future, "error": "backoff" if source == "ebay" else "",
                                             "failures": 1 if source == "ebay" else 0}
            for source in ("ebay", "apple-refurb")}
    (tmp_path / "schedule.json").write_text(json.dumps({"jobs": jobs}))
    root = Path(__file__).resolve().parents[1]
    app = monitor.Monitor(root / "config/monitor.toml", tmp_path / "state", tmp_path, dry_run=False)
    assert app.jobs[monitor.job_id("legacy", "apple-refurb")]["next"] == 0
    assert app.jobs[monitor.job_id("legacy", "ebay")]["next"] == future
    app.jobs[monitor.job_id("legacy", "apple-refurb")]["next"] = future
    app.write_health()
    restarted = monitor.Monitor(root / "config/monitor.toml", tmp_path / "state", tmp_path, dry_run=False)
    assert restarted.jobs[monitor.job_id("legacy", "apple-refurb")]["next"] == future
