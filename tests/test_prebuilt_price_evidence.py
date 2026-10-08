from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json

import pytest

from alerters.hardware.prebuilt import Offer, PrebuiltHistory
from alerters.hardware.price_evidence import PriceEvidence, configuration_key, offer_key
from alerters.techscout.prebuilt_value import attach_values
from alerters.techscout.price_history import record_research, walmart_key
from alerters.techscout.research import Product, Research

NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


def pc(**changes):
    return Offer(**dict(retailer="newegg", sku="ABC", title="Gaming PC RTX 5090 9800X3D 32GB DDR5 2TB SSD",
                        url="https://www.newegg.com/p/ABC", seller="Builder", condition="new", specs={},
                        base_price=4000, shipping=0, stock="in_stock", confirmed=True,
                        observed_at=NOW.isoformat(), **changes))


def row(**changes):
    return {"id": "self", "title": pc().title, "available": True, "stock": "in_stock", "total": 4000, "lead": False,
            "condition": "New", "seller": "Builder", "source": "newegg", "retailer": "Newegg", "url": pc().url,
            "checked_at": NOW.isoformat(), "expires_at": NOW.timestamp()+900, "verification_reasons": [], **changes}


def test_daily_samples_returning_prices_and_legacy_range(tmp_path):
    history = PriceEvidence(tmp_path / "prices.json")
    for days, total in ((4, 5000), (3, 4500), (2, 5000), (0, 4000)):
        at = NOW-timedelta(days=days)
        history.record("pc", total, at.isoformat())
        for minute in range(1, 10):
            history.record("pc", total, (at+timedelta(minutes=minute)).isoformat())
    history.save()
    history = PriceEvidence(history.path)
    stats = history.summary("pc", (NOW+timedelta(minutes=10)).isoformat(), [
        {"seen_at": (NOW-timedelta(days=40)).isoformat(), "total": 3000},
        {"seen_at": (NOW-timedelta(days=100)).isoformat(), "total": 1}])
    assert len(history.rows) == 4 and stats["prior_days"] == 3
    assert stats["median"] == 5000 and stats["low"] == 3000 and stats["legacy_prices"] == 1
    assert stats["observed_days"] == 4


def test_new_price_cannot_move_its_own_baseline_and_older_quote_cannot_overwrite(tmp_path):
    h = PriceEvidence(tmp_path / "prices.json")
    h.record("pc", 4500, NOW.isoformat())
    h.record("pc", 5000, (NOW-timedelta(minutes=1)).isoformat())
    h.record("pc", 4000, (NOW+timedelta(minutes=1)).isoformat())
    assert h.rows[0]["total"] == 4000 and h.rows[0]["high"] == 4500
    assert h.summary("pc", (NOW+timedelta(minutes=2)).isoformat())["median"] is None
    next_day = h.summary("pc", (NOW+timedelta(days=1)).isoformat())
    assert next_day["low"] == 4000 and next_day["high"] == 4500


def test_monitor_reuses_old_range_without_treating_distinct_prices_as_daily_samples(tmp_path):
    h = PrebuiltHistory(tmp_path)
    for days, price in ((4, 4800), (3, 4200)):
        offer = replace(pc(), base_price=price, observed_at=(NOW-timedelta(days=days)).isoformat())
        h.rows.append({"key": offer.key, "total": price, "seen_at": offer.observed_at,
                       "offer": asdict(offer), "condition": "new"})
    h.record(pc(), NOW)
    h.save()
    evidence = PrebuiltHistory(tmp_path).evidence(pc(), NOW)
    assert evidence["low"] == 4200 and evidence["median"] is None
    assert evidence["legacy_prices"] == 2 and evidence["observed_days"] == 1
    assert h.evidence(replace(pc(), seller="Another"), NOW)["low"] is None
    assert h.evidence(replace(pc(), title=pc().title + " 64GB upgrade"), NOW)["low"] is None


@pytest.mark.parametrize("change", [{"stock": "out_of_stock"}, {"stock": "preorder"}, {"confirmed": False},
                                    {"announcement": True}, {"shipping": None}, {"condition": "unknown"}])
def test_unavailable_quotes_do_not_enter_daily_history(tmp_path, change):
    h = PrebuiltHistory(tmp_path)
    h.record(replace(pc(), **change), NOW)
    assert h.observations.rows == []


def test_identity_separates_region_specs_condition_seller_and_title():
    args = ["walmart", "123", "Seller", "new", pc().title, {"RAM": "32GB"}, "94105"]
    original = configuration_key(*args)
    for i, value in ((2,"Seller2"),(3,"used"),(4,pc().title+" updated"),(5,{"RAM":"64GB"}),(6,"10001")):
        changed = list(args)
        changed[i] = value
        assert configuration_key(*changed) != original


def test_stale_history_never_claims_current_discount():
    stats = {"median": 5000, "low": 4500, "high": 5200, "prior_days": 3}
    live = row(price_history=stats)
    stale = row(price_history=stats, reasons=["Check failed"])
    stale["verification_reasons"] = ["Check failed"]
    attach_values([live, stale], NOW.timestamp())
    assert live["prebuilt_value"]["history"]["difference_pct"] == -20
    assert stale["prebuilt_value"]["history"]["difference_pct"] is None


def test_untracked_source_does_not_claim_to_be_collecting_history():
    item = row(source="ebay", stock="unknown")
    attach_values([item], NOW.timestamp())
    assert not item["prebuilt_value"]["history"]["tracked"]
    assert item["prebuilt_value"]["history"]["label"] == "History not tracked for this source"


def test_walmart_capture_is_available_only_and_dashboard_get_is_read_only(tmp_path):
    from alerters.techscout.dashboard import snapshot
    product = Product("123", pc().title, "Walmart.com", "New", 4000, 0, "Available", True, "MODEL", {}, [])
    research = Research("desktop-memory", "94105", NOW.isoformat(), [], [], [product, replace(product, item_id="456", available=False)], [])
    record_research(tmp_path, research)
    history = PriceEvidence(tmp_path / "walmart-prebuilt-observations.json")
    assert len(history.rows) == 1 and history.rows[0]["key"] == walmart_key(asdict(product), "94105")
    (tmp_path / "latest-desktop-memory.json").write_text(json.dumps(research.document()))
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    for category in ("desktop-memory", "monitor"):
        result = snapshot(tmp_path, category, now=NOW.timestamp())
        rows = [r for g in result["groups"] for r in g["rows"]] + result["held"]
        assert next(r for r in rows if r["id"] == "123")["prebuilt_value"]["history"]["observed_days"] == 1
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
