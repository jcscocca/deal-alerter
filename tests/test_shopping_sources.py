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
TITLE = "NVIDIA GeForce RTX 5080 16GB GDDR7 graphics card"


def offer(**changes):
    return replace(Offer("newegg", "ABC", "Gaming PC RTX 5080 Ryzen 9800X3D 32GB DDR5 2TB SSD", "https://www.newegg.com/p/ABC?Item=ABC",
                         "Newegg", "new", {"Memory": "2x16GB DDR5", "Memory Slots": "4", "Maximum Memory": "128GB"},
                         2100, 20, "in_stock", True, NOW.isoformat()), **changes)


def listing(source="ebay", **changes):
    return replace(Listing("123", source, TITLE, "https://www.ebay.com/itm/123", NOW,
                           price=2100, condition_hint="new", extra={"seller": "Store", "shopping": {
                               "item_price": 2000, "shipping": 100, "available": True, "stock": "in_stock", "availability_checked_at": NOW.isoformat()}}), **changes)


def assessment(row):
    return SimpleNamespace(detail=SimpleNamespace(source=row.source, listing_id=row.listing_id,
                                                  quantity=1, is_system=False, part=SimpleNamespace(name="RTX 5080")))


def publish(runtime, batch=None, *, source="ebay", at=NOW, failed=False, interval=120):
    exporter = ShoppingExport(runtime)
    batch = batch or Batch(listings=[listing()])
    exporter.record("job", batch, [assessment(row) for row in batch.listings], at)
    exporter.write({"job": {"kind": source, "interval": interval, "error": "error" if failed else "",
                            "last_success": at.timestamp()}}, NOW.timestamp())
    return exporter


def state(tmp_path, category="parts", now=None):
    return snapshot(tmp_path / "walmart", category, now=now or NOW.timestamp(), monitor_runtime=tmp_path)


def test_component_source_ranks_without_any_walmart_report(tmp_path):
    publish(tmp_path)
    result = state(tmp_path)
    row = result["groups"][0]["rows"][0]
    assert result["fresh"] and row["source"] == "ebay" and row["total"] == 2100
    assert row["facets"]["kind"] == "Graphics cards"
    assert not any(key in row for key in ("potential", "fit_summary", "prebuilt_value"))


def test_old_prebuilt_batches_and_history_do_not_reenter_feed(tmp_path):
    exporter = publish(tmp_path, Batch(offers=[offer()]), source="newegg")
    exporter.batches["job"]["rows"][0]["judgment"] = {"price_history": {"median": 2500}}
    exporter.write({"job": {"kind": "ebay", "interval": 120, "error": ""}}, NOW.timestamp())
    for category in ("parts", "monitors", "monitor"):
        result = state(tmp_path, category)
        assert result["count"] == 0 and not result["groups"] and not result["held"]
    assert not (tmp_path / "walmart" / "walmart-prebuilt-observations.json").exists()


@pytest.mark.parametrize("stock", ["out_of_stock", "unknown", "preorder"])
def test_monitor_preserves_explicit_stock_without_promoting_unavailable_offer(tmp_path, stock):
    row = listing()
    row.extra["shopping"].update(stock=stock, available=False)
    publish(tmp_path, Batch(listings=[row]))
    result = state(tmp_path)
    projected = result["held"][0]
    assert not result["groups"] and projected["stock"] == stock and not projected["available"]
    assert ("Out of stock at last check" in projected["verification_reasons"]) == (stock == "out_of_stock")


def test_independent_walmart_failure_does_not_hold_monitor(tmp_path):
    publish(tmp_path)
    app = Dashboard(tmp_path / "walmart", lambda _: 2, monitor_runtime=tmp_path, clock=lambda: NOW.timestamp())
    app.checks["parts"] = {"status": "failed", "at": NOW.timestamp()}
    assert app.state("parts")["snapshot"]["groups"][0]["rows"][0]["source"] == "ebay"
    assert app.start("monitor")[0] == 200 and app.running is None


@pytest.mark.parametrize("category", ["parts", "monitor"])
def test_source_failures_hold_components_without_build_preferences(tmp_path, category):
    publish(tmp_path, failed=True)
    result = state(tmp_path, category)
    row = result["held"][0]
    assert "preference_reasons" not in row and row["verification_reasons"]
    source = next(s for s in result["sources"] if s["source"] == "ebay")
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
    jobs = {"job": {"kind": "ebay", "interval": 120, "error": "", "last_success": NOW.timestamp()}}
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


