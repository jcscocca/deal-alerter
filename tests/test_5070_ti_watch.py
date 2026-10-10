"""5070 Ti alerts: actual delivery, identity, price and RAM boundaries."""
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from alerters.hardware.builders import discover_skytech
from alerters.hardware.native.match import match
from alerters.hardware.prebuilt import Offer, gpu_model
from alerters.hardware.prebuilt_plugin import MonitorHardwarePlugin, offer_listing
from alerters.hardware.prebuilt_specs import build_specs
from alerters.hardware.retailers import parse_newegg, discover_newegg
from alerters.hardware.retail_http import Deferred
from dealcore.notify import Channel
from dealcore.run import run
from dealcore.state import AlertState
from dealcore.types import FetchResult, Listing

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(timezone.utc)


def card(price=900, **changes):
    return replace(Listing("5070-card", "slickdeals", "[GPU] Gigabyte RTX 5070 Ti 16GB graphics card",
                           "https://example.invalid/gpu", NOW, price=price), **changes)


def pc(price=2100, capacity=32, **changes):
    return replace(Offer("newegg", "5070-pc", "Gaming Desktop RTX 5070 Ti 16GB GDDR7",
                         "https://example.invalid/pc", "Newegg", "new",
                         {"RAM": f"{capacity}GB DDR5 (2 x {capacity//2}GB)",
                          "Memory Slots": "4", "Maximum Memory": "128GB"},
                         price, 0, "in_stock", True, NOW.isoformat()), **changes)


def execute(tmp_path, row):
    plugin = MonitorHardwarePlugin(ROOT / "config/hardware.toml", tmp_path, now=NOW)
    try:
        listing = offer_listing(row) if isinstance(row, Offer) else row
        plugin.sources = (SimpleNamespace(name="fixture", fetch=lambda: FetchResult([listing])),)
        sent = []
        result = run(plugin, AlertState(plugin.state_dir / "alerts.json", plugin.normalise_key),
                     replace(plugin.options, quiet_when_empty=True, preview=tmp_path / "preview.html"),
                     (Channel("fixture", "push", sent.append),), now=NOW)
        assert not result.problems
        return sent, result
    finally:
        plugin.close()


@pytest.mark.parametrize("spelling", ["RTX 5070 Ti", "RTX5070TI", "RTX 5070ti"])
def test_card_and_prebuilt_share_exact_desktop_identity(spelling):
    assert gpu_model(spelling) == "5070 Ti"
    assert match(f"{spelling} 16GB graphics card", price=900).part.key == "rtx_5070_ti"
    build = build_specs(f"Gaming PC {spelling} Ryzen 7 9800X3D 32GB DDR5 2TB SSD", {}, "new")
    assert build["core"]["gpu"] == "5070 Ti" and not build["issues"]


@pytest.mark.parametrize("text", ["RTX 5070", "RTX 5070 Ti Laptop", "RTX 5070 Ti Super",
    "RTX 5070 Ti/5080", "RTX 5070 Ti or RTX 5090", "RTX 5070 Ti RTX 5070",
    "up to RTX 5070 Ti", "RTX 5080 Ti", "RTX 5090 D"])
def test_wrong_gpu_or_ambiguous_title_never_becomes_supported_prebuilt(text):
    assert gpu_model(text) is None


@pytest.mark.parametrize("price,priority", [(1000,3), (950,4), (900,5), (1000.01,None)])
def test_new_card_prices_send_without_claiming_sold_reference_or_vram_upgrade(tmp_path, price, priority):
    sent, result = execute(tmp_path, card(price))
    if priority is None:
        assert not sent
    else:
        assert sent[0].buys[0].priority == priority
        assert "PRICE WATCH" in sent[0].buys[0].badge
        assert not result.assessments[0].detail.reference_trusted
        assert "sold-price" in sent[0].buys[0].reason


