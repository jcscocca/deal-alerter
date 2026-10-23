"""Actual 4K monitor delivery: requirements, price, stock and quiet port facts."""
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from alerters.hardware.displays import LIMITS, PRICES, WATCHES, specifications
from alerters.hardware.native.catalog import BY_KEY
from alerters.hardware.native.config import Config, _query_for
from alerters.hardware.native.match import find_part, match
from alerters.hardware.native.sources import build_sources
from alerters.hardware.native.sources.ebay import EbaySource
from alerters.hardware.prebuilt_plugin import MonitorHardwarePlugin
from alerters.hardware.shopping_activity import judgments
from alerters.techscout.facets import attributes
from dealcore.state import AlertState
from dealcore.report import render_html, render_text
from tests.test_5070_ti_watch import NOW, ROOT, card, execute
from tests.test_ebay_stock import detail


def monitor(price=299.99, **changes):
    return card(price, title='[Monitor] Alienware AW2725QF 27" 4K 180Hz IPS DisplayPort', **changes)


@pytest.mark.parametrize("title,key,hz", [
    ('Alienware AW2725QF', "monitor_4k_27_standard", 180),
    ('Alienware AW2725Q 26.7" 4K 240Hz QD-OLED', "monitor_4k_27_oled", 240),
    ('ASUS ROG Strix XG27UCS 27-inch 4K 160Hz', "monitor_4k_27_standard", 160),
    ('MSI MAG 274UPF E2 27" UHD 160Hz', "monitor_4k_27_standard", 160),
    ('MSI MPG272URX QD-OLED', "monitor_4k_27_oled", 240),
    ('LG UltraGear 27GR93U-B 144Hz', "monitor_4k_27_standard", 144),
    ('LG 27GR93U-B 27" 4K 144Hz monitor with DP cable', "monitor_4k_27_standard", 144),
    ('New Brand 27-inch 4K 144Hz IPS gaming monitor DP 1.4 HDMI', "monitor_4k_27_standard", 144),
    ('New Brand 27" 3840x2160 165Hz gaming monitor DisplayPort', "monitor_4k_27_standard", 165),
    ('New Brand 26.5" 4K 240Hz OLED gaming monitor DP 2.1', "monitor_4k_27_oled", 240),
    ('New Brand 27" 4K 240Hz WOLED monitor DisplayPort', "monitor_4k_27_oled", 240),
    ('Alienware AW2725QF no DP cable included', "monitor_4k_27_standard", 180),
    ('Alienware AW2725QF 27" dual-mode 4K 180Hz FHD 360Hz', "monitor_4k_27_standard", 180),
    ('MSI MPG 272URX 27" 4K 240Hz QD-OLED 3-year burn-in warranty', "monitor_4k_27_oled", 240),
])
def test_only_proven_required_specs_match(title, key, hz):
    specs = specifications(title)
    assert specs.key == key and specs.refresh_hz == hz
    result = match(title, price=200)
    assert result.part == BY_KEY[key] and not result.junk and not result.is_bundle
    assert find_part(title)[0] == BY_KEY[key]
    assert attributes({"title": title})["kind"] == "Monitors"
    assert "DP" in specs.ports or "DisplayPort" in specs.ports


