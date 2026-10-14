"""Prebuilt watch ceilings move with the RAM, storage and CPU a listing includes."""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from alerters.hardware.desktop_profile import DEFAULT_PROFILE, DesktopProfile
from alerters.hardware.prebuilt import Offer
from alerters.hardware.prebuilt_plugin import MonitorHardwarePlugin, community_offer, offer_listing
from alerters.hardware.prebuilt_specs import cpu_models, normalized
from dealcore.notify import Channel
from dealcore.run import run
from dealcore.state import AlertState
from dealcore.types import FetchResult, Listing

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 12, 22, 50, tzinfo=timezone.utc)

# The two Slickdeals posts the live monitor saw on 2026-10-12.
TI_POST = ("CyberPowerPC Gamer Supreme Gaming PC, AMD Ryzen 9 9950X, NVIDIA GeForce RTX 5070 Ti 16GB, "
           "64GB DDR5, 4TB SSD, SLCAI8000CPGV2 - $2739.99")
FIVE_080_POST = ("CyberPowerPC Gamer Supreme Gaming Desktop, Intel Core Ultra 9 285, NVIDIA GeForce RTX 5080 16GB, "
                 "32GB DDR5, 2TB SSD, White, SLC8000WSTV2 - $2599 at Walmart")


def post(listing_id, title):
    return Listing(listing_id, "slickdeals", title, f"https://slickdeals.net/f/{listing_id}", NOW)


def execute(tmp_path, listings):
    plugin = MonitorHardwarePlugin(ROOT / "config/hardware.toml", tmp_path, now=NOW)
    try:
        plugin.sources = (SimpleNamespace(name="fixture", fetch=lambda: FetchResult(listings)),)
        sent = []
        result = run(plugin, AlertState(plugin.state_dir / "alerts.json", plugin.normalise_key),
                     replace(plugin.options, quiet_when_empty=True, preview=tmp_path / "preview.html"),
                     (Channel("fixture", "push", sent.append),), now=NOW)
        assert not result.problems
        return sent, result
    finally:
        plugin.close()


def band(title, specs=None):
    profile = DesktopProfile(DEFAULT_PROFILE)
    offer = Offer("newegg", "x", title, "https://example.invalid/pc", "Newegg", "new",
                  specs or {}, 2000, 0, "in_stock", True, NOW.isoformat())
    return profile.price_band(profile.assess_memory(offer), offer.gpu, offer)


def test_both_october_12_posts_alert_on_component_adjusted_ceilings(tmp_path):
    listings = [community_offer(post("20149107", TI_POST)), community_offer(post("20149056", FIVE_080_POST))]
    sent, result = execute(tmp_path, [offer_listing(o) for o in listings])
    ceilings = {a.detail.title: a.detail.target_price for a in result.assessments}
    # 5070 Ti: $2,200 base + 32GB x $15 + 3TB x $135 + (9950X $419 - 9800X3D $375).
    assert ceilings[TI_POST] == pytest.approx(3129)
    # 5080: $3,000 base + 1TB x $135 + (Ultra 9 285 $393 - $375).
    assert ceilings[FIVE_080_POST] == pytest.approx(3153)
    assert {card.title for message in sent for card in message.buys} == {"RTX 5070 Ti prebuilt", "RTX 5080 prebuilt"}


def test_alert_card_explains_the_ceiling(tmp_path):
    sent, _ = execute(tmp_path, [offer_listing(community_offer(post("20149107", TI_POST)))])
    facts = " ".join(sent[0].buys[0].facts)
    assert "base $2,200" in facts and "RAM +$480" in facts and "storage +$405" in facts and "CPU +$44" in facts


def test_missing_cpu_and_storage_earn_no_credit():
    assert band("Gaming desktop RTX 5070 Ti 16GB 32GB DDR5")["ceiling"] == 2200


def test_unrecognised_cpu_earns_no_credit():
    assert band("Gaming desktop RTX 5070 Ti 16GB Ryzen 9 9950X3D2 32GB DDR5")["ceiling"] == 2200


def test_cheaper_cpu_and_smaller_ssd_lower_the_ceiling():
    # 512GB is 0.488TB below the reference; a 14700KF resells for $119 less than a 9800X3D.
    assert band("Gaming desktop RTX 5070 Ti 16GB i7-14700KF 32GB DDR5 512GB SSD")["ceiling"] == pytest.approx(
        2200 - 0.488 * 135 - 119)


def test_unknown_ram_keeps_the_wider_64gb_ceiling():
    assert band("Gaming desktop RTX 5080 16GB")["ceiling"] == 3000 + 32 * 15


def test_every_configured_cpu_is_recognised_by_the_spec_parser():
    profile = DesktopProfile(DEFAULT_PROFILE)
    for name in profile.components["cpu_resale"]:
        assert {normalized(found) for found in cpu_models(f"Gaming PC {name} RTX 5080")} == {normalized(name)}, name
