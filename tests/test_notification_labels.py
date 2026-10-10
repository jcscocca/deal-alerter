"""October 9 digest regressions: PC prices, watch limits and promotion evidence."""
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from alerters.hardware.native.history import PriceStats
from alerters.hardware.native.verdict import Verdict
from alerters.hardware.prebuilt import Coupon, Offer
from alerters.hardware.prebuilt_plugin import MonitorHardwarePlugin, offer_listing
from alerters.hardware.shopping_activity import judgments
from alerters.techscout.monitor_bridge import public_row
from alerters.techscout.prebuilt_value import current, peer_view
from dealcore.report import render_html, render_text
from dealcore.state import AlertState
from dealcore.types import Listing
from dealcore.verdict import qualifies

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 10, 2, 52, tzinfo=timezone.utc)


@pytest.fixture
def plugin(tmp_path):
    adapter = MonitorHardwarePlugin(ROOT / "config/hardware.toml", tmp_path, now=NOW)
    try:
        yield adapter
    finally:
        adapter.close()


def pc(price=3800, ram=64, **changes):
    return replace(Offer("newegg", "TEST5080", f"Gaming Desktop PC RTX 5080 {ram}GB DDR5",
                         "https://www.newegg.com/p/83-151-596?Item=83-151-596", "Newegg", "new",
                         {"Memory Capacity": f"{ram}GB DDR5"}, price, 0, "in_stock", True,
                         NOW.isoformat()), **changes)


def judge_offer(plugin, offer):
    candidate = plugin.prepare(offer_listing(offer))
    return plugin.judge(candidate, plugin.read_history(candidate))


@pytest.mark.parametrize("offer", [
    pc(4272.99, sku="C9NVV-1277US", title="MSI Aegis ZS2 C9NVV-1277US Gaming Desktop RTX 5080 64GB DDR5"),
    pc(4829.99, sku="GML70943", stock="out_of_stock",
       title="CyberpowerPC Gaming Desktop PC Gamer Supreme GML70943 AMD Ryzen 9 9950X3D2 64GB DDR5 4TB NVMe SSD GeForce RTX 5080 Windows 11 Home"),
])
def test_production_5080_examples_explain_the_actual_ceiling(plugin, offer):
    item = judge_offer(plugin, offer)
    assert item.detail.target_price == 4000 and not item.detail.target_hit
    assert not qualifies(item, plugin.options.push_floor)
    report = plugin.report([], [item], [])
    for body in (render_text(report), render_html(report)):
        assert "Factory 64GB: watch through $4,000" in body
        assert "outside the watch range" in body
        assert "Within the watch range" not in body
    card = report.others[0]
    if offer.stock == "out_of_stock":
        assert "OUT OF STOCK" in card.badge and "CONFIRMED OFFER" not in card.badge
        assert not item.alertable


@pytest.mark.parametrize("ram,target,ceiling", [(32, 2800, 3000), (64, 3600, 4000)])
@pytest.mark.parametrize("boundary,offset", [("target", -.01), ("target", 0), ("target", .01),
                                             ("ceiling", -.01), ("ceiling", 0), ("ceiling", .01)])
def test_watch_labels_and_qualification_share_inclusive_boundaries(plugin, ram, target, ceiling, boundary, offset):
    total = (target if boundary == "target" else ceiling) + offset
    item = judge_offer(plugin, pc(total, ram))
    facts = " ".join(plugin.card(item).facts)
    assert item.detail.target_hit == (total <= ceiling)
    assert qualifies(item, plugin.options.push_floor) == (total <= ceiling)
    if total > ceiling:
        assert "outside the watch range" in facts and "Within the watch range" not in facts
    elif total > target:
        assert "Within the watch range; above" in facts
    else:
        assert "Within the watch range; at or below" in facts