@pytest.mark.parametrize("title", [
    '27" 4K 144Hz gaming monitor HDMI USB-C',
    '27" 4K 144Hz monitor USB-C DP Alt Mode HDMI',
    '27" 4K 144Hz monitor HDMI DP 1.4 cable included',
    '27" UHD 144Hz monitor DisplayPort',
    '27" 4K 120Hz monitor DisplayPort',
    '28" 4K 144Hz monitor DP', '32" 4K 240Hz OLED monitor DP',
    '27" 1440p 240Hz monitor supports 4K DisplayPort',
    '27" 144Hz monitor accepts 4K DisplayPort',
    '27" 4K input 144Hz monitor DP',
    '27" 4K 60Hz / 1080p 240Hz monitor DP',
    'AW2725QF 32" 4K 180Hz monitor', 'AW2725QF 4K 60Hz monitor',
    'AW2725Q dual-mode QHD 240Hz monitor DP',
    'AW2725QF OLED monitor', 'AW2725Q IPS monitor',
    'AW2725QF or AW2725Q choose model',
    'AW2725DF 27" QHD OLED 360Hz monitor DP',
    'Replacement stand for AW2725QF', 'Monitor arm for AW2725Q',
    'Screen protector for AW2725QF', 'AW2725QF screen panel only',
    'Alienware AW2725QF mainboard', 'Power supply for AW2725QF',
    'AW2725QF DisplayPort cable',
    'AW2725QF HDMI-only', 'AW2725Q no DisplayPort',
    'AW2725Q QD-OLED burn-in', 'AW2725Q cracked panel',
    'AW2725QF box only', 'AW2725QF not working',
    'Gaming PC RTX 5090 with AW2725QF monitor',
    'NVIDIA RTX 5090 + Alienware AW2725QF monitor',
    'Intel i7-14700K computer with AW2725QF monitor',
    'AW2725QF DP 1.4 is broken',
    '2 x Alienware AW2725QF monitors', 'Lot of 2 AW2725QF monitors',
    'AW2725QF 2-pack monitors',
])
def test_other_sizes_slow_modes_missing_ports_accessories_and_lots_never_match(title):
    result = match(title, price=200)
    assert result.part is None or result.junk


@pytest.mark.parametrize("title,model", [
    ('Alienware AW2725QF', "AW2725QF"),
    ('Alienware AW2725Q', "AW2725Q"),
    ('ASUS XG27UCS', "XG27UCS"),
    ('MSI MPG272URX QD-OLED', "MPG 272URX"),
])
def test_actual_push_at_limit_with_ports_and_without_pooled_value_history(tmp_path, title, model):
    row = replace(monitor(), title=title, price=LIMITS[model])
    sent, result = execute(tmp_path, row)
    assert len(sent) == 1 and result.assessments[0].target_override
    notice = sent[0].buys[0]
    assert notice.badge == "4K MONITOR PRICE WATCH · COMMUNITY LEAD"
    assert sum(fact.startswith("Ports: ") for fact in notice.facts) == 1
    for rendered in (render_text(sent[0]), render_html(sent[0])):
        assert "Ports: DP" in rendered
        assert "25% below this model" in rendered
        assert f"${PRICES[model]['benchmark']:,.2f}" in rendered
    assert "unverified" in notice.reason
    assert not result.assessments[0].loggable
    assert not result.assessments[0].detail.reference_trusted
    assert not (tmp_path / "hardware/US/prices.jsonl").read_text().strip()
    assert not execute(tmp_path / "over", replace(row, price=LIMITS[model]+.01))[0]
    # Existing receipts suppress duplicate delivery.
    assert not execute(tmp_path, row)[0]


@pytest.mark.parametrize("title", [
    'LG 27GR93U-B 27" 4K 144Hz monitor DP',
    'MSI MAG 274UPF E2 27" 4K 160Hz monitor DP',
    'New Brand 27" 4K 144Hz IPS monitor DP',
])
def test_missing_exact_model_benchmark_cannot_borrow_a_category_limit(tmp_path, title):
    sent, result = execute(tmp_path, replace(monitor(), title=title, price=200))
    assert not sent
    assert result.assessments and not result.assessments[0].target_override
    assert result.assessments[0].detail.target_price is None
    assert "benchmark is missing" in result.assessments[0].detail.reason


def test_different_models_use_their_own_thresholds(tmp_path):
    assert LIMITS["AW2725Q"] == 599.99
    assert LIMITS["MPG 272URX"] == 674.99
    sent, result = execute(tmp_path / "alienware", replace(monitor(), title='Alienware AW2725Q', price=650))
    assert not sent
    assert "Alert requires at least 25%" in result.assessments[0].detail.reason
    assert execute(tmp_path / "msi", replace(monitor(), title='MSI MPG 272URX QD-OLED', price=650))[0]


