"""Completed desktop topology and additional-card/desktop-memory notifications."""
from dataclasses import replace
from datetime import timedelta
from unittest.mock import Mock

import pytest

from alerters.hardware.native import rig
from alerters.hardware.native.catalog import BY_KEY
from alerters.hardware.native.config import Config, _query_for
from alerters.hardware.native.match import match
from alerters.hardware.native.sources.ebay import EbaySource
from alerters.hardware.memory import configuration
from alerters.techscout.facets import attributes
from tests.test_5070_ti_watch import NOW, ROOT, card, execute
from tests.test_ebay_stock import detail
from dealcore.types import Listing


def test_docked_gpu_is_not_assumed_to_pool_memory_or_main_psu_draw():
    assert sum(n.vram_gb for n in rig.NODES if n.host == "desktop") == 48
    assert rig.host_vram_gb() == 32
    assert rig.host_draw_w() == 575
    assert rig.host_draw_w("dock") == 300
    assert rig.host_vram_gb("missing") == 0
    fit = rig.check_fit(BY_KEY["rtx_5090"])
    assert fit.ok and "~875W total" in fit.summary and "1300W" in fit.summary
    assert "750W" in fit.summary


def test_replacement_does_not_claim_more_context_for_smaller_or_identical_cards():
    for key in ("rtx_5070_ti", "rtx_5090", "rtx_3090"):
        before, after, sentence = rig.capability_gain(BY_KEY[key])
        assert before == 32 and after <= before
        assert "No single-device capacity upgrade" in sentence
    assert rig.capability_gain(BY_KEY["rtx_a6000"])[1] > 32


@pytest.mark.parametrize("gpu,price,priority", [("5070 Ti",1000,3), ("5080",1500,3),
    ("5080",1400,4), ("5080",1300,5), ("5090",5000,5), ("5090",4500,5)])
def test_additional_cards_can_push_without_growing_single_device_vram(tmp_path, gpu, price, priority):
    row = card(price, title=f"NVIDIA GeForce RTX {gpu} graphics card")
    sent, result = execute(tmp_path, row)
    assert len(sent) == 1 and sent[0].buys[0].priority == priority
    assert "CARD PRICE WATCH" in sent[0].buys[0].badge
    assert result.assessments[0].detail.vram_before == 32


@pytest.mark.parametrize("changes", [{"price":5000.01}, {"condition_hint":"used"},
    {"seller_risk":"high"}, {"loggable":False}, {"sold":True}, {"multi_variant":True},
    {"extra":{"shopping":{"available":False}}}, {"price":1000}])
def test_5090_watch_preserves_price_condition_source_and_risk_vetoes(tmp_path, changes):
    row = card(5000, title="NVIDIA GeForce RTX 5090 32GB graphics card")
    assert not execute(tmp_path, replace(row, **changes))[0]


@pytest.mark.parametrize("title,key,limit", [
    ("Crucial 64GB DDR5-5600 UDIMM Desktop Memory", "ddr5_udimm_64", 937.49),
    ("Corsair Vengeance DDR5 96GB (2x48GB) 288-Pin Desktop Memory Intel XMP", "ddr5_udimm_96_kit", 1109.99),
    ("Kingston FURY Beast 64GB 288-Pin PC RAM DDR5 5600 (PC5 44800) Memory (Desktop Memory) Model KF556C36BBEA-64", "ddr5_udimm_64", 937.49),
    ("G.SKILL Ripjaws M5 RGB Series 96GB (2 x 48GB) 288-Pin PC RAM DDR5 5600 (PC5 44800) Desktop Memory Model F5-5600J4040D48GX2-RM5RW", "ddr5_udimm_96_kit", 1109.99)])