@pytest.mark.parametrize("changes", [
    {"stock": "out_of_stock"}, {"stock": "preorder"}, {"confirmed": False}, {"condition": "unknown"},
    {"announcement": True, "confirmed": False}, {"starts_at": (NOW + timedelta(hours=1)).isoformat()},
    {"ends_at": (NOW - timedelta(hours=1)).isoformat()}, {"specs": {"Memory Slots": "2"}},
])
def test_unavailable_or_ineligible_pc_never_claims_confirmed_watch_qualification(plugin, changes):
    item = judge_offer(plugin, pc(**changes))
    facts = " ".join(plugin.card(item).facts)
    assert "Within the watch range" not in facts
    assert "prevents a confirmed watch-range qualification" in facts
    if not changes.get("announcement") and "starts_at" not in changes:
        assert not qualifies(item, plugin.options.push_floor)


@pytest.mark.parametrize("changes", [{"shipping": None}, {"required_accessories": None}, {"base_price": None}])
def test_unknown_complete_total_cannot_claim_watch_membership(plugin, changes):
    item = judge_offer(plugin, pc(**changes))
    facts = " ".join(plugin.card(item).facts)
    assert "complete PC total unknown" in facts and "Within the watch range" not in facts
    assert not qualifies(item, plugin.options.push_floor)


@pytest.mark.parametrize("coupon,expected", [(None, False), (Coupon("SAVE", "Enter SAVE", 300, True), True),
                                           (Coupon("SAVE", "Membership required", 300, False), False)])
def test_label_uses_delivered_total_and_confirmed_coupon_eligibility(plugin, coupon, expected):
    item = judge_offer(plugin, pc(3990, shipping=30, required_accessories=10, coupon=coupon))
    assert qualifies(item, plugin.options.push_floor) is expected
    assert ("Within the watch range" in " ".join(plugin.card(item).facts)) is expected


def gpu_listing(plugin, price=4000, *, system=True, condition="open_box", **changes):
    title = ("Ryzen 58003XD PC NVIDIA RTX 4090 - 64GB DDR4 RGB! 3600Mhz RAM+2TB SSD+WiFi 6" if system
             else "NVIDIA GeForce RTX 4090 24GB graphics card")
    row = replace(Listing("404932819870" if system else "loose", "ebay", title,
                          "https://www.ebay.com/itm/404932819870" if system else "https://www.ebay.com/itm/loose",
                          datetime.now(timezone.utc), price=price, condition_hint=condition), **changes)
    candidate = plugin.prepare(row)
    assert candidate is not None and candidate.match.is_system is system
    history = PriceStats("rtx_4090", "new", 37, low=2073, p10=2500, p25=2700, median=2928,
                         recent_median=3180, recent_count=37, span_days=60)
    item = plugin.judge(candidate, history)
    assert item is not None
    return item


def test_production_4090_system_promotion_subject_body_and_dashboard_agree(plugin, tmp_path):
    system, loose = gpu_listing(plugin), gpu_listing(plugin, 4500, system=False)
    promoted = plugin.promote([system, loose])[0]
    assert promoted.verdict == Verdict.EXCEPTIONAL and not promoted.loggable
    assert promoted.detail.percentile is None
    report = plugin.report([promoted], [], [])  # benchmark absent from this delivery
    assert report.subject == "EXCEPTIONAL · WHOLE-PC PRICE GAP: Whole PC with RTX 4090 24GB at $4,000"
    assert report.buys[0] == plugin.card(promoted)  # dashboard's independent card call
    assert not report.buys[0].bar
    for body in (render_text(report), render_html(report)):
        assert "Whole PC with RTX 4090 24GB" in body and "404932819870" in body
        assert "this run at $4,500" in body and "$500 lower asking price" in body
        assert "neither market value nor resale profit" in body
        for misleading in ("/GB", "History says wait", "Against 37 recorded", "usual $2,928", "Takes the desktop from"):
            assert misleading not in body
    result = SimpleNamespace(assessments=[promoted], decisions=[])
    exported = judgments(plugin, result, plugin.options, AlertState(tmp_path / "receipts.json", plugin.normalise_key), NOW)[promoted.key]
    assert exported["badge"] == report.buys[0].badge
    assert exported["headline"] == report.buys[0].headline
    assert exported["eligible"] and "$4,500" in exported["headline"]


