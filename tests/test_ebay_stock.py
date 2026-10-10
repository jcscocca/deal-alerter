"""Newegg's $119.99 SO-DIMM search hit must not imply purchasable stock."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from alerters.hardware.native.sources.ebay import EbaySource, _availability_of, ITEM_URL
from alerters.hardware.native.sources import build_sources
from alerters.hardware.native.config import Config
from alerters.hardware.prebuilt_plugin import MonitorHardwarePlugin
from alerters.hardware.shopping_activity import judgments
from alerters.hardware.shopping_export import ShoppingExport
from dealcore.notify import Channel
from dealcore.run import run
from dealcore.state import AlertState
from dealcore.types import FetchResult, SourceError

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(timezone.utc)
ITEM = {
    "itemId": "v1|298268535773|0",
    "title": "CORSAIR Vengeance 48GB 262-Pin DDR5 SO-DIMM DDR5 4800 (PC4 38400) Laptop Memory",
    "itemWebUrl": "https://www.ebay.com/itm/298268535773",
    "price": {"value": "119.99", "currency": "USD"}, "condition": "New",
    "seller": {"username": "newegg", "feedbackScore": 1082896, "feedbackPercentage": "99.6"},
    "shippingOptions": [{"shippingCost": {"value": "0.00", "currency": "USD"}}],
    "buyingOptions": ["FIXED_PRICE"],
}


def detail(**changes):
    return deepcopy(ITEM) | {"estimatedAvailabilities": [{"deliveryOptions": ["SHIP_TO_HOME"],
        "estimatedAvailabilityStatus": "IN_STOCK", "estimatedAvailableQuantity": 1}]} | changes


def source(response=None, *, status=200, items=None, queries=("DDR5 SO-DIMM 48GB",)):
    source = EbaySource(queries, client_id="fixture", client_secret="fixture", include_sold=False,
                        memory_limits={"ddr5_sodimm_48": 300})
    source._token = "fixture"
    def get(url, **kwargs):
        if url.startswith(ITEM_URL):
            if isinstance(response, Exception):
                raise response
            return SimpleNamespace(status_code=status, json=lambda: response)
        return SimpleNamespace(status_code=200, json=lambda: {"itemSummaries": items or [deepcopy(ITEM)]})
    source.session.get = Mock(side_effect=get)
    return source


def deliveries(tmp_path, rows):
    plugin = MonitorHardwarePlugin(ROOT / "config/hardware.toml", tmp_path, now=NOW)
    try:
        plugin.sources = (SimpleNamespace(name="fixture", fetch=lambda: FetchResult(rows)),)
        sent = []
        result = run(plugin, AlertState(plugin.state_dir / "alerts.json", plugin.normalise_key),
                     replace(plugin.options, quiet_when_empty=True, preview=tmp_path / "preview.html"),
                     (Channel("fixture", "push", sent.append),), now=NOW)
        assert not result.problems
        return sent, result
    finally:
        plugin.close()


@pytest.mark.parametrize("item,expected", [
    ({}, None),
    ({"estimatedAvailabilityStatus": "IN_STOCK"}, True),
    ({"estimatedAvailabilityStatus": "OUT_OF_STOCK"}, False),
    (detail(), True),
    (detail(estimatedAvailabilities=[{"estimatedAvailabilityStatus": "OUT_OF_STOCK"}]), False),
    (detail(estimatedAvailabilities=[{"estimatedAvailabilityStatus": "IN_STOCK", "estimatedAvailableQuantity": 0}]), False),
    (detail(estimatedAvailabilities=[{"estimatedAvailableQuantity": 3}]), None),
    (detail(estimatedAvailabilities=[{"estimatedAvailabilityStatus": "PREORDER"}]), None),
    (detail(estimatedAvailabilities=[{"estimatedAvailabilityStatus": "IN_STOCK", "estimatedAvailableQuantity": "bad"}]), None),
    (detail(estimatedAvailabilities=[{"estimatedAvailabilityStatus": "IN_STOCK", "estimatedAvailableQuantity": float("nan")}]), None),
    (detail(estimatedAvailabilities=[{"estimatedAvailabilityStatus": "IN_STOCK", "estimatedAvailableQuantity": 0.5}]), None),
    (detail(estimatedAvailabilities=[None, {"estimatedAvailabilityStatus": "IN_STOCK"}]), None),
    (detail(estimatedAvailabilities=[{"estimatedAvailabilityStatus": "IN_STOCK", "deliveryOptions": ["PICKUP_IN_STORE"]}]), None),
    (detail(itemEndDate="2000-01-01T00:00:00Z"), False),
    (detail(itemEndDate="not-a-date"), None),
    (detail(itemEndDate={"bad": "date"}), None),
    (detail(estimatedAvailabilities=[{"estimatedAvailabilityStatus": "IN_STOCK"}, {"estimatedAvailabilityStatus": "OUT_OF_STOCK"}]), False),
])
def test_explicit_availability(item, expected):
    assert _availability_of(item, NOW) is expected


@pytest.mark.parametrize("response,status", [
    (deepcopy(ITEM), 200),
    (detail(estimatedAvailabilities=[{"estimatedAvailabilityStatus": "OUT_OF_STOCK", "estimatedAvailableQuantity": 0}]), 200),
    (detail(estimatedAvailabilities=[{"estimatedAvailabilityStatus": "IN_STOCK", "estimatedAvailableQuantity": 0}]), 200),
    (detail(itemEndDate="2000-01-01T00:00:00Z"), 200),
    (detail(itemId="v1|other|0"), 200),
    (detail(title="Corsair 32GB DDR5 SO-DIMM Laptop Memory"), 200),
    (detail(price={"value": "1", "currency": "EUR"}), 200),
    (detail(price={"value": "nan", "currency": "USD"}), 200),
    (detail(price={"value": "0", "currency": "USD"}), 200),
    (detail(buyingOptions=["AUCTION"]), 200),
    (detail(seller="bad data"), 200),
    (detail(condition=["New"]), 200),
    (None, 200), ([], 200), ({}, 404), ({}, 500), (ValueError("bad JSON"), 200),
    (requests.Timeout(), 200),
])
def test_unavailable_failed_or_mismatched_detail_cannot_send(tmp_path, response, status):
    rows = source(response, status=status).fetch()
    assert rows[0].extra["shopping"]["available"] is not True
    sent, result = deliveries(tmp_path, rows)
    assert not sent and not result.assessments[0].alertable


def test_real_alert_shape_needs_detail_and_saves_verification(tmp_path):
    feed = source(detail())
    assert feed._search_active("DDR5 SO-DIMM 48GB")[0].extra["shopping"]["available"] is None
    rows = feed.fetch()
    assert feed.session.get.call_args.args[0] == ITEM_URL + "v1%7C298268535773%7C0"
    assert rows[0].extra["shopping"]["stock"] == "in_stock"
    assert rows[0].extra["shopping"]["availability_checked_at"]
    sent, result = deliveries(tmp_path, rows)
    assert len(sent) == 1 and result.assessments[0].target_override
    assert "Stock checked:" in sent[0].buys[0].reason
    assert not deliveries(tmp_path, rows)[0]  # Delivery receipts still deduplicate.


@pytest.mark.parametrize("changes", [
    {"price": {"value": "350.00", "currency": "USD"}},
    {"seller": {"username": "other", "feedbackScore": 1, "feedbackPercentage": "90"}},
    {"condition": "For parts or not working"},
])
def test_detail_refreshes_price_seller_and_condition_before_judging(tmp_path, changes):
    rows = source(detail(**changes)).fetch()
    assert not deliveries(tmp_path, rows)[0]


def test_stock_check_ignores_search_claim_and_deduplicates_queries():
    feed = source(detail(estimatedAvailabilities=[]), items=[ITEM | {"estimatedAvailabilityStatus": "IN_STOCK"}],
                  queries=("DDR5 SO-DIMM 48GB", "DDR5 SO-DIMM 96GB"))
    rows = feed.fetch()
    assert all(row.extra["shopping"]["available"] is None for row in rows)
    assert sum(call.args[0].startswith(ITEM_URL) for call in feed.session.get.call_args_list) == 1


def test_request_bound_leaves_unchecked_stock_unknown(monkeypatch):
    monkeypatch.setattr("alerters.hardware.native.sources.ebay.MAX_STOCK_CHECKS", 1)
    feed = source(detail(), items=[ITEM, ITEM | {"itemId": "v1|123|0"}])
    rows = feed.fetch()
    assert rows[0].extra["shopping"]["available"] is True
    assert rows[1].extra["shopping"]["available"] is None
    assert "request limit" in rows[1].extra["shopping"]["availability_note"]


@pytest.mark.parametrize("item", [ITEM | {"price": {"value": "301", "currency": "USD"}},
    ITEM | {"itemId": "v1|298268535773|123"}, ITEM | {"title": "RTX 5090 32GB graphics card"}])
def test_only_affordable_single_memory_listings_use_detail_requests(item):
    feed = source(detail(), items=[item])
    feed.fetch()
    assert feed.session.get.call_count == 1


@pytest.mark.parametrize("status", [401, 403, 429, 503])
def test_access_and_rate_limit_failures_stop_stock_requests(status):
    feed = source({}, status=status)
    with pytest.raises(SourceError, match=str(status)):
        feed.fetch()


def test_memory_limits_follow_configured_hunts(monkeypatch):
    monkeypatch.setenv("EBAY_CLIENT_ID", "fixture")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "fixture")
    monkeypatch.setenv("HARDWARE_SOURCES", "ebay")
    cfg = Config.load(ROOT / "config/hardware.toml", ROOT / "config/watchlist.toml")
    feed = build_sources(cfg)[0]
    assert feed.memory_limits == {"ddr5_sodimm_32": 200, "ddr5_sodimm_48": 300,
                                 "ddr5_sodimm_64_kit": 400, "ddr5_sodimm_96_kit": 600}


def test_delivery_activity_retains_original_stock_and_does_not_backfill_old_receipts(tmp_path):
    rows = source(detail()).fetch()
    plugin = MonitorHardwarePlugin(ROOT / "config/hardware.toml", tmp_path, now=NOW)
    try:
        plugin.sources = (SimpleNamespace(name="fixture", fetch=lambda: FetchResult(rows)),)
        receipts = AlertState(plugin.state_dir / "alerts.json", plugin.normalise_key)
        result = run(plugin, receipts, replace(plugin.options, quiet_when_empty=True),
                     (Channel("fixture", "push", lambda report: None),), now=NOW)
        records = judgments(plugin, result, plugin.options, receipts, NOW)
        exporter = ShoppingExport(tmp_path)
        exporter.record_activity(records)
        original = next(iter(exporter.events.values()))["stock_evidence"]
        assert original["available"] is True and original["availability_checked_at"]
        for record in records.values():
            record["decisions"] = []
            record["stock_evidence"] = {"available": False, "stock": "out_of_stock"}
        restarted = ShoppingExport(tmp_path)
        restarted.record_activity(records)
        assert next(iter(restarted.events.values()))["stock_evidence"] == original
        legacy = ShoppingExport(tmp_path / "old-receipts")
        legacy.record_activity(records)
        assert "stock_evidence" not in next(iter(legacy.events.values()))
    finally:
        plugin.close()