def test_watchlist_budget_cannot_raise_the_model_discount_limit(tmp_path):
    plugin = MonitorHardwarePlugin(ROOT / "config/hardware.toml", tmp_path, now=NOW)
    try:
        candidate = plugin.prepare(monitor(price=350))
        candidate = replace(candidate, hunt=replace(candidate.hunt, target=500))
        item = plugin.judge(candidate, plugin.read_history(candidate))
        assert not item.alertable and item.detail.target_price == 299.99
        candidate = replace(candidate, listing=monitor(price=275), hunt=replace(candidate.hunt, target=250))
        item = plugin.judge(candidate, plugin.read_history(candidate))
        assert not item.alertable and item.detail.target_price == 250
    finally:
        plugin.close()


@pytest.mark.parametrize("changes", [
    {"seller_risk": "high"}, {"seller_risk": "moderate"}, {"condition_hint": "used"},
    {"condition_hint": "open_box"}, {"condition_hint": "refurbished"}, {"condition_hint": "parts"},
    {"loggable": False}, {"sold": True}, {"multi_variant": True}, {"price": 20},
    {"extra": {"shopping": {"available": False}}},
    {"body": "Only this cheap after trade-in rebate"}, {"body": "DP is broken; HDMI works"},
    {"body": "DisplayPort 1.4 does not work; use HDMI"},
    {"body": "Out of stock"}, {"source": "manual"},
    {"body": "Monitor not included; stand only"},
])
def test_alert_keeps_condition_seller_price_variant_stock_and_terms_vetoes(tmp_path, changes):
    assert not execute(tmp_path, replace(monitor(), **changes))[0]


def checked_monitor():
    row = monitor(source="ebay", listing_id="v1|123|0", condition_hint="new", loggable=False)
    source = EbaySource((), client_id="fixture", client_secret="fixture", display_limits=LIMITS)
    source._headers = Mock(return_value={})
    item = detail(itemId=row.listing_id, title=row.title, price={"value": "299.99", "currency": "USD"})
    source.session.get = Mock(return_value=Mock(status_code=200, json=lambda: item))
    return source, row, item


def test_ebay_search_is_not_stock_and_exact_check_includes_shipping(tmp_path):
    source, row, _ = checked_monitor()
    try:
        assert not execute(tmp_path / "search", row)[0]
        checked = source._verify_memory_stock([row])[0]
        checked = replace(checked, extra={"shopping": {**checked.extra["shopping"], "availability_checked_at": NOW.isoformat()}})
        sent, result = execute(tmp_path / "verified", checked)
        assert len(sent) == 1 and "COMMUNITY" not in sent[0].buys[0].badge
        assert any(fact.startswith("Stock checked: ") for fact in sent[0].buys[0].facts)
        assert not result.assessments[0].loggable
        stale = {**checked.extra["shopping"], "availability_checked_at": (NOW-timedelta(hours=1)).isoformat()}
        assert not execute(tmp_path / "stale", replace(checked, extra={"shopping": stale}))[0]
    finally:
        source.session.close()


@pytest.mark.parametrize("body", [
    'DP 1.4 does not work; HDMI works', 'Monitor not included; stand only',
    'Only this price after trade-in rebate', 'Out of stock',
])
def test_exact_item_verification_retains_negative_search_description(tmp_path, body):
    source, row, _ = checked_monitor()
    try:
        checked = source._verify_memory_stock([replace(row, body=body)])[0]
        checked = replace(checked, extra={"shopping": {**checked.extra["shopping"], "availability_checked_at": NOW.isoformat()}})
        assert not execute(tmp_path, checked)[0]
    finally:
        source.session.close()