@pytest.mark.parametrize("changes", [{"stock": "out_of_stock"}, {"confirmed": False},
                                     {"shipping": None}, {"specs": {"Memory Slots": "2"}}])
def test_loose_card_comparison_cannot_promote_unavailable_or_ineligible_offer(plugin, changes):
    # A high loose-card ask cannot rescue missing stock, cost or RAM eligibility.
    item = judge_offer(plugin, pc(3800, **changes))
    loose = gpu_listing(plugin, 4500, system=False)
    loose = replace(loose, detail=replace(loose.detail, part=next(p for p in plugin.catalog.PARTS if p.key == "rtx_5080")))
    assert plugin.promote([item, loose])[0].verdict < Verdict.EXCEPTIONAL


@pytest.mark.parametrize("condition,price", [("used", 4500), ("unknown", 4500), ("open_box", 4000), ("open_box", 4100)])
def test_system_comparison_that_cannot_promote_has_no_exceptional_claim(plugin, condition, price):
    system = gpu_listing(plugin)
    loose = gpu_listing(plugin, price, system=False, condition=condition)
    item = plugin.promote([system, loose])[0]
    assert item.verdict < Verdict.EXCEPTIONAL
    assert "EXCEPTIONAL" not in plugin.report([], [item], []).others[0].badge


@pytest.mark.parametrize("price,exceptional", [(3149.99, False), (3150, True), (4275, True), (4275.01, False)])
def test_system_price_gap_keeps_existing_floor_and_margin_boundaries(plugin, price, exceptional):
    system, loose = gpu_listing(plugin, price), gpu_listing(plugin, 4500, system=False)
    promoted = plugin.promote([system, loose])[0]
    assert (promoted.verdict == Verdict.EXCEPTIONAL) is exceptional


def test_loose_card_still_shows_its_own_history_and_efficiency(plugin):
    loose = gpu_listing(plugin, 4500, system=False)
    card = plugin.card(loose)
    assert card.title == "RTX 4090 24GB" and card.bar
    assert "/GB" in " ".join(card.facts) and "recorded" in card.reason


def test_separate_price_gap_promotion_never_relabels_over_ceiling_price(plugin):
    item = judge_offer(plugin, pc(4272.99))
    loose = gpu_listing(plugin, 4500, system=False, condition="new")
    loose = replace(loose, detail=replace(loose.detail, part=next(p for p in plugin.catalog.PARTS if p.key == "rtx_5080")))
    item = plugin.promote([item, loose])[0]
    assert item.verdict == Verdict.EXCEPTIONAL and not item.detail.target_hit
    card = plugin.card(item)
    assert "WHOLE-PC PRICE GAP" in card.badge
    assert "outside the watch range" in " ".join(card.facts)
    assert "this run at $4,500" in " ".join(card.warnings)
    assert "Within the watch range" not in " ".join(card.facts)


def test_out_of_stock_email_and_dashboard_remain_saved_price_evidence(plugin):
    offer = pc(4829.99, stock="out_of_stock", sku="GML70943")
    item = judge_offer(plugin, offer)
    row = public_row({"type": "offer", "offer": asdict(offer)}, "newegg", NOW.isoformat(),
                     NOW.timestamp()+120, [], NOW.timestamp(), plugin.desktop_profile)
    assert not row["available"] and row["stock"] == "out_of_stock"
    assert not current(row, NOW.timestamp())
    assert "OUT OF STOCK" in plugin.card(item).badge and not item.alertable
    assert peer_view(row, {"issues": [], "core": {"gpu": "5080", "cpu": "test", "ram_gb": 64,
                     "ram_type": "DDR5", "ssd_gb": 4000, "condition": "new"}}, [], NOW.timestamp())["label"] == "Peer rating needs a current offer"