def test_desktop_memory_is_whole_purchase_and_separate_from_sodimms(tmp_path, title, key, limit):
    parsed = match(title, price=limit)
    assert parsed.part.key == key and parsed.quantity == 1 and parsed.unit_price == limit
    row = card(limit, title=title, condition_hint="new", extra={"shopping":{"available":True}})
    sent, _ = execute(tmp_path, row)
    assert len(sent) == 1 and sent[0].buys[0].badge == "DESKTOP RAM PRICE WATCH"
    assert "ThinkPad" not in " ".join(sent[0].buys[0].warnings)
    facets = attributes({"title":title})
    assert facets["kind"] == "Memory" and "UDIMM" in facets["memory_layout"]
    assert not execute(tmp_path / "over", replace(row, price=limit+.01))[0]
    assert not execute(tmp_path / "stock", replace(row, extra={"shopping":{"available":False}}))[0]


@pytest.mark.parametrize("title", ["DDR5 UDIMM 64GB (2x32GB)", "DDR5 UDIMM 96GB",
    "DDR5 SO-DIMM 64GB", "DDR5 RDIMM 64GB", "DDR5 ECC UDIMM 64GB",
    "DDR5 UDIMM 64GB kit", "DDR5 UDIMM 2x48GB 128GB", "DDR5 UDIMM 64GB/96GB choose size",
    "Gaming PC RTX 5090 96GB DDR5 2x48GB Desktop Memory", "DDR5 UDIMM 2x48GB $300 each"])
def test_wrong_desktop_layouts_do_not_match(title):
    assert configuration(title) is None


def test_new_searches_fit_within_existing_query_cap():
    cfg = Config.load(ROOT / "config/hardware.toml", ROOT / "config/watchlist.toml")
    for key in ("rtx_5080", "ddr5_udimm_64", "ddr5_udimm_96_kit"):
        assert _query_for(BY_KEY[key]) in cfg.search_queries


def checked_card(title="NVIDIA RTX 5090 32GB graphics card", price=5000):
    row = card(price, source="ebay", listing_id="v1|123|0", title=title, condition_hint="new", loggable=False)
    feed = EbaySource((), client_id="fixture", client_secret="fixture", card_limits={"rtx_5090":5000})
    feed._headers = Mock(return_value={})
    feed.session.get = Mock(return_value=Mock(status_code=200, json=lambda:detail(
        itemId=row.listing_id, title=title, price={"value":str(price),"currency":"USD"})))
    return feed, row


def test_ebay_price_notice_needs_exact_stock_and_never_enters_market_history(tmp_path):
    feed, row = checked_card()
    try:
        assert not execute(tmp_path / "search", row)[0]
        verified = feed._verify_memory_stock([row])[0]
        # The delivery helper uses a fixed run clock; align its API receipt.
        shopping = dict(verified.extra["shopping"], availability_checked_at=NOW.isoformat())
        verified = replace(verified, extra={**verified.extra, "shopping":shopping})
        sent, result = execute(tmp_path / "verified", verified)
        assert len(sent) == 1 and sent[0].buys[0].priority == 5
        assert not result.assessments[0].loggable
        shopping = dict(verified.extra["shopping"], availability_checked_at=(NOW-timedelta(hours=1)).isoformat())
        assert not execute(tmp_path / "stale", replace(verified, extra={"shopping":shopping}))[0]
    finally:
        feed.session.close()


@pytest.mark.parametrize("changes", [{"title":"NVIDIA RTX 5080 graphics card"},
    {"estimatedAvailabilities":[]}, {"shippingOptions":[]}, {"buyingOptions":["AUCTION"]},
    {"condition":"Used"}, {"seller":{"feedbackScore":1,"feedbackPercentage":"80"}},
    {"price":{"value":"1000","currency":"USD"}}])
def test_ebay_card_detail_failures_or_bait_cannot_alert(tmp_path, changes):
    feed, row = checked_card()
    item = detail(itemId=row.listing_id, title=row.title, price={"value":"5000","currency":"USD"}) | changes
    feed.session.get.return_value.json = lambda:item
    try:
        assert not execute(tmp_path, feed._verify_memory_stock([row])[0])[0]
    finally:
        feed.session.close()
