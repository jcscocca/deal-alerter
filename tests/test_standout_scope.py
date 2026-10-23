"""Shopping scope keeps real parts while excluding old and implicit full builds."""
from pathlib import Path

import pytest

from alerters.techscout.facets import attributes, product_type
from alerters.techscout.scope import allowed_title, categories, in_scope


@pytest.mark.parametrize("title,kind,expected_categories", [
    ("AMD Ryzen 9 9950X3D", "Components", {"parts"}),
    ("Intel Core i7-14700K desktop processor", "Components", {"parts"}),
    ("AMD Ryzen 7 9800X3D + ASUS B650 motherboard + 32GB DDR5 RAM bundle", "Components", {"parts"}),
    ("AMD Ryzen 7 9800X3D + ASUS B650 motherboard + 32GB DDR5 RAM + 1TB SSD bundle", "Storage", {"parts"}),
    ("Samsung 990 Pro 2TB NVMe SSD for desktop and laptop", "Storage", {"parts"}),
    ("Crucial laptop NVMe SSD 2TB", "Storage", {"parts"}),
    ("Crucial 32GB DDR5 Laptop Memory SODIMM", "Memory", {"parts", "memory"}),
    ("Corsair 32GB DDR5 RAM for desktop PCs", "Memory", {"parts", "memory"}),
    ("Corsair Vengeance DDR5 64GB Desktop Memory Kit", "Memory", {"parts", "memory"}),
    ("MSI GeForce RTX 5090 desktop graphics card 32GB GDDR7", "Graphics cards", {"parts"}),
    ("NVIDIA RTX 5090 graphics card pulled from prebuilt desktop", "Graphics cards", {"parts"}),
    ("NVIDIA RTX 5090 graphics card removed from a desktop", "Graphics cards", {"parts"}),
    ("Fractal Design North ATX desktop computer case", "Components", {"parts"}),
    ("Fractal Design North gaming PC case", "Components", {"parts"}),
    ("Corsair RM1000x 1000W power supply for desktop PCs", "Components", {"parts"}),
    ("Corsair RM1000x power supply compatible RTX 5090 desktop PCs", "Components", {"parts"}),
    ("Cooler Master CPU air cooler for gaming desktop PCs", "Components", {"parts"}),
    ("LG 32 inch 4K gaming monitor for laptop and desktop computer", "Monitors", {"monitors"}),
    ("Dell P2723QE 27 inch monitor USB-C hub", "Monitors", {"monitors"}),
    ("Dell monitor power supply adapter", "Accessories", {"supplies"}),
    ("VESA monitor arm", "Accessories", {"supplies"}),
    ("USB C docking station for MacBook Pro", "Docks & hubs", {"supplies"}),
    ("Anker USB-C hub for iPad Pro and laptop", "Docks & hubs", {"supplies"}),
    ("Mac mini docking station", "Docks & hubs", {"supplies"}),
    ("Samsung Galaxy Tab S10 keyboard cover", "Accessories", {"supplies"}),
    ("Apple MacBook Pro laptop sleeve", "Accessories", {"supplies"}),
])
def test_identifiable_individual_products_keep_scope_and_categories(title, kind, expected_categories):
    assert allowed_title(title)
    assert in_scope({"title": title})
    assert product_type(title) == kind
    assert attributes({"title": title})["kind"] == kind
    assert categories(title) == expected_categories


@pytest.mark.parametrize("title", [
    "Gaming PC RTX 5080 Ryzen 7 9800X3D 32GB DDR5 1TB SSD",
    "Gaming PC RTX 5090 9950X3D 32GB RAM 1TB SSD with monitor",
    "HP OMEN 45L RTX 5090 64GB RAM 2TB SSD",
    "Framework Desktop AMD Ryzen AI Max+ 395 128GB RAM",
    "Mac mini M4 24GB RAM",
    "Mac mini with docking station",
    "MSI Aegis R2 GeForce RTX 5070",
    "MSI Aegis R2 Intel Core Ultra 7 265F RTX 5070 32GB DDR5 2TB SSD",
    "Lenovo Legion Tower 5 Ryzen 7 9700X 32GB DDR5 1TB SSD RTX 5070",
    "HP Envy x360 Intel Core Ultra 7 32GB RAM 1TB SSD",
    "ASUS ROG Strix G16 Intel Core i9 RTX 5080 32GB DDR5 1TB SSD",
    "Skytech Azure 2 Ryzen 7 9700X 32GB DDR5 1TB SSD",
    "Skytech Azure 2 32GB DDR5 1TB SSD",
    "iBUYPOWER Y40 GeForce RTX 5070",
    "ASUS Zenbook Duo Core Ultra X9 388H 32GB RAM",
    "HP Victus 15 Intel Core i5 16GB RAM 512GB SSD",
    "Intel Core Ultra 7 32GB DDR5 1TB SSD",
    "Ryzen 7 9700X 32GB DDR5 1TB SSD",
    "AMD 9950X3D 32GB RAM 2TB NVMe",
    "RTX 5080 laptop 32GB RAM",
    "Samsung Galaxy Tab S10 Ultra Wi-Fi 256GB",
    "Samsung Galaxy Tab S10 with keyboard cover",
    "Apple iPad Pro 13 inch M5 256GB with Magic Keyboard",
    "iPad Air 256GB tablet",
    "Sunday sale roundup",
    "",
])
def test_complete_computers_and_unidentified_products_cannot_return_via_loaded_results(title):
    assert not allowed_title(title)
    assert not in_scope({"title": title})
    assert categories(title) == set()


def test_enriched_short_name_does_not_discard_an_identified_part():
    row = {"title": "Samsung 990 Pro 2TB NVMe SSD", "product_name": "Samsung 990 Pro 2TB"}
    assert in_scope(row)
    assert attributes(row)["kind"] == "Storage"


@pytest.mark.parametrize("name", ["Gaming PC RTX 5090", "HP Envy x360", "iPad Air 256GB", "Mac mini"])
def test_enriched_computer_name_cannot_smuggle_a_system_into_a_component_card(name):
    assert not in_scope({"title": "GeForce RTX 5090 graphics card", "product_name": name})


def test_explicit_system_identity_wins_over_a_component_title():
    assert not in_scope({"title": "GeForce RTX 5090 graphics card", "is_system": True})
    assert categories("GeForce RTX 5090 graphics card", is_system=True) == set()


@pytest.mark.parametrize("title,expected_categories", [
    ('Alienware AW2725QF 27" 4K 180Hz IPS DisplayPort', {"monitors"}),
    ("Corsair DDR5 UDIMM 96GB (2x48GB) Desktop Memory", {"parts", "memory"}),
])
def test_price_only_catalog_products_remain_in_scope_after_runtime_initialization(tmp_path, title, expected_categories):
    from alerters.hardware.parts_plugin import PartsHardwarePlugin
    root = Path(__file__).resolve().parents[1]
    plugin = PartsHardwarePlugin(root / "config/hardware.toml", tmp_path)
    try:
        assert allowed_title(title)
        assert in_scope({"title": title})
        assert categories(title) == expected_categories
        assert not allowed_title("ASUS Zenbook Duo Core Ultra X9 388H 32GB RAM")
    finally:
        plugin.close()
