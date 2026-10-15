"""Newegg's unavailable $4,920.99 AORUS 5090 must never bypass a stock check."""
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from alerters.hardware.native.sources.ebay import EbaySource, ITEM_URL
from alerters.hardware.prebuilt_plugin import MonitorHardwarePlugin
from alerters.hardware.shopping_activity import judgments
from dealcore.state import AlertState
from tests.test_5070_ti_watch import NOW, ROOT, card, execute
from tests.test_ebay_stock import detail

TITLE = "GIGABYTE AORUS GeForce RTX 5090 32GB GDDR7 PCI Express 5.0 ATX Graphics Card GV-"
BODY = ("AORUS identity stickers. GeForce RTX 5090. NVIDIA GeForce RTX 50 Series. "
        "WATERFORCE water block installation guide. Part Number. Warranty notice. Quick guide. Slot Width.")
ID = "v1|800402829841|0"


def listing():
    return card(4920.99, listing_id=ID, source="ebay", title=TITLE, body=BODY,
                url="https://www.ebay.com/itm/800402829841",
                condition_hint="new", extra={"seller": "newegg", "shopping": {
                    "item_price": 4920.99, "shipping": 0, "available": None}})


def feed(item=None, status=200):
    source = EbaySource(("RTX 5090",), client_id="fixture", client_secret="fixture",
                        include_sold=False, card_limits={"rtx_5090": 5000})
    source._headers = Mock(return_value={})
    source.session.get = Mock(return_value=SimpleNamespace(status_code=status, json=lambda: item))
    return source


def api_item(**changes):
    return detail(itemId=ID, title=TITLE, price={"value": "4920.99", "currency": "USD"}, **changes)


def at_run_time(row):
    shopping = {**row.extra["shopping"], "availability_checked_at": NOW.isoformat()}
    return replace(row, extra={**row.extra, "shopping": shopping})


def test_real_best_match_shape_is_loggable_but_not_stock_verified(tmp_path):
    # This is the source shape omitted by the earlier loggable=False tests.
    source = feed({"itemSummaries": [api_item(shortDescription=BODY)]})
    try:
        row = source._search_active("RTX 5090")[0]
        assert row.loggable and row.extra["shopping"]["available"] is True
        # Even a positive summary status cannot replace exact-item evidence.
        assert not execute(tmp_path, row)[0]
    finally:
        source.session.close()


def test_incident_description_cannot_skip_the_exact_item_lookup(tmp_path):
    source = feed(api_item(estimatedAvailabilities=[{"deliveryOptions": ["SHIP_TO_HOME"],
                      "estimatedAvailabilityStatus": "OUT_OF_STOCK", "estimatedAvailableQuantity": 0,
                      "estimatedSoldQuantity": 0, "estimatedRemainingQuantity": 0}]))
    try:
        checked = source._verify_memory_stock([listing()])[0]
        assert source.session.get.call_args.args[0] == ITEM_URL + "v1%7C800402829841%7C0"
        assert checked.extra["shopping"]["available"] is False
        assert not checked.loggable
        assert not execute(tmp_path, checked)[0]
    finally:
        source.session.close()


@pytest.mark.parametrize("shopping", [
    {}, {"available": None}, {"available": False}, {"available": True},
    {"available": True, "availability_checked_at": NOW.isoformat()},
    {"available": True, "verified_price_watch": "rtx_5080", "availability_checked_at": NOW.isoformat()},
    {"available": True, "verified_price_watch": "rtx_5090", "availability_checked_at": (NOW-timedelta(hours=1)).isoformat()},
])
def test_loggable_search_never_substitutes_for_fresh_exact_stock(tmp_path, shopping):
    assert not execute(tmp_path, replace(listing(), extra={"shopping": shopping}))[0]


@pytest.mark.parametrize("status", [404, 500])
def test_failed_item_checks_cannot_alert_loggable_cards(tmp_path, status):
    source = feed({}, status=status)
    try:
        assert not execute(tmp_path, source._verify_memory_stock([listing()])[0])[0]
    finally:
        source.session.close()


def test_request_budget_defers_card_without_alerting(tmp_path, monkeypatch):
    monkeypatch.setattr("alerters.hardware.native.sources.ebay.MAX_STOCK_CHECKS", 0)
    source = feed(api_item())
    try:
        row = source._verify_memory_stock([listing()])[0]
        assert not source.session.get.called
        assert "request limit" in row.extra["shopping"]["availability_note"]
        assert not execute(tmp_path, row)[0]
    finally:
        source.session.close()


def test_confirmed_card_still_sends_at_max_priority_and_keeps_stock_evidence(tmp_path):
    source = feed(api_item())
    plugin = MonitorHardwarePlugin(ROOT / "config/hardware.toml", tmp_path, now=NOW)
    try:
        row = at_run_time(source._verify_memory_stock([listing()])[0])
        sent, result = execute(tmp_path, row)
        assert len(sent) == 1 and sent[0].buys[0].priority == 5
        assert "Stock checked:" in " ".join(sent[0].buys[0].facts)
        candidate = plugin.prepare(row)
        item = plugin.judge(candidate, plugin.read_history(candidate))
        records = judgments(plugin, SimpleNamespace(assessments=[item], decisions=[]), plugin.options,
                            AlertState(plugin.state_dir / "alerts.json", plugin.normalise_key), NOW)
        stock = records[item.key]["stock_evidence"]
        assert stock["available"] is True and stock["availability_checked_at"] == NOW.isoformat()
    finally:
        source.session.close()
        plugin.close()
