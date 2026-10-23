"""Named GPU hunts can establish exact used-item stock without price-watch overrides."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from alerters.hardware.native.config import Config
from alerters.hardware.native.sources import build_sources
from alerters.hardware.native.sources.ebay import EbaySource, ITEM_URL
from alerters.hardware.parts_plugin import PartsHardwarePlugin
from alerters.hardware.monitor_sources import Batch
from alerters.hardware.shopping_activity import judgments
from alerters.hardware.shopping_export import ShoppingExport
from alerters.techscout.dashboard import snapshot
from dealcore.notify import Channel
from dealcore.run import run
from dealcore.state import AlertState
from dealcore.types import FetchResult
from tests.test_ebay_stock import detail

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(timezone.utc)


def source(key="rtx_3090", title="NVIDIA RTX 3090 24GB graphics card", price=850,
           condition="Used", changes=None):
    item = detail(itemId="v1|123456|0", title=title, condition=condition,
                  itemWebUrl="https://www.ebay.com/itm/123456",
                  price={"value":str(price), "currency":"USD"})
    exact = item | (changes or {})
    feed = EbaySource((title,), client_id="fixture", client_secret="fixture", include_sold=False,
                      gpu_limits={key:2600})
    feed._headers = Mock(return_value={})
    feed.session.get = Mock(side_effect=lambda url, **_: SimpleNamespace(
        status_code=200, json=lambda: exact if url.startswith(ITEM_URL) else {"itemSummaries":[item]}))
    return feed


def at_run_time(row):
    shopping = {**row.extra["shopping"], "availability_checked_at":NOW.isoformat()}
    return replace(row, extra={**row.extra, "shopping":shopping})


def execute(tmp_path, rows, *, include_target_notices=False):
    plugin = PartsHardwarePlugin(ROOT / "config/hardware.toml", tmp_path, now=NOW)
    plugin.sources = (SimpleNamespace(name="fixture", fetch=lambda: FetchResult(rows)),)
    sent = []
    result = run(plugin, AlertState(plugin.state_dir / "alerts.json", plugin.normalise_key),
                 replace(plugin.options, quiet_when_empty=True, preview=tmp_path / "preview.html",
                         notify_filter=lambda item: plugin.notification_allowed(item, include_target_notices=include_target_notices)),
                 (Channel("fixture", "push", sent.append),), now=NOW)
    assert not result.problems
    return sent, result, plugin


@pytest.mark.parametrize("key,title,price,condition,bucket", [
    ("rtx_3090", "NVIDIA RTX 3090 24GB graphics card", 850, "Used", "used"),
    ("rtx_4090", "NVIDIA RTX 4090 24GB graphics card", 1050, "Used", "used"),
    ("rtx_a6000", "NVIDIA RTX A6000 48GB graphics card", 2300, "Seller Refurbished", "refurb")])
def test_native_used_and_refurb_hunts_receive_exact_stock_without_price_band(tmp_path, key, title, price, condition, bucket):
    feed = source(key, title, price, condition)
    try:
        row = at_run_time(feed.fetch()[0])
        assert row.extra["shopping"]["available"] is True
        assert row.extra["shopping"]["verified_price_watch"] == key
        assert feed.session.get.call_args.args[0] == ITEM_URL + "v1%7C123456%7C0"
        sent, result, plugin = execute(tmp_path, [row])
        assert len(sent) == 1 and result.assessments[0].verdict >= plugin.bands.EXCEPTIONAL
        assert result.assessments[0].detail.reference_trusted
        assert not plugin.card_price_watches
        assert "CARD PRICE WATCH" not in sent[0].buys[0].badge
        assert plugin.card_stock[result.assessments[0].key]["available"] is True
        assert f'"bucket": "{bucket}"' in (tmp_path / "hardware/US/prices.jsonl").read_text()
        receipts = AlertState(plugin.state_dir / "alerts.json", plugin.normalise_key)
        decisions = judgments(plugin, result, plugin.options, receipts, NOW)
        export = ShoppingExport(tmp_path / "runtime")
        export.record("gpu", Batch(listings=[row]), result.assessments, NOW, decisions)
        export.write({"gpu":{"kind":"legacy", "source":"ebay", "interval":900,
                              "last_success":NOW.timestamp(), "error":""}}, NOW.timestamp())
        projected = snapshot(tmp_path / "reports", "parts", now=NOW.timestamp(), monitor_runtime=tmp_path / "runtime")
        public = [row for group in projected["groups"] for row in group["rows"]]
        assert len(public) == 1 and public[0]["stock"] == "in_stock"
        assert public[0]["judgment"]["standout_basis"] and not public[0]["judgment"]["price_notice"]
    finally:
        feed.session.close()


@pytest.mark.parametrize("changes", [
    {"itemId":"v1|other|0"}, {"title":"NVIDIA RTX 4090 24GB graphics card"},
    {"title":"Gaming PC RTX 3090 64GB DDR5 2TB SSD"}, {"buyingOptions":["AUCTION"]},
    {"seller":{"feedbackScore":1, "feedbackPercentage":"80"}},
    {"estimatedAvailabilities":[]},
    {"estimatedAvailabilities":[{"estimatedAvailabilityStatus":"OUT_OF_STOCK"}]},
    {"price":{"value":"100", "currency":"EUR"}}, {"condition":"For parts or not working"}])
def test_detail_identity_purchase_stock_and_trust_vetoes_still_prevent_native_alerts(tmp_path, changes):
    feed = source(changes=changes)
    try:
        row = at_run_time(feed.fetch()[0])
        assert not execute(tmp_path, [row])[0]
    finally:
        feed.session.close()


def test_one_shared_stock_budget_and_duplicate_identity_are_preserved(monkeypatch):
    monkeypatch.setattr("alerters.hardware.native.sources.ebay.MAX_STOCK_CHECKS", 1)
    monkeypatch.setattr("alerters.hardware.native.sources.ebay._stock_rotation_slot", lambda:0)
    feed = source()
    try:
        first = feed._search_active("RTX 3090")[0]
        second = replace(first, listing_id="v1|second|0")
        rows = feed._verify_memory_stock([first, first, second])
        assert rows[0] is rows[1]
        assert rows[0].extra["shopping"]["available"] is True
        assert rows[2].extra["shopping"]["available"] is None
        assert "request limit" in rows[2].extra["shopping"]["availability_note"]
        assert sum(call.args[0].startswith(ITEM_URL) for call in feed.session.get.call_args_list) == 1
    finally:
        feed.session.close()


@pytest.mark.parametrize("changes", [{"price":2600.01}, {"multi_variant":True},
    {"seller_risk":"high"}, {"condition_hint":"parts"}, {"condition_hint":"unknown"}])
def test_native_gpu_lookup_budget_skips_over_ceiling_variants_and_untrusted_summaries(changes):
    feed = source()
    try:
        row = replace(feed._search_active("RTX 3090")[0], **changes)
        checked = feed._verify_memory_stock([row])[0]
        assert checked.extra["shopping"]["available"] is None
        assert not any(call.args[0].startswith(ITEM_URL) for call in feed.session.get.call_args_list)
    finally:
        feed.session.close()


def test_generic_gpu_coverage_does_not_broaden_static_50_series_condition_policy():
    feed = source("rtx_5090", "NVIDIA RTX 5090 32GB graphics card", 4500, "Used")
    feed.card_limits = {"rtx_5090":5000}
    try:
        assert feed.fetch()[0].extra["shopping"]["available"] is None
        assert not any(call.args[0].startswith(ITEM_URL) for call in feed.session.get.call_args_list)
    finally:
        feed.session.close()


@pytest.mark.parametrize("age", [1201, 3600, -1])
def test_stale_or_future_exact_gpu_stock_cannot_notify(tmp_path, age):
    feed = source()
    try:
        row = at_run_time(feed.fetch()[0])
        shopping = {**row.extra["shopping"], "availability_checked_at":(NOW-timedelta(seconds=age)).isoformat()}
        assert not execute(tmp_path, [replace(row, extra={**row.extra, "shopping":shopping})])[0]
    finally:
        feed.session.close()


def test_all_named_gpu_hunts_get_stock_ceilings_but_catch_all_does_not():
    cfg = Config.load(ROOT / "config/hardware.toml", ROOT / "config/watchlist.toml")
    cfg = replace(cfg, ebay_client_id="fixture", ebay_client_secret="fixture", sources=frozenset({"ebay"}))
    feed = build_sources(cfg)[0]
    try:
        assert feed.gpu_limits["rtx_3090"] == 1250
        assert feed.gpu_limits["rtx_4090"] == 2600
        assert "rtx_a6000" in feed.gpu_limits and "a100_40" in feed.gpu_limits
        assert all(cfg.all_watched_parts()[key].target is not None for key in feed.gpu_limits)
        assert not any(key.startswith(("ddr5_", "monitor_")) for key in feed.gpu_limits)
        assert feed.card_limits == {"rtx_5070_ti":1000, "rtx_5080":1500, "rtx_5090":5000}
    finally:
        feed.session.close()


@pytest.mark.parametrize("age", [1201, 3600, -1, None])
def test_memory_notice_requires_fresh_matching_exact_item_stock(tmp_path, age):
    feed = source("ddr5_udimm_96_kit", "Corsair DDR5 UDIMM 96GB (2x48GB) Desktop Memory", 1000, "New")
    feed.gpu_limits = {}
    feed.memory_limits = {"ddr5_udimm_96_kit":1109.99}
    try:
        row = at_run_time(feed.fetch()[0])
        assert execute(tmp_path / "fresh", [row], include_target_notices=True)[0]
        shopping = dict(row.extra["shopping"])
        if age is None:
            shopping.pop("availability_checked_at")
        else:
            shopping["availability_checked_at"] = (NOW-timedelta(seconds=age)).isoformat()
        assert not execute(tmp_path / "old", [replace(row, extra={**row.extra, "shopping":shopping})], include_target_notices=True)[0]
        shopping = {**row.extra["shopping"], "verified_price_watch":"ddr5_udimm_64"}
        assert not execute(tmp_path / "identity", [replace(row, extra={**row.extra, "shopping":shopping})], include_target_notices=True)[0]
    finally:
        feed.session.close()
