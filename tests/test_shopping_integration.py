import json
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from alerters.hardware.shopping_controls import defaults, validate, read_controls, matches, delivery_filter
from alerters.hardware.shopping_export import ShoppingExport
from alerters.techscout.integration import Workspace, activity, judgment


def watch(**changes):
    return {"id": "a"*32, "name": "Graphics card deals", "enabled": True, "category": "parts",
            "filters": {"gpu": "RTX 3090"}, "source": "slickdeals", "budget": 900,
            "product_id": "", **changes}


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


def test_exact_filter_budget_and_source_never_broaden(tmp_path):
    detail = SimpleNamespace(title="NVIDIA RTX 3090 24GB graphics card", source="slickdeals",
                             listing_id="card", condition="new", is_system=False, total_price=850)
    item = SimpleNamespace(key="slickdeals:card", detail=detail, price=850)
    plugin = SimpleNamespace()
    assert matches(watch(), item, plugin)
    assert not matches(watch(budget=800), item, plugin)
    assert not matches(watch(source="ebay"), item, plugin)
    assert not matches(watch(filters={"gpu": "RTX 5090"}), item, plugin)
    assert not matches(watch(enabled=False), item, plugin)
    assert not matches(watch(product_id="slickdeals:"+"0"*24), item, plugin)
    item.detail.is_system = True
    assert not matches(watch(), item, plugin)


@pytest.mark.parametrize("category", ["desktop-memory", "computers", "tablets"])
def test_old_complete_machine_watches_are_disabled_during_migration(tmp_path, category):
    old = watch(category=category, reuse=True, product_id="ebay:" + "b"*24)
    path = tmp_path / "watches.json"
    path.write_text(json.dumps({"version":1, "mode":"watches", "watches":[old]}))
    data, error = read_controls(path)
    assert error is None and data["version"] == 3 and data["mode"] == "watches"
    assert data["watches"][0]["category"] == "parts"
    assert data["watches"][0]["enabled"] is False
    assert "reuse" not in data["watches"][0]


def test_component_watch_migrates_without_ram_completion_restrictions():
    data = validate({"version":1, "mode":"watches", "watches":[watch(category="monitor", reuse=True)]})
    assert data["watches"][0]["enabled"]
    assert "reuse" not in data["watches"][0]
    assert data["watches"][0]["filters"] == {"gpu":"RTX 3090"}


def test_exact_monitor_watch_retains_precise_identity_during_migration():
    original = watch(category="monitor", filters={}, source="ebay", reuse=False,
                     name="My monitor", product_id="ebay:" + "c"*24)
    data = validate({"version":1, "mode":"watches", "watches":[original]})
    retained = data["watches"][0]
    assert retained["enabled"] and retained["product_id"] == original["product_id"]
    assert retained["filters"] == {} and retained["source"] == "ebay"


def test_settings_revision_prevents_lost_edits_and_preserves_mode(tmp_path):
    (tmp_path / "shopping-sources.json").write_text(json.dumps({"capabilities": ["watches", "watches-v2", "watches-v3"]}))
    (tmp_path / "ui").mkdir()
    workspace = Workspace(tmp_path)
    original = workspace.state()
    settings = {**defaults(), "mode": "watches", "watches": [watch()]}
    assert workspace.update({"revision": original["revision"], "settings": settings})[0] == 200
    assert workspace.update({"revision": original["revision"], "settings": defaults()})[0] == 409
    assert read_controls(workspace.path)[0] == settings


@pytest.mark.parametrize("capabilities", [["watches"], ["watches", "watches-v2"]])
def test_new_dashboard_cannot_write_v3_settings_to_older_monitor(tmp_path, capabilities):
    (tmp_path / "shopping-sources.json").write_text(json.dumps({"capabilities": capabilities}))
    (tmp_path / "ui").mkdir()
    path = tmp_path / "ui" / "watches.json"
    original = json.dumps({"version": 1, "mode": "all", "watches": []})
    path.write_text(original)
    workspace = Workspace(tmp_path)
    state = workspace.state()
    assert state["settings"]["version"] == 3 and not state["supported"]
    status, result = workspace.update({"revision": state["revision"], "settings": defaults()})
    assert status == 409 and "Update the installed monitor" in result["error"]
    assert path.read_text() == original


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


def test_unpriced_announcement_receipt_is_not_a_free_product(tmp_path):
    exporter = ShoppingExport(tmp_path)
    exporter.record_activity({"announcement": {
        "id": "slickdeals:" + "b" * 24, "source": "slickdeals",
        "title": "Desktop announcement", "url": "https://slickdeals.net/f/123-example",
        "verdict": "GOOD", "price": None, "decisions": [],
        "deliveries": [{"channel": "ntfy", "at": "2026-10-07T01:00:00+00:00", "price": 0}],
    }})
    # The original receipt remains intact; only its public price is unknown.
    restarted = ShoppingExport(tmp_path)
    assert len(restarted.events) == 1
    assert activity(tmp_path)[0]["price"] is None


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("mode", ["all", "watches", "paused"])
def test_migration_preserves_mode_and_requires_explicit_target_opt_in(version, mode):
    old = watch(**({"reuse": False} if version == 1 else {}))
    result = validate({"version": version, "mode": mode, "watches": [old]})
    assert result["version"] == 3 and result["mode"] == mode
    assert result["include_target_notices"] is False
    assert result["watches"][0]["enabled"]


@pytest.mark.parametrize("value", [None, 0, 1, "true"])
def test_target_opt_in_requires_explicit_boolean(value):
    with pytest.raises(ValueError, match="explicitly"):
        validate({**defaults(), "include_target_notices": value})


def test_filter_applies_policy_before_watch_subscription():
    item = SimpleNamespace()
    calls = []
    plugin = SimpleNamespace(notification_allowed=lambda row, **kwargs: calls.append(kwargs) or kwargs["include_target_notices"])
    assert not delivery_filter(defaults(), plugin)(item)
    assert delivery_filter({**defaults(), "include_target_notices": True}, plugin)(item)
    assert not delivery_filter({**defaults(), "mode": "paused", "include_target_notices": True}, plugin)(item)
    assert len(calls) == 2
    assert not delivery_filter({**defaults(), "mode": "watches", "include_target_notices": True}, plugin)(item)


def test_upgrade_marker_prevents_writes_without_changing_preferences(tmp_path):
    (tmp_path / "shopping-sources.json").write_text(json.dumps({"capabilities": ["watches-v3"]}))
    (tmp_path / "ui").mkdir()
    workspace = Workspace(tmp_path)
    original = workspace.state()
    marker = tmp_path / "ui" / "upgrade-in-progress.json"
    marker.write_text("{}")
    status, result = workspace.update({"revision": original["revision"], "settings": defaults()})
    assert status == 503 and "upgrade in progress" in result["error"].lower()
    assert not workspace.path.exists()
