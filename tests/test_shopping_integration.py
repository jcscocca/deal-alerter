import json
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from alerters.hardware.shopping_controls import defaults, validate, read_controls, matches, delivery_filter
from alerters.hardware.shopping_export import ShoppingExport
from alerters.techscout.integration import Workspace, activity, judgment


def watch(**changes):
    return {"id": "a"*32, "name": "Desktop search", "enabled": True, "category": "desktop-memory",
            "filters": {"gpu": "RTX 5090", "ram": "64GB"}, "source": "newegg", "budget": 8000,
            "reuse": False, "product_id": "", **changes}


@pytest.mark.parametrize("changes", [{"budget": float("nan")}, {"budget": -1}, {"filters": {"path": "secrets"}},
                                     {"product_id": "../settings"}, {"source": "https://evil.test"}, {"enabled": "yes"}])
def test_watch_input_is_bounded(changes):
    with pytest.raises(ValueError):
        validate({**defaults(), "watches": [watch(**changes)]})


def test_invalid_saved_controls_fail_closed(tmp_path):
    path = tmp_path / "watches.json"
    path.write_text("broken")
    data, error = read_controls(path)
    assert error and data["mode"] == "paused"
    assert delivery_filter(data, None)(None) is False


def test_exact_filter_budget_source_and_reuse_never_broaden(tmp_path):
    detail = SimpleNamespace(title="Gaming PC RTX 5090 64GB DDR5", source="newegg", listing_id="pc", condition="new", is_system=True, total_price=7900)
    item = SimpleNamespace(key="prebuilt/newegg:abc", detail=detail, price=7900)
    plugin = SimpleNamespace(memory_fits={})
    assert matches(watch(), item, plugin)
    assert not matches(watch(budget=7800), item, plugin)
    assert not matches(watch(source="ebay"), item, plugin)
    assert not matches(watch(filters={"ram": "96GB"}), item, plugin)
    assert not matches(watch(reuse=True), item, plugin)
    assert not matches(watch(enabled=False), item, plugin)
    assert not matches(watch(product_id="newegg:"+"0"*24), item, plugin)
    # The UI prefers structured factory RAM evidence when the title omits it.
    item.detail.title = "Gaming PC RTX 5090"
    plugin.memory_fits[item.key] = SimpleNamespace(installed_gb=64, eligible=True)
    assert matches(watch(reuse=True), item, plugin)


def test_settings_revision_prevents_lost_edits_and_preserves_mode(tmp_path):
    (tmp_path / "shopping-sources.json").write_text(json.dumps({"capabilities": ["watches"]}))
    (tmp_path / "ui").mkdir()
    workspace = Workspace(tmp_path)
    original = workspace.state()
    settings = {**defaults(), "mode": "watches", "watches": [watch()]}
    assert workspace.update({"revision": original["revision"], "settings": settings})[0] == 200
    assert workspace.update({"revision": original["revision"], "settings": defaults()})[0] == 409
    assert read_controls(workspace.path)[0] == settings


def test_activity_retains_sent_receipt_without_duplicates_and_rejects_bad_links(tmp_path):
    exporter = ShoppingExport(tmp_path)
    item = {"id": "newegg:"+"a"*24, "source": "newegg", "title": "Example PC", "url": "https://www.newegg.com/p/ABC",
            "verdict": "STRONG", "price": 1000, "decisions": [{"channel": "ntfy", "status": "sent", "at": "2026-10-07T01:00:00.123456+00:00"}],
            "deliveries": [{"channel": "ntfy", "at": "2026-10-07T01:00:00+00:00", "price": 990}]}
    exporter.record_activity({"key": item})
    rows = activity(tmp_path)
    assert len(rows) == 1 and rows[0]["price"] == 990
    restarted = ShoppingExport(tmp_path)
    restarted.record_activity({"key": item})
    assert len(activity(tmp_path)) == 1
    item["url"] = "javascript:alert(1)"
    restarted.record_activity({"key": item})
    assert activity(tmp_path) == []


def test_judgment_projection_does_not_expose_arbitrary_fields():
    row = judgment({"verdict": "GOOD", "secret": "never", "reason": "Evidence", "eligible": False})
    assert row["reason"] == "Evidence" and row["eligible"] is False and "secret" not in row
