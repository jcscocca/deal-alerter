"""A later target or prebuilt comparison cannot undo a native price/trust veto."""
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from alerters.hardware.native import match, rig, verdict
from alerters.hardware.native.catalog import BY_KEY
from alerters.hardware.native.config import Thresholds
from alerters.hardware.native.history import PriceStats
from alerters.hardware.plugin import Candidate, HardwarePlugin
from dealcore.types import Listing
from dealcore.verdict import qualifies

Bands = verdict.Verdict


def plugin():
    result = HardwarePlugin.__new__(HardwarePlugin)
    result.verdict, result.bands, result.rig = verdict, Bands, rig
    result.cfg = NS(thresholds=Thresholds(), psu_headroom_w=150, prebuilt_push_margin_pct=5)
    result.log = Mock()
    result.log.total_observations.return_value = 0
    result.matched = result.seen = 1
    return result


def candidate(part, price, **listing_fields):
    is_system = listing_fields.pop("is_system", False)
    is_bundle = listing_fields.pop("is_bundle", False)
    mining_risk = listing_fields.pop("mining_risk", "low")
    listing_id = listing_fields.pop("listing_id", "fixture")
    listing = Listing(listing_id, "ebay", part.name, "https://example.invalid/fixture",
                      datetime.now(timezone.utc), price=price, **listing_fields)
    match = NS(part=part, unit_price=price, quantity=1, mining_risk=mining_risk,
               is_system=is_system, is_bundle=is_bundle)
    return Candidate(listing, match, NS(target=price + 20, name="explicit target"), "used")


def empty_stats(part):
    return PriceStats(part.key, "used", 0)


def expensive_history(part, price):
    # A reconstructed pool: the incident supplied the price/reference ratio,
    # not the historical distribution. This makes the price rank in the top 10%.
    return PriceStats(part.key, "used", 50, low=price, p10=price * 1.02,
                      p25=price * 1.05, median=price * 1.10, span_days=60)


@pytest.mark.parametrize("part_key, price, listing_id, expected", [
    ("rtx_3090", 1199.99, "bridge960010926668", Bands.FAIR),
    ("rtx_5090", BY_KEY["rtx_5090"].reference_price * 1.36, "oct3-1.36x", Bands.PASS),
    ("rtx_5090", BY_KEY["rtx_5090"].reference_price * 1.57, "oct3-1.57x", Bands.PASS),
])
def test_history_price_veto_survives_target_in_badge_report_and_delivery(
    part_key, price, listing_id, expected,
):
    store = plugin()
    part = BY_KEY[part_key]
    row = candidate(part, price, listing_id=listing_id)
    item = store.judge(row, expensive_history(part, price))
    assert item.detail.target_hit
    assert item.verdict == item.detail.verdict == expected
    assert "Held back anyway" in item.detail.reason
    assert not item.target_override
    assert not qualifies(item, Bands.STRONG)
    assert not qualifies(item, Bands.EXCEPTIONAL)
    report = store.report([], [item], [])
    assert report.buys == ()
    assert report.others[0].badge.startswith(expected.label)
    assert "STRONG BUY" not in report.others[0].badge
    assert report.subject == "0 new AI hardware recommendations"


@pytest.mark.parametrize("stale", [False, True], ids=["unverified-5200", "stale-sold"])
def test_uncertain_reference_is_watch_only_in_every_channel_even_under_target(stale):
    store = plugin()
    # The September 29 reference was $5,200; the current catalog differs.
    part = replace(BY_KEY["mac_studio_m4_max_128"], reference_price=5200,
                   reference_basis="sold" if stale else "estimate")
    stats = empty_stats(part)
    if stale:
        stats = replace(stats, recent_median=5200, recent_count=5)
    item = store.judge(candidate(part, 4000), stats)
    assert item.verdict == item.detail.promotion_ceiling == Bands.GOOD
    assert not item.detail.reference_trusted
    assert "Watch only" in item.detail.reason
    assert "WATCH / UNVERIFIED" in item.detail.headline
    assert not qualifies(item, Bands.STRONG)
    assert not qualifies(item, Bands.GOOD)  # A configured lower floor cannot undo the veto.
    assert not item.target_override
    assert not qualifies(item, Bands.EXCEPTIONAL)
    report = store.report([], [item], [])
    assert report.buys == ()
    assert report.subject == "0 new AI hardware recommendations"
    assert report.others[0].badge.startswith("WATCH / UNVERIFIED")
    assert "BUY" not in report.others[0].badge
    assert "WATCH / UNVERIFIED" in report.others[0].headline
    assert "provisional" in report.others[0].warnings[0]