@pytest.mark.parametrize("loggable", [False, True])
def test_best_match_and_unavailable_exact_stock_cannot_alert(tmp_path, loggable):
    source, row, item = checked_monitor()
    try:
        row = replace(row, loggable=loggable)
        assert not execute(tmp_path / "search", row)[0]
        source.session.get.return_value.json = lambda: item | {"estimatedAvailabilities": [{
            "deliveryOptions": ["SHIP_TO_HOME"], "estimatedAvailabilityStatus": "OUT_OF_STOCK",
            "estimatedRemainingQuantity": 0}]}
        checked = source._verify_memory_stock([row])[0]
        checked = replace(checked, extra={"shopping": {**checked.extra["shopping"], "availability_checked_at": NOW.isoformat()}})
        assert checked.extra["shopping"]["available"] is False
        assert not execute(tmp_path / "unavailable", checked)[0]
    finally:
        source.session.close()


def test_exact_lookup_cannot_switch_models_within_the_same_panel_category(tmp_path):
    source, row, item = checked_monitor()
    try:
        source.session.get.return_value.json = lambda: item | {"title": "ASUS XG27UCS", "price": {"value": "200", "currency": "USD"}}
        checked = source._verify_memory_stock([row])[0]
        checked = replace(checked, extra={"shopping": {**checked.extra["shopping"], "availability_checked_at": NOW.isoformat()}})
        assert not execute(tmp_path, checked)[0]
    finally:
        source.session.close()


def test_saved_delivery_judgment_retains_stock_evidence(tmp_path):
    source, row, _ = checked_monitor()
    plugin = MonitorHardwarePlugin(ROOT / "config/hardware.toml", tmp_path, now=NOW)
    try:
        checked = source._verify_memory_stock([row])[0]
        checked = replace(checked, extra={"shopping": {**checked.extra["shopping"], "availability_checked_at": NOW.isoformat()}})
        candidate = plugin.prepare(checked)
        item = plugin.judge(candidate, plugin.read_history(candidate))
        assert item.alertable
        records = judgments(plugin, SimpleNamespace(assessments=[item], decisions=[]), plugin.options,
                            AlertState(plugin.state_dir / "alerts.json", plugin.normalise_key), NOW)
        stock = records[item.key]["stock_evidence"]
        assert stock["available"] is True and stock["availability_checked_at"] == NOW.isoformat()
    finally:
        source.session.close()
        plugin.close()


@pytest.mark.parametrize("changes", [
    {"title": 'AW3225QF 32" 4K 240Hz monitor'}, {"title": '27" 4K 120Hz monitor DP'},
    {"condition": "Used"}, {"estimatedAvailabilities": []}, {"shippingOptions": []},
    {"shippingOptions": [{"shippingCost": {"value": "10", "currency": "USD"}}]},
    {"price": {"value": "300", "currency": "USD"}},
    {"seller": {"feedbackScore": 1, "feedbackPercentage": "80"}},
    {"buyingOptions": ["AUCTION"]},
])
def test_ebay_details_can_veto_an_affordable_search_hit(tmp_path, changes):
    source, row, item = checked_monitor()
    source.session.get.return_value.json = lambda: item | changes
    try:
        assert not execute(tmp_path, source._verify_memory_stock([row])[0])[0]
    finally:
        source.session.close()


def test_sources_search_every_watch_and_share_existing_detail_budget():
    cfg = Config.load(ROOT / "config/hardware.toml", ROOT / "config/watchlist.toml")
    wanted = {_query_for(part) for hunt in cfg.hunts for part in hunt.parts}
    wanted |= {q for hunt in cfg.hunts for q in hunt.queries}
    assert wanted <= set(cfg.search_queries)
    assert len(cfg.search_queries) <= 40
    assert not any("gaming pc" in query.lower() for query in cfg.search_queries)
    ebay = next(source for source in build_sources(replace(cfg, ebay_client_id="fixture", ebay_client_secret="fixture")) if source.name == "ebay")
    assert ebay.display_limits == LIMITS
    assert set(WATCHES) <= set(cfg.all_watched_parts())