def test_legacy_whole_pc_is_excluded_even_when_export_flag_is_missing(tmp_path):
    title = "Alienware Aurora R16 i9-12900 8GB DDR5 RTX 3090 1TB M.2 SSD Win 11 Pro"
    publish(tmp_path, Batch(listings=[listing(title=title)]))
    result = state(tmp_path, "monitor")
    assert result["count"] == 0 and not result["groups"] and not result["held"]


@pytest.mark.parametrize("changes", [{"multi_variant": True}, {"seller_risk": "high"}])
def test_ebay_variant_and_seller_guards(tmp_path, changes):
    publish(tmp_path, Batch(listings=[listing(**changes)]), source="ebay")
    assert not state(tmp_path)["groups"] and state(tmp_path)["held"]


def test_ebay_item_stock_evidence_survives_export_and_labels_unavailable_rows(tmp_path):
    row = listing()
    row.extra["shopping"].update(available=False, stock="out_of_stock",
                                 availability_checked_at=NOW.isoformat(),
                                 availability_note="eBay item detail: unavailable")
    exporter = publish(tmp_path, Batch(listings=[row]), source="ebay")
    exported = json.loads(exporter.path.read_text())["sources"][0]["rows"][0]
    assert exported["shopping"]["availability_checked_at"] == NOW.isoformat()
    result = state(tmp_path)
    assert not result["groups"]
    assert result["held"][0]["stock"] == "out_of_stock"
    assert "Out of stock at last check" in result["held"][0]["verification_reasons"]


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


def test_retired_apple_computer_source_is_not_displayed(tmp_path):
    row = listing("apple-refurb", url="https://www.apple.com/shop/product/ABC", title="Refurbished Mac Studio M3 Ultra", condition_hint="refurbished", extra={})
    publish(tmp_path, Batch(listings=[row]), source="apple-refurb")
    result = state(tmp_path, "monitor")
    assert result["count"] == 0 and not any(s["source"] == "apple-refurb" for s in result["sources"])


def test_search_availability_without_fresh_exact_item_check_is_held(tmp_path):
    row = listing()
    row.extra["shopping"].pop("availability_checked_at")
    publish(tmp_path, Batch(listings=[row]))
    result = state(tmp_path)
    assert not result["groups"] and not result["held"][0]["available"]
    assert "Exact-item stock" in result["held"][0]["verification_reasons"][0]


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


def test_newer_duplicate_component_wins_and_monitors_have_their_own_category(tmp_path):
    exporter = publish(tmp_path, at=datetime.fromtimestamp(NOW.timestamp()-30, timezone.utc))
    newer = listing()
    newer.extra["shopping"]["item_price"] = 1900
    exporter.record("new", Batch(listings=[newer]), [assessment(newer)], NOW)
    display = listing(listing_id="monitor", title="Dell AW2725Q 27-inch 4K 240Hz OLED monitor DisplayPort")
    exporter.record("display", Batch(listings=[display]), [assessment(display)], NOW)
    jobs = {key: {"kind": "ebay", "interval": 900, "error": ""} for key in ("job", "new", "display")}
    exporter.write(jobs, NOW.timestamp())
    result = state(tmp_path, "monitor")
    assert result["count"] == 2 and len(result["groups"]) == 2
    card = next(g for g in result["groups"] if g["name"].startswith("Graphics cards"))
    assert card["rows"][0]["total"] == 2000
    assert state(tmp_path, "parts")["count"] == 1
    assert state(tmp_path, "monitors")["count"] == 1


def test_initial_component_snapshot_does_not_override_failure_backoff(tmp_path, monkeypatch):
    from pathlib import Path
    from alerters.hardware import monitor
    monkeypatch.setattr(monitor, "channels", lambda **kwargs: [])
    monkeypatch.setenv("EBAY_CLIENT_ID", "test")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "test")
    future = NOW.timestamp()+3600
    key = monitor.job_id("legacy", "ebay")
    (tmp_path / "schedule.json").write_text(json.dumps({"jobs": {key: {"next": future, "error": "backoff", "failures": 1}}}))
    root = Path(__file__).resolve().parents[1]
    app = monitor.Monitor(root / "config/monitor.toml", tmp_path / "state", tmp_path, dry_run=False)
    assert app.jobs[key]["next"] == future
    assert not any(j.get("source") == "apple-refurb" for j in app.jobs.values())
    app.write_health()
    restarted = monitor.Monitor(root / "config/monitor.toml", tmp_path / "state", tmp_path, dry_run=False)
    assert restarted.jobs[key]["next"] == future
