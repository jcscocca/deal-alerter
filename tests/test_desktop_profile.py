from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from alerters.hardware.desktop_profile import DesktopProfile, DEFAULT_PROFILE
from alerters.hardware.prebuilt import Offer, exact_desktop
from alerters.hardware.prebuilt_plugin import MonitorHardwarePlugin, community_offer, offer_listing
from alerters.hardware.retailers import parse_newegg, parse_hp, discover_newegg
from alerters.hardware.retail_http import Deferred
from dealcore.notify import Channel
from dealcore.run import run
from dealcore.state import AlertState
from dealcore.types import FetchResult, Listing

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 6, 17, tzinfo=timezone.utc)


def pc(**changes):
    row = Offer("newegg", "TEST5080", "Gaming desktop RTX 5080 16GB GDDR7", "https://example.invalid/pc",
                "Newegg", "new", {"RAM": "64GB DDR5 (2 x 32GB)", "Memory Slots (Total)": "4",
                "Maximum Memory Supported": "128GB"}, 2499, 0, "in_stock", True, NOW.isoformat())
    return replace(row, **changes)


def assess(offer):
    return DesktopProfile(DEFAULT_PROFILE).assess_memory(offer)


@pytest.mark.parametrize("capacity,total", [(32,96), (64,128)])
def test_reuse_is_potential_never_validated(capacity, total):
    fit = assess(pc(specs={"RAM": f"{capacity}GB DDR5 (2 x {capacity//2}GB)",
                          "Memory Slots": "4", "Maximum Memory": "128GB"}))
    assert fit.status == "POSSIBLE REUSE" and fit.eligible
    assert fit.potential_gb == total and "unverified" in fit.summary


@pytest.mark.parametrize("specs", [{}, {"Maximum Memory": "128GB"}, {"Memory": "Up to 128GB"}])
def test_gpu_vram_and_capacity_limits_are_not_installed_ram(specs):
    fit = assess(pc(title="Gaming desktop RTX 5090 32GB GDDR7", specs=specs))
    assert fit.status == "NEEDS SPECS" and fit.potential_gb is None


@pytest.mark.parametrize("title", ["RTX 5080 laptop", "Gaming PC up to RTX 5080", "Gaming PC RTX 5080/5090", "Gaming PC RTX 5080 or 5090"])
def test_variant_and_laptop_titles_do_not_establish_desktop_gpu(title):
    assert not exact_desktop(title)


@pytest.mark.parametrize("specs", [
    {"RAM": "64GB DDR4 (2 x 32GB)", "Memory Slots": "4"},
    {"RAM": "64GB DDR5 (2 x 32GB)", "Memory Slots": "2"},
    {"RAM": "64GB DDR5 (4 x 16GB)", "Memory Slots": "4"},
    {"RAM": "64GB DDR5 (2 x 32GB)", "Maximum Memory": "64GB"},
])
def test_explicit_layout_without_requested_reuse_path_is_excluded(specs):
    assert not assess(pc(specs=specs)).eligible


def test_unknown_layout_does_not_discard_promising_deal():
    fit = assess(pc(specs={"RAM": "32GB DDR5"}))
    assert fit.eligible and fit.status == "NEEDS SPECS" and fit.potential_gb == 96


def test_exact_sku_review_fills_gaps_but_conflicts_remain_unknown():
    base = pc(retailer="hp", sku="C33HVAA#ABA", specs={})
    fit = assess(base)
    assert fit.status == "POSSIBLE REUSE" and fit.potential_gb == 96
    assert "hp.com" in fit.evidence[0]
    assert assess(replace(base, sku="different")).status == "NEEDS SPECS"
    assert assess(replace(base, specs={"RAM": "64GB DDR5"})).status == "NEEDS SPECS"


def execute(tmp_path, offer, profile=None):
    plugin = MonitorHardwarePlugin(ROOT / "config/hardware.toml", tmp_path, now=NOW, desktop_profile=profile)
    plugin.sources = (SimpleNamespace(name="fixture", fetch=lambda: FetchResult([offer_listing(offer)])),)
    sent = []
    result = run(plugin, AlertState(plugin.state_dir / "alerts.json", plugin.normalise_key),
                 replace(plugin.options, quiet_when_empty=True, preview=tmp_path / "preview.html"),
                 (Channel("fixture", "push", sent.append),), now=NOW)
    assert not result.problems
    return sent


@pytest.mark.parametrize("capacity,price,level", [
    (32,2500,5), (32,2800,4), (32,3000,3), (32,3000.01,None),
    (64,3300,5), (64,3600,4), (64,4000,3), (64,4000.01,None),
])
def test_5080_thresholds_use_installed_ram_tier_and_pc_total(tmp_path, capacity, price, level):
    offer = pc(base_price=price)
    offer.specs["RAM"] = f"{capacity}GB DDR5 (2 x {capacity//2}GB)"
    sent = execute(tmp_path, offer)
    if level is None:
        assert not sent
    else:
        card = sent[0].buys[0]
        assert card.priority == level and card.title == "RTX 5080 prebuilt"
        assert "POSSIBLE REUSE" in card.badge
        assert any("not a guaranteed" in w for w in card.warnings)


