import pytest

from alerters.techscout.facets import UNKNOWN, attributes


@pytest.mark.parametrize("title,expected", [
    ("Gaming PC RTX 5090 9800X3D 64GB DDR5 2TB NVMe SSD",
     {"gpu": "RTX 5090", "ram": "64GB", "cpu": "9800X3D", "storage": "2TB SSD"}),
    ("GeForce RTX 5090 32GB GDDR7 graphics card",
     {"gpu": "RTX 5090", "ram": UNKNOWN, "storage": UNKNOWN}),
    ("GeForce RTX 5090 32GB memory graphics card", {"ram": UNKNOWN}),
    ("Gaming PC RTX 5070Ti", {"gpu": "RTX 5070 TI"}),
    ("Dell OptiPlex 5090 16GB RAM 512GB SSD", {"gpu": UNKNOWN, "ram": "16GB"}),
    ("Gaming PC RTX 5090/5080 32GB or 64GB DDR5", {"gpu": UNKNOWN, "ram": UNKNOWN}),
    ("RTX 5090 and RTX 4090 GPU bundle", {"gpu": UNKNOWN}),
    ("NVIDIA RTX PRO 6000 Blackwell 96GB GDDR7", {"gpu": "RTX PRO 6000 BLACKWELL WORKSTATION", "ram": UNKNOWN}),
    ("iPad Air 256GB", {"gpu": UNKNOWN, "ram": UNKNOWN, "storage": UNKNOWN}),
    ("Memory kit 2 x 32GB DDR5", {"ram": "64GB"}),
    ("CORSAIR DDR5 16GB (1 x 16GB) Up to 6000MHz RAM", {"ram": "16GB", "kind": "Memory"}),
    ("Desktop RTX 5090 32GB DDR5 1000GB SSD", {"ram": "32GB", "kind": "Desktops"}),
    ("Laptop pocket backpack", {"kind": "Accessories"}),
    ("iPad case", {"kind": "Accessories"}),
    ("USB-C laptop docking station", {"kind": "Docks & hubs"}),
    ("B650 motherboard DDR5", {"kind": "Components"}),
    ("64GB (2x32GB) DDR5 memory kit", {"ram": "64GB"}),
    ("Gaming PC 32GB DDR5 supports up to 128GB RAM", {"ram": UNKNOWN}),
    ("Gaming PC 32GB RAM 64GB RAM", {"ram": UNKNOWN}),
    ("Desktop 1000GB SSD", {"storage": "1TB SSD"}),
    ("Desktop 1TB SSD and 2TB SSD", {"storage": UNKNOWN}),
])
def test_listing_attributes_keep_variants_and_memory_types_distinct(title, expected):
    actual = attributes({"title": title})
    for key, value in expected.items():
        assert actual[key] == value


def test_structured_ram_and_normalized_condition():
    actual = attributes({"title": "Desktop with up to 128GB RAM", "ram": 64, "condition": "open_box"})
    assert actual["ram"] == "64GB"
    assert actual["condition"] == "Open box"


def test_system_identity_does_not_turn_laptops_or_bare_cards_into_desktops():
    assert attributes({"title": "Alienware laptop RTX 3090", "is_system": True})["kind"] == "Laptops"
    assert attributes({"title": "Dell Alienware RTX 3090 24GB GDDR6X graphics card", "is_system": False})["kind"] == "Graphics cards"


def test_combined_publishers_supply_agreeing_details_without_splitting_card():
    row = {"title": "Gaming desktop", "reports": [
        {"title": "Gaming desktop RTX 5090 32GB DDR5 1000GB SSD"},
        {"title": "Gaming desktop RTX 5090 32GB DDR5 1TB SSD"},
    ]}
    assert attributes(row) == {"kind": "Desktops", "gpu": "RTX 5090", "ram": "32GB", "storage": "1TB SSD", "cpu": UNKNOWN, "condition": UNKNOWN}
    row["reports"][1]["title"] = "Gaming desktop RTX 5080 64GB DDR5 2TB SSD"
    assert all(attributes(row)[key] == UNKNOWN for key in ("gpu", "ram", "storage"))