def test_trusted_explicit_target_still_reaches_push():
    store = plugin()
    part = BY_KEY["rtx_3090"]
    row = candidate(part, part.reference_price)
    item = store.judge(row, empty_stats(part))
    assert item.verdict == Bands.STRONG
    assert "under your" in item.detail.headline
    assert item.target_override
    assert qualifies(item, Bands.EXCEPTIONAL)


@pytest.mark.parametrize("risk", ["seller", "mining", "reference", "history", "parts"])
def test_prebuilt_comparison_cannot_undo_native_veto(risk):
    store = plugin()
    part = BY_KEY["rtx_5090"]
    price = part.reference_price * 0.9
    if risk == "reference":
        part = replace(part, reference_basis="estimate")
    if risk == "history":
        price = part.reference_price * 1.36
    fields = {"is_system": True}
    if risk == "seller":
        fields["seller_risk"] = "high"
    if risk == "mining":
        fields["mining_risk"] = "high"
    row = candidate(part, price, **fields)
    if risk == "parts":
        row = replace(row, condition="parts")
    stats = expensive_history(part, price) if risk == "history" else empty_stats(part)
    machine = store.judge(row, stats)
    card = store.judge(candidate(part, price / 0.9, listing_id="loose"), empty_stats(part))
    promoted = store.promote([machine, card])[0]
    assert promoted.verdict == machine.verdict
    assert not qualifies(promoted, Bands.EXCEPTIONAL)
    assert not store.signals


def test_real_prebuilt_can_promote_but_never_be_logged():
    store = plugin()
    part = BY_KEY["rtx_5090"]
    row = candidate(part, part.reference_price * 0.9, is_system=True)
    machine = store.judge(row, empty_stats(part))
    card = store.judge(candidate(part, part.reference_price, listing_id="loose"), empty_stats(part))
    promoted = store.promote([machine, card])[0]
    assert promoted.verdict == promoted.detail.verdict == Bands.EXCEPTIONAL
    assert qualifies(promoted, Bands.EXCEPTIONAL)
    assert not promoted.loggable
    store.append([(row, promoted)])
    store.log.record.assert_not_called()


def test_source_veto_cannot_supply_a_prebuilt_benchmark():
    store = plugin()
    part = BY_KEY["rtx_5090"]
    machine = store.judge(candidate(part, part.reference_price * 0.9, is_system=True), empty_stats(part))
    card = store.judge(candidate(part, part.reference_price, listing_id="loose", loggable=False), empty_stats(part))
    assert not store.arbitrage([machine, card])
    assert store.promote([machine, card])[0].verdict == machine.verdict
    assert not store.signals


def test_structured_nonworking_hint_cannot_claim_model_capacity():
    store = plugin()
    part = BY_KEY["rtx_3090"]
    store.matcher = match.match
    store.cfg.max_listing_age_hours = 72
    store.watched = {part.key: NS(target=1100, name="RTX 3090")}
    listing = Listing("parts-hint", "ebay", "NVIDIA RTX 3090 24GB Graphics Card",
                      "https://example.invalid/card", datetime.now(timezone.utc),
                      price=1000, condition_hint="parts")
    row = store.prepare(listing)
    assert row.condition == "parts"
    item = store.judge(row, empty_stats(part))
    assert item.verdict == Bands.PASS
    assert item.detail.vram_after == item.detail.vram_before
    assert item.detail.fit is None
    assert "usable capacity is unverified" in item.detail.unlock
    assert not item.alertable and not item.target_override and not item.loggable
    assert not qualifies(item, Bands.PASS)
    card = store.card(item)
    assert card.bar[1][0] == 0
    assert item.detail.unlock in card.facts
    store.append([(row, item)])
    store.log.record.assert_not_called()

    working = store.judge(store.prepare(replace(listing, condition_hint="used")), empty_stats(part))
    assert working.detail.vram_after > working.detail.vram_before
    assert working.detail.fit is not None
    assert "unverified" not in working.detail.unlock
    assert working.alertable


@pytest.mark.parametrize("is_system", [False, True])
def test_ambiguous_bundle_cannot_override_target_or_supply_savings(is_system):
    store = plugin()
    part = BY_KEY["rtx_5090"]
    row = candidate(part, part.reference_price * 0.9, is_system=is_system, is_bundle=True)
    item = store.judge(row, empty_stats(part))
    card = store.judge(candidate(part, part.reference_price, listing_id="loose"), empty_stats(part))
    assert item.verdict <= Bands.GOOD
    assert not item.target_override
    assert not qualifies(item, Bands.STRONG)
    assert not store.arbitrage([item, card])
    assert store.promote([item, card])[0].verdict == item.verdict
