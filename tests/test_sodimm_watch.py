"""Whole-purchase memory limits, conservative identity and actual delivery."""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from alerters.hardware.native.match import match
from alerters.hardware.prebuilt_plugin import MonitorHardwarePlugin
from alerters.hardware.sodimm import configuration
from alerters.techscout.facets import product_type, ram, attributes, UNKNOWN
from alerters.techscout.monitor_bridge import categories
from dealcore.notify import Channel
from dealcore.run import run
from dealcore.state import AlertState
from dealcore.types import FetchResult, Listing

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(timezone.utc)


def execute(tmp_path, title="Crucial 32GB DDR5-5600 SO-DIMM Laptop Memory", price=200, **changes):
    row = replace(Listing("memory", "ebay", title, "https://www.ebay.com/itm/123", NOW,
                          price=price, condition_hint="new"), **changes)
    plugin = MonitorHardwarePlugin(ROOT / "config/hardware.toml", tmp_path, now=NOW)
    try:
        plugin.sources = (SimpleNamespace(name="fixture", fetch=lambda: FetchResult([row])),)
        sent = []
        result = run(plugin, AlertState(plugin.state_dir / "alerts.json", plugin.normalise_key),
                     replace(plugin.options, quiet_when_empty=True, preview=tmp_path / "preview.html"),
                     (Channel("fixture", "push", sent.append),), now=NOW)
        assert not result.problems
        return sent, result
    finally:
        plugin.close()


@pytest.mark.parametrize("title,key,price", [
    ("Crucial 32GB DDR5-5600 SO-DIMM Laptop Memory", "ddr5_sodimm_32", 200),
    ("Kingston 48GB DDR5 5600 SODIMM Notebook RAM", "ddr5_sodimm_48", 300),
    ("Crucial 64GB (2 x 32GB) DDR5 SODIMM Laptop Memory Kit", "ddr5_sodimm_64_kit", 400),
    ("Crucial 96GB (48GB x 2) DDR5 SO-DIMM kit", "ddr5_sodimm_96_kit", 600),
    ("CT2K48G56C46S5", "ddr5_sodimm_96_kit", 600),
    ("2x48GB Crucial CT48G56C46S5 DDR5 SO-DIMM", "ddr5_sodimm_96_kit", 600),
    ("Crucial 32GB DDR5 5600 (or 5200 or 4800) SODIMM Laptop Memory", "ddr5_sodimm_32", 200),
])
def test_correct_capacity_and_whole_kit_delivery(tmp_path, title, key, price):
    parsed = match(title, price=price)
    assert parsed.part.key == key and parsed.unit_price == price and parsed.quantity == 1
    assert product_type(title) == "Memory" and categories(title) == {"memory"}
    sent, result = execute(tmp_path, title, price)
    assert sent[0].buys[0].badge == "SO-DIMM PRICE WATCH"
    assert result.assessments[0].price == price
    assert not result.assessments[0].loggable
    assert not result.assessments[0].detail.reference_trusted
    assert not execute(tmp_path / "over", title, price + .01)[0]


@pytest.mark.parametrize("title", [
    "32GB DDR4 SODIMM", "32GB DDR5 desktop UDIMM", "32GB DDR5 ECC SODIMM",
    "48GB DDR5 Registered RDIMM", "32GB DDR5 SO-DIMM adapter",
    "DDR5 SO-DIMM 32GB/48GB choose size", "DDR5 SO-DIMM 32GB kit",
    "DDR5 SO-DIMM 32/48GB", "DDR5 SO-DIMM 32 or 48GB",
    "Dell laptop CT32G56C46S5",
    "DDR5 SO-DIMM 64GB", "DDR5 SO-DIMM 96GB", "DDR5 SO-DIMM 2x16GB 32GB kit",
    "DDR5 SO-DIMM 2x32GB 96GB kit", "DDR5 SO-DIMM 4x32GB 128GB",
    "CT2K48G56C46S5 2x32GB", "CT32G56C46S5 48GB",
    "CT32G56C46S5 CT48G56C46S5", "2x Crucial 32GB DDR5 SO-DIMM",
    "32GB DDR5 SO-DIMM lot of 4", "32GB DDR5 SO-DIMM 2 pack",
    "Lenovo ThinkPad P16 32GB DDR5 SO-DIMM i7-13700HX 1TB SSD",
    "Laptop 32GB DDR5 SO-DIMM", "RTX 5080 32GB DDR5 desktop gaming PC",
])
def test_wrong_modules_ambiguous_kits_and_whole_computers_are_not_memory_alerts(title):
    assert configuration(title) is None


@pytest.mark.parametrize("changes", [
    {"seller_risk":"moderate"}, {"seller_risk":"high"}, {"condition_hint":"unknown"},
    {"sold":True}, {"multi_variant":True}, {"condition_hint":"parts"},
    {"extra":{"shopping":{"available":False}}},
    {"title":"32GB DDR5 SO-DIMM for parts not working"},
    {"title":"32GB DDR5 SO-DIMM after trade-in rebate"},
    {"title":"2x48GB DDR5 SO-DIMM $200 each"},
    {"title":"[H] PayPal [W] 32GB DDR5 SO-DIMM"},
])
def test_risk_stock_and_condition_vetoes(tmp_path, changes):
    assert not execute(tmp_path, **changes)[0]


@pytest.mark.parametrize("condition", ["new", "used", "open_box", "refurbished"])
def test_price_ordered_source_and_working_conditions_can_alert(tmp_path, condition):
    # eBay's sorted asks are not a statistical market sample; they still support
    # explicit price notices. They must never become cross-brand market history.
    assert execute(tmp_path, price=99, condition_hint=condition, loggable=False)[0]


def test_dedup_and_material_price_drop(tmp_path):
    assert execute(tmp_path)[0]
    assert not execute(tmp_path)[0]
    assert execute(tmp_path, price=180)[0]


def test_kit_facets_do_not_report_one_module_capacity():
    assert ram("96GB (2x48GB) DDR5 SODIMM Laptop Memory Kit") == "96GB"
    assert ram("Crucial CT2K32G56C46S5") == "64GB"
    assert categories("DDR5 32GB desktop memory kit") == {"memory"}
    assert categories("Gaming PC RTX 5080 32GB DDR5 2TB SSD") != {"memory"}
    assert attributes({"title":"32GB DDR5 SO-DIMM Laptop Memory"})["memory_layout"] == "DDR5 SO-DIMM 1x32GB"
    assert attributes({"title":"32GB (2x16GB) DDR5 SO-DIMM Laptop Memory"})["memory_layout"] == UNKNOWN
    assert attributes({"title":"32GB DDR5 desktop UDIMM memory"})["memory_layout"] == UNKNOWN


def test_memory_queries_fit_without_displacing_prior_watches(tmp_path):
    plugin = MonitorHardwarePlugin(ROOT / "config/hardware.toml", tmp_path)
    try:
        assert len(plugin.cfg.search_queries) == 29
        for capacity in (32, 48, 64, 96):
            assert f"DDR5 SO-DIMM {capacity}GB" in plugin.cfg.search_queries
            assert plugin.cfg.query_price_floors[f"DDR5 SO-DIMM {capacity}GB"] == 0
        assert any("Zenbook" in q for q in plugin.cfg.search_queries)
    finally:
        plugin.close()
