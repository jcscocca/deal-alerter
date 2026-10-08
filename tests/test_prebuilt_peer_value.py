from copy import deepcopy

import pytest

from alerters.hardware.prebuilt_specs import build_specs
from alerters.techscout.prebuilt_value import attach_values
from tests.test_prebuilt_price_evidence import NOW, pc, row


def sample():
    return [row(), row(id="b", seller="Other builder", total=5000, build_specs={"Model":"DESKTOP-002"}),
            row(id="c", seller="Third builder", total=4500, build_specs={"Model":"DESKTOP-003"}),
            row(id="d", seller="Third builder", total=5500, build_specs={"Model":"DESKTOP-004"})]


def test_matched_peers_exclude_self_use_shipping_total_and_explain_sample():
    rows = sample()
    rows[0]["price"] = 1000  # Before-tax delivered total, not headline price.
    attach_values(rows, NOW.timestamp())
    peers = rows[0]["prebuilt_value"]["peers"]
    assert peers["median"] == 5000 and peers["difference_pct"] == -20
    assert peers["count"] == 3 and peers["sellers"] == 2
    assert peers["label"] == "Below peer median" and peers["low"] == 4500 and peers["high"] == 5500
    assert {r["id"] for r in peers["offers"]} == {"b","c","d"}
    assert all(r["build_details"]["Warranty"] == "Not published" for r in peers["offers"])


@pytest.mark.parametrize("change", [
    {"available": False}, {"stock":"out_of_stock"}, {"lead":True}, {"total":None}, {"total":float("nan")},
    {"expires_at":NOW.timestamp()-1}, {"checked_at":"2030-01-01T00:00:00Z"},
    {"verification_reasons":["Latest source check failed"]}, {"condition":"Used"},
    {"title":pc().title.replace("5090","5080")}, {"title":pc().title.replace("9800X3D","9950X3D")},
    {"title":pc().title.replace("32GB","64GB")}, {"title":pc().title.replace("DDR5","DDR4")},
    {"title":pc().title.replace("2TB","4TB")}, {"seller":"Not published"},
])
def test_unsafe_or_different_build_never_supports_peer_rating(change):
    rows=sample()
    rows[1].update(change)
    attach_values(rows,NOW.timestamp())
    peers=rows[0]["prebuilt_value"]["peers"]
    assert peers["median"] is None and peers["count"] == 2


def test_repeated_seller_model_and_cross_retailer_listing_do_not_inflate_sample():
    rows=sample()
    duplicate=deepcopy(rows[1])
    duplicate.update(id="duplicate",source="walmart",retailer="Walmart",total=4900)
    rows += [duplicate, row(id="own_duplicate",total=1)]
    attach_values(rows,NOW.timestamp())
    peers=rows[0]["prebuilt_value"]["peers"]
    assert peers["count"] == 3 and peers["median"] == 4900
    assert "duplicate" in {r["id"] for r in peers["offers"]}
    assert "b" not in {r["id"] for r in peers["offers"]}


def test_one_seller_cannot_establish_a_market_rating():
    rows=sample()
    for p in rows[1:]:
        p["seller"]="Single seller"
    attach_values(rows,NOW.timestamp())
    peers=rows[0]["prebuilt_value"]["peers"]
    assert peers["count"] == 3 and peers["median"] is None


@pytest.mark.parametrize("title,specs", [
    (pc().title, {"CPU Name":"Ryzen 9 9950X3D"}),
    (pc().title, {"Selected Anniversary Edition":"9950X3D / RTX5090 / 64GB DDR5 / 4TB"}),
    (pc().title, {"Memory Capacity":"64GB DDR5"}),
    (pc().title, {"GPU/VGA Type":"RTX 5080"}),
    (pc().title, {"GPU/VGA Type":"RTX 4090"}),
    (pc().title, {"Selected Options":"9800X3D / 5080 / 32G / 2T"}),
    (pc().title, {"Selected Edition":"9800X3D / RTX5090 / 32GB DDR5 / 4TB"}),
    (pc().title, {"SSD":"4TB"}),
    (pc().title.replace("2TB", "2 x 2TB"), {}),
    (pc().title + " + 2TB SSD", {}),
    (pc().title + " 4TB HDD", {}),
    (pc().title.replace("32GB DDR5", "32GB GDDR7"), {}),
    (pc().title.replace("32GB DDR5", ""), {}),
    (pc().title.replace("32GB DDR5", "supports 128GB DDR5"), {}),
    (pc().title.replace("9800X3D", "Ryzen 7"), {}),
    (pc().title + " choose your configuration", {}),
])
def test_conflicting_unknown_and_multidrive_specs_fail_closed(title,specs):
    build=build_specs(title,specs,"New")
    assert build["key"] is None and build["issues"]


def test_structured_specs_and_aliases_match_without_guessing_unknown_parts():
    title="Gaming PC RTX 5090 Ultra 9 285K 32GB GDDR7 32GB DDR5 2TB SSD"
    build=build_specs(title,{"CPU Name":"Intel Core Ultra 9 285K", "Selected CPU":"U9 285K",
                            "Memory Capacity":"2 x 16GB DDR5", "SSD":"2TB NVMe", "Power Supply":"1000W",
                            "Included components":"Motherboard: Z890\nCPU Cooler: 360mm AIO\nWarranty: 1 Year Parts & Labor\nComponent brands may vary"},"New")
    assert build["key"] is not None and build["core"]["ram_gb"] == 32
    assert build["core"]["cpu"] == "ULTRA 9 285K"
    assert build["details"]["Warranty"] == "1 Year Parts & Labor"
    assert build["variable_parts"]


def test_ram_reuse_preference_does_not_suppress_price_evidence():
    rows=sample()
    rows[0].update(preference_reasons=["No reuse path"],reasons=["No reuse path"],eligible=False)
    attach_values(rows,NOW.timestamp())
    assert rows[0]["prebuilt_value"]["peers"]["median"] == 5000


def test_expired_or_sold_out_target_gets_no_current_rating():
    rows=sample()
    rows[0].update(stock="out_of_stock",available=False)
    attach_values(rows,NOW.timestamp())
    assert rows[0]["prebuilt_value"]["peers"]["median"] is None
