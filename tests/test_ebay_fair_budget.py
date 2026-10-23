"""Real stock-check planning shares its cap and rotates every stable candidate."""
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from itertools import count
from types import SimpleNamespace
from urllib.parse import unquote
from unittest.mock import Mock

import pytest

from alerters.hardware.displays import LIMITS
from alerters.hardware.native.sources import ebay
from dealcore.types import Listing
from tests.test_ebay_stock import detail

NOW = datetime.now(timezone.utc)
PRODUCTS = {
    "gpu": ("NVIDIA RTX 3090 24GB graphics card", 850, "used"),
    "memory": ("Corsair DDR5 UDIMM 96GB (2x48GB) Desktop Memory", 1000, "new"),
    "monitors": ('Alienware AW2725QF 27-inch 4K 180Hz monitor DisplayPort', 299.99, "new"),
}


def rows_for(category, count):
    title, price, condition = PRODUCTS[category]
    return [Listing(f"v1|{category}-{index:03}|0", "ebay", title,
                    f"https://www.ebay.com/itm/{category}-{index}", NOW,
                    price=price, condition_hint=condition) for index in range(count)]


def fixture_source(rows):
    items = {row.listing_id: detail(itemId=row.listing_id, title=row.title,
                                   price={"value":str(row.price), "currency":"USD"},
                                   condition="Used" if row.condition_hint == "used" else "New")
             for row in rows}
    source = ebay.EbaySource((), client_id="fixture", client_secret="fixture",
                             gpu_limits={"rtx_3090":1250, "rtx_4090":2600},
                             memory_limits={"ddr5_udimm_96_kit":1109.99}, display_limits=LIMITS)
    source._headers = Mock(return_value={})
    source.session.get = Mock(side_effect=lambda url, **_: SimpleNamespace(
        status_code=200, json=lambda:items[unquote(url[len(ebay.ITEM_URL):])]))
    return source


def checked_ids(rows):
    return {row.listing_id for row in rows if row.extra.get("shopping", {}).get("available") is True}


def test_twenty_gpu_hits_cannot_crowd_out_monitor_and_memory(monkeypatch):
    monkeypatch.setattr(ebay, "_stock_rotation_slot", lambda:0)
    rows = rows_for("gpu", 20) + rows_for("monitors", 1) + rows_for("memory", 1)
    source = fixture_source(rows)
    try:
        result = source._verify_memory_stock(rows)
        assert source.session.get.call_count == ebay.MAX_STOCK_CHECKS == 20
        assert len(checked_ids(result)) == 20
        assert rows[-1].listing_id in checked_ids(result) and rows[-2].listing_id in checked_ids(result)
        assert sum(row.listing_id in checked_ids(result) for row in rows[:20]) == 18
        assert [row.listing_id for row in result] == [row.listing_id for row in rows]
        for row in result:
            if row.listing_id not in checked_ids(result):
                assert "request limit" in row.extra["shopping"]["availability_note"]
        # Actual requests interleave the categories, not only their accounting.
        first = [unquote(call.args[0][len(ebay.ITEM_URL):]) for call in source.session.get.call_args_list[:3]]
        assert {item.split("|")[1].split("-")[0] for item in first} == set(PRODUCTS)
    finally:
        source.session.close()


@pytest.mark.parametrize("category", list(PRODUCTS))
def test_absent_categories_return_unused_budget(category, monkeypatch):
    monkeypatch.setattr(ebay, "_stock_rotation_slot", lambda:0)
    rows = rows_for(category, 25)
    source = fixture_source(rows)
    try:
        result = source._verify_memory_stock(rows)
        assert source.session.get.call_count == 20 and len(checked_ids(result)) == 20
    finally:
        source.session.close()