@pytest.mark.parametrize("changes", [{"stock":"out_of_stock"}, {"confirmed":False}, {"shipping":None},
                                    {"shipping":1600}, {"specs":{"Memory Slots":"2"}}])
def test_5080_bad_offer_or_ineligible_layout_cannot_push(tmp_path, changes):
    assert not execute(tmp_path, pc(**changes))


def test_5080_dedup_and_price_drop(tmp_path):
    assert execute(tmp_path, pc(base_price=2799))
    assert not execute(tmp_path, pc(base_price=2799))
    assert execute(tmp_path, pc(base_price=2399))


def test_strict_profile_rejects_mixed_kits_and_missing_layout(tmp_path):
    path = tmp_path / "profile.toml"
    path.write_text(DEFAULT_PROFILE.read_text().replace("allow_unverified = true", "allow_unverified = false"))
    assert not execute(tmp_path, pc(), path)
    assert not execute(tmp_path, pc(specs={"RAM":"128GB DDR5"}), path)
    assert not execute(tmp_path, pc(specs={"RAM":"128GB DDR5", "Memory Slots":"4"}), path)


@pytest.mark.parametrize("capacity", [16,48,96,128,192])
def test_only_factory_32gb_and_64gb_belong_in_reuse_watch(tmp_path, capacity):
    offer = pc(specs={"RAM":f"{capacity}GB DDR5 (2 x {capacity//2}GB)", "Memory Slots":"4"})
    assert not assess(offer).eligible
    assert not execute(tmp_path, offer)


def test_unknown_capacity_keeps_wider_watch_limit_but_normal_priority(tmp_path):
    sent = execute(tmp_path, pc(base_price=3799, specs={}))
    assert sent[0].buys[0].priority == 3
    assert "NEEDS SPECS" in sent[0].buys[0].badge


def test_explicit_available_slots_establish_or_veto_reuse():
    specs = {"Total Memory":"64GB", "Memory Speed":"DDR5-6000", "Memory Slots (Total)":"4",
             "Memory Slots (Available)":"2", "Maximum Memory Supported":"256GB"}
    assert assess(pc(specs=specs)).status == "POSSIBLE REUSE"
    assert not assess(pc(specs={**specs, "Memory Slots (Available)":"0"})).eligible


def test_5080_announcement_stays_unverified_and_does_not_invent_ram():
    offer = community_offer(Listing("notice", "slickdeals", "[Prebuilt] RTX 5080 16GB gaming PC $2399", "https://example.invalid/post", NOW))
    assert offer and offer.gpu == "5080" and offer.claimed_price == 2399 and not offer.confirmed
    assert assess(offer).potential_gb is None


def test_selected_5080_is_supported_without_accepting_mismatched_variants():
    data = json.loads((ROOT / "tests/fixtures/newegg_selected_5090.json").read_text().replace("5090", "5080"))
    url = data["provenance"]["url"]
    body = lambda: '<script>window.__initialState__ = ' + json.dumps(data) + ';</script>'
    offer = parse_newegg(body(), url, NOW)
    assert offer.gpu == "5080" and offer.confirmed
    data["PropertyCollection"]["PropertyGroups"][1]["SelectedProperty"]["Description"] = "5090"
    with pytest.raises(Deferred, match="Selected GPU"):
        parse_newegg(body(), url, NOW)


def test_discovery_includes_5080_from_explicit_supported_brand():
    data = {"Products":[{"ItemCell":{"Item":"EXAMPLE", "Description":{"Title":"STORMCRAFT Gaming PC RTX 5080"},
                                      "ItemManufactory":{"Manufactory":"STORMCRAFT"}}}]}
    assert len(discover_newegg('<script>window.__initialState__ = ' + json.dumps(data) + ';</script>')) == 1


def test_hp_gpu_can_come_from_primary_fixed_product_description():
    product = {"@type":"Product", "name":"OMEN 35L Gaming Desktop", "sku":"C33HVAA#ABA",
               "description":"Ryzen 7 9800X3D, RTX 5080 16GB, 32GB DDR5", "offers":{"@type":"Offer",
               "price":2799.99, "priceCurrency":"USD", "availability":"https://schema.org/InStock"}}
    body = '<h1>OMEN 35L Gaming Desktop</h1>FREE Storewide Shipping<script type="application/ld+json">' + json.dumps(product) + '</script>'
    offer = parse_hp(body, "https://www.hp.com/us-en/shop/pdp/omen-example", NOW)
    assert offer.gpu == "5080" and offer.confirmed and assess(offer).potential_gb == 96
