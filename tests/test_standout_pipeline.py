"""Real monitor judgments must survive export into the standout browser tier."""
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from alerters.hardware.monitor_sources import Batch
from alerters.hardware.parts_plugin import PartsHardwarePlugin
from alerters.hardware.shopping_activity import judgments
from alerters.hardware.shopping_export import ShoppingExport
from alerters.techscout.dashboard import snapshot
from dealcore.run import run
from dealcore.state import AlertState
from dealcore.types import FetchResult, Listing

ROOT = Path(__file__).resolve().parents[1]


def projected(tmp_path, title, price, identity, *, available=True):
    now = datetime.now(timezone.utc)
    listing = Listing("part", "ebay", title, "https://www.ebay.com/itm/123", now,
                      price=price, condition_hint="new", extra={"seller": "Known Store", "shopping": {
                          "item_price": price, "shipping": 0, "available": available,
                          "stock": "in_stock" if available else "out_of_stock",
                          "verified_price_watch": identity, "availability_checked_at": now.isoformat()}})
    plugin = PartsHardwarePlugin(ROOT / "config/hardware.toml", tmp_path / "state", now=now)
    plugin.sources = (SimpleNamespace(name="fixture", fetch=lambda: FetchResult([listing])),)
    receipts = AlertState(plugin.state_dir / "alerts.json", plugin.normalise_key)
    options = replace(plugin.options, dry_run=True, preview=tmp_path / "preview.html")
    result = run(plugin, receipts, options, (), now=now)
    assert not result.problems and len(result.assessments) == 1
    public_judgments = judgments(plugin, result, options, receipts, now)
    exporter = ShoppingExport(tmp_path)
    exporter.record("ebay", Batch(listings=[listing]), result.assessments, now, public_judgments)
    exporter.write({"ebay": {"kind": "legacy", "source": "ebay", "interval": 900, "error": ""}}, now.timestamp())
    data = snapshot(tmp_path / "reports", "monitor", now=now.timestamp(), monitor_runtime=tmp_path)
    rows = [r for g in data["groups"] for r in g["rows"]] + data["held"]
    assert len(rows) == 1
    return rows[0]


def browser_tier(row):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed for the projection-to-browser integration check")
    program = "const B=require(process.argv[1]);let s='';process.stdin.on('data',c=>s+=c);process.stdin.on('end',()=>console.log(B.recommendation(JSON.parse(s)).tier));"
    result = subprocess.run([node, "-e", program, str(ROOT / "alerters/techscout/web/browsing.js")],
                            input=json.dumps(row), capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_real_verified_monitor_discount_appears_in_standout_feed(tmp_path):
    row = projected(tmp_path, 'Alienware AW2725QF 27" 4K 180Hz IPS DisplayPort', 299.99, "AW2725QF")
    assert row["judgment"]["verdict"] == "STRONG"  # Actual engine grade, not a synthetic EXCEPTIONAL.
    assert "25.0% below AW2725QF" in row["judgment"]["standout_basis"]
    assert "2026-10-14" in row["judgment"]["standout_basis"]
    assert "not a sold-market valuation" in row["judgment"]["standout_basis"]
    assert browser_tier(row) == "standout"


def test_real_memory_target_does_not_borrow_monitor_discount_evidence(tmp_path):
    row = projected(tmp_path, "Corsair DDR5 UDIMM 96GB (2x48GB) Desktop Memory", 1109.99, "ddr5_udimm_96_kit")
    assert row["judgment"]["eligible"] and row["judgment"]["price_notice"]
    assert row["judgment"]["standout_basis"] == ""
    assert browser_tier(row) == "target"


def test_unavailable_monitor_cannot_claim_standout_discount(tmp_path):
    row = projected(tmp_path, 'Alienware AW2725QF 27" 4K 180Hz IPS DisplayPort', 299.99, "AW2725QF", available=False)
    assert not row["judgment"]["eligible"] and row["judgment"]["standout_basis"] == ""
    assert browser_tier(row) == "unassessed"