def test_every_stable_candidate_rotates_into_a_check_and_query_order_does_not_matter(monkeypatch):
    slot = [100]
    monkeypatch.setattr(ebay, "_stock_rotation_slot", lambda:slot[0])
    rows = sum((rows_for(category, 30) for category in PRODUCTS), [])
    source = fixture_source(rows)
    try:
        seen = set()
        for current in range(100, 105):
            slot[0] = current
            before = source.session.get.call_count
            result = source._verify_memory_stock(rows)
            selected = checked_ids(result)
            assert source.session.get.call_count - before == len(selected) == 20
            counts = Counter(identity.split("|")[1].split("-")[0] for identity in selected)
            assert set(counts) == set(PRODUCTS) and max(counts.values()) - min(counts.values()) <= 1
            seen |= selected
            reversed_result = source._verify_memory_stock(list(reversed(rows)))
            assert checked_ids(reversed_result) == selected
        assert seen == {row.listing_id for row in rows}
    finally:
        source.session.close()


def test_tiny_budget_rotates_categories_and_each_categorys_items(monkeypatch):
    slot = [0]
    monkeypatch.setattr(ebay, "MAX_STOCK_CHECKS", 1)
    monkeypatch.setattr(ebay, "_stock_rotation_slot", lambda:slot[0])
    rows = sum((rows_for(category, 3) for category in PRODUCTS), [])
    source = fixture_source(rows)
    try:
        seen = set()
        for current in range(9):
            slot[0] = current
            before = source.session.get.call_count
            selected = checked_ids(source._verify_memory_stock(rows))
            assert source.session.get.call_count - before == len(selected) == 1
            seen |= selected
        assert seen == {row.listing_id for row in rows}
    finally:
        source.session.close()


def test_new_source_instances_advance_real_round_even_after_a_long_backoff(monkeypatch):
    monkeypatch.setattr(ebay, "_STOCK_ROUNDS", count(0))
    rows = rows_for("gpu", 40)
    seen = set()
    for _ in range(2):
        # Match the monitor's fresh source per fetch. Actual elapsed time does
        # not matter; repeated 30-minute gaps cannot alias a 20-of-40 rotation.
        source = fixture_source(rows)
        try:
            seen |= checked_ids(source._verify_memory_stock(rows))
            assert source.session.get.call_count == 20
        finally:
            source.session.close()
    assert seen == {row.listing_id for row in rows}


def test_duplicates_and_ineligible_summaries_do_not_spend_other_categories_budget(monkeypatch):
    monkeypatch.setattr(ebay, "MAX_STOCK_CHECKS", 3)
    monkeypatch.setattr(ebay, "_stock_rotation_slot", lambda:0)
    good = sum((rows_for(category, 1) for category in PRODUCTS), [])
    bad = [replace(good[0], listing_id=f"v1|bad-{index}|0", **changes) for index, changes in enumerate([
        {"price":1250.01}, {"multi_variant":True}, {"seller_risk":"high"},
        {"condition_hint":"parts"}, {"sold":True}])]
    source = fixture_source(good)
    try:
        result = source._verify_memory_stock(bad + [good[0]] * 30 + good)
        assert source.session.get.call_count == 3
        assert checked_ids(result) == {row.listing_id for row in good}
        assert all(row.extra.get("shopping", {}).get("available") is not True for row in result[:len(bad)])
    finally:
        source.session.close()


def test_conflicting_identity_duplicate_cannot_borrow_verified_stock(monkeypatch):
    monkeypatch.setattr(ebay, "_stock_rotation_slot", lambda:0)
    row = rows_for("gpu", 1)[0]
    conflict = replace(row, title="NVIDIA RTX 4090 24GB graphics card")
    source = fixture_source([row])
    try:
        result = source._verify_memory_stock([row, conflict])
        assert source.session.get.call_count == 1
        assert result[0].extra["shopping"]["available"] is True
        assert result[1].extra["shopping"]["available"] is None
        assert "Conflicting search item identity" in result[1].extra["shopping"]["availability_note"]
    finally:
        source.session.close()