@pytest.mark.parametrize("changes", [
    {"condition_hint":"used"}, {"condition_hint":"open_box"}, {"condition_hint":"refurbished"},
    {"seller_risk":"high"}, {"seller_risk":"moderate"}, {"loggable":False}, {"multi_variant":True}, {"sold":True},
    {"title":"RTX 5070 Ti Laptop 12GB"}, {"title":"RTX 5070 Ti water block"},
    {"title":"RTX 5070 Ti for parts not working"}, {"title":"2x RTX 5070 Ti 16GB graphics cards"},
    {"title":"Gaming PC RTX 5070 Ti 16GB RAM 1TB SSD"},
])
def test_card_notice_does_not_bypass_existing_risk_and_identity_vetoes(tmp_path, changes):
    assert not execute(tmp_path, card(**changes))[0]


def test_suspiciously_cheap_card_does_not_alert(tmp_path):
    assert not execute(tmp_path, card(100))[0]


def test_card_receipts_dedupe_and_allow_material_drop(tmp_path):
    assert execute(tmp_path, card(1000))[0]
    assert not execute(tmp_path, card(1000))[0]
    assert execute(tmp_path, card(900))[0]


@pytest.mark.parametrize("capacity,price,priority", [
    (32,2200,3), (32,2100,4), (32,2000,5), (32,2200.01,None),
    (64,2400,3), (64,2300,4), (64,2200,5), (64,2400.01,None),
])
def test_prebuilt_uses_separate_whole_pc_ram_price_bands(tmp_path, capacity, price, priority):
    sent, result = execute(tmp_path, pc(price, capacity))
    if priority is None:
        assert not sent
    else:
        assert sent[0].buys[0].priority == priority
        assert sent[0].buys[0].title == "RTX 5070 Ti prebuilt"
        assert "POSSIBLE REUSE" in sent[0].buys[0].badge
        assert result.assessments[0].detail.target_price == (2200 if capacity == 32 else 2400)


@pytest.mark.parametrize("changes", [{"stock":"out_of_stock"}, {"shipping":None}, {"shipping":101},
    {"confirmed":False}, {"specs":{"RAM":"16GB DDR5"}}, {"specs":{"RAM":"96GB DDR5"}},
    {"specs":{"RAM":"32GB DDR5", "Memory Slots":"2"}}])
def test_prebuilt_cannot_alert_without_price_stock_or_ram_eligibility(tmp_path, changes):
    assert not execute(tmp_path, pc(**changes))[0]


def test_unknown_ram_remains_normal_priority_review(tmp_path):
    sent, _ = execute(tmp_path, pc(2399, specs={}))
    assert sent[0].buys[0].priority == 3 and "NEEDS SPECS" in sent[0].buys[0].badge


def test_newegg_selected_ti_variant_supported_and_conflicts_rejected():
    data = json.loads((ROOT / "tests/fixtures/newegg_selected_5090.json").read_text().replace("5090", "5070 Ti"))
    data["ItemDetail"]["ItemManufactory"]["Manufactory"] = "Yeyian"
    url = data["provenance"]["url"]
    body = lambda: '<script>window.__initialState__ = ' + json.dumps(data) + ';</script>'
    offer = parse_newegg(body(), url, NOW)
    assert offer.gpu == "5070 Ti" and offer.confirmed
    data["PropertyCollection"]["PropertyGroups"][1]["SelectedProperty"]["Description"] = "5070"
    with pytest.raises(Deferred, match="Selected GPU"):
        parse_newegg(body(), url, NOW)


def test_discovery_includes_ti_only_and_retains_existing_gpus():
    products = [{"ItemCell":{"Description":{"Title":f"Yeyian Gaming PC RTX {gpu}"},
                              "ItemManufactory":{"Manufactory":"Yeyian"}, "Item":str(i)}}
                for i,gpu in enumerate(("5070", "5070 Ti", "5080", "5090", "5070 Ti Laptop"))]
    assert discover_newegg('<script>window.__initialState__ = ' + json.dumps({"Products":products}) + ';</script>') == [
        f"https://www.newegg.com/p/{i}?Item={i}" for i in (1,2,3)]
    urls = [f"https://skytechgaming.com/prebuilt-gaming-pc/st-test-{i}/gaming-pc-rtx-{gpu}-16gb/test"
            for i,gpu in enumerate(("5070", "5070-ti", "5080", "5090"))]
    body = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(
        f'<url><loc>{url}</loc></url>' for url in urls) + '</urlset>'
    assert discover_skytech(body) == urls[1:]
