"""The active hardware product watches parts, never a completed PC project."""
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from alerters.__main__ import PLUGINS
from alerters.hardware import monitor
from alerters.hardware.desktop_profile import DesktopProfile
from alerters.hardware.monitor_sources import Batch
from alerters.hardware.native.config import Config
from alerters.hardware.native.sources.reddit import INTERESTING_FLAIRS
from alerters.hardware.parts_plugin import PartsHardwarePlugin
from alerters.hardware.prebuilt import Offer
from alerters.hardware.prebuilt_plugin import offer_listing
from dealcore.notify import Channel
from dealcore.run import run
from dealcore.state import AlertState
from dealcore.types import FetchResult, Listing

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(timezone.utc)


def listing(title="NVIDIA RTX 3090 24GB graphics card", price=850, **changes):
    return replace(Listing("part", "slickdeals", title, "https://example.invalid/part", NOW,
                           price=price, condition_hint="new"), **changes)



def verified_listing(title="NVIDIA RTX 3090 24GB graphics card", price=850, *, key="rtx_3090", **changes):
    return listing(title, price, source="ebay", url="https://www.ebay.com/itm/123456789012",
                   extra={"seller": "EstablishedStore", "shopping": {
                       "available": True, "stock": "in_stock", "item_price": price, "shipping": 0,
                       "availability_checked_at": NOW.isoformat(), "verified_price_watch": key}}, **changes)


def execute(tmp_path, rows, *, include_target_notices=False, channel_kind="push"):
    plugin = PartsHardwarePlugin(ROOT / "config/hardware.toml", tmp_path, now=NOW)
    plugin.sources = (SimpleNamespace(name="fixture", fetch=lambda: FetchResult(rows)),)
    sent = []
    result = run(plugin, AlertState(plugin.state_dir / "alerts.json", plugin.normalise_key),
                 replace(plugin.options, quiet_when_empty=True, preview=tmp_path / "preview.html",
                         notify_filter=lambda item: plugin.notification_allowed(item, include_target_notices=include_target_notices)),
                 (Channel("fixture", channel_kind, sent.append),), now=NOW)
    assert not result.problems
    return sent, result


@pytest.mark.parametrize("ram", [32, 64, 96, 128])
def test_whole_pc_is_never_judged_alerted_or_logged_regardless_of_ram(tmp_path, ram):
    offer = Offer("newegg", "retired", f"Gaming PC RTX 5090 {ram}GB DDR5 4TB SSD",
                  "https://www.newegg.com/p/3D5-000Z-002C6", "Newegg", "new",
                  {"RAM": f"{ram}GB DDR5"}, 4000, 0, "in_stock", True, NOW.isoformat())
    rows = [offer_listing(offer), listing(offer.title, price=4000)]
    sent, result = execute(tmp_path, rows)
    assert not sent and not result.assessments
    assert not (tmp_path / "hardware/US/prices.jsonl").read_text().strip()
    assert not list(tmp_path.rglob("prebuilt-*"))


def test_standalone_bargain_can_alert_below_owned_gpu_capacity(tmp_path):
    sent, result = execute(tmp_path, [verified_listing()])
    assert len(sent) == 1
    item = result.assessments[0]
    assert item.detail.vram_before == 32 and 0 < item.detail.vram_after < 24
    assert item.alertable and item.loggable and item.verdict >= item.verdict.EXCEPTIONAL
    assert "Capped:" not in item.detail.reason
    assert "WHOLE-PC" not in sent[0].buys[0].badge


@pytest.mark.parametrize("changes", [{"price":650}, {"seller_risk":"high"}, {"condition_hint":"parts"}])
def test_removing_upgrade_veto_does_not_remove_price_or_seller_vetoes(tmp_path, changes):
    sent, _ = execute(tmp_path, [listing(**changes)])
    assert not sent


@pytest.mark.parametrize("title,price,key,badge", [
    ("NVIDIA GeForce RTX 5080 graphics card", 1400, "rtx_5080", "CARD PRICE WATCH"),
    ("Corsair DDR5 UDIMM 96GB (2x48GB) Desktop Memory", 1109.99, "ddr5_udimm_96_kit", "DESKTOP RAM PRICE WATCH"),
    ('Alienware AW2725QF 27" 4K 180Hz IPS DisplayPort', 299.99, "AW2725QF", "4K MONITOR PRICE WATCH")])
def test_product_notices_need_no_desktop_ram_profile(tmp_path, monkeypatch, title, price, key, badge):
    monkeypatch.setattr(DesktopProfile, "__init__", lambda *_: pytest.fail("Retired RAM profile was loaded"))
    row = verified_listing(title, price, key=key)
    sent, result = execute(tmp_path, [row], include_target_notices=True)
    assert len(sent) == 1 and badge in sent[0].buys[0].badge
    assert not any("reuse" in text.lower() for text in sent[0].buys[0].facts)
    assert len(result.assessments) == 1


def test_saved_pc_jobs_config_and_community_cannot_resurrect_tracking(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "channels", lambda **_: ())
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    config = tmp_path / "old-monitor.toml"
    config.write_text((ROOT / "config/monitor.toml").read_text() + '''
[[seed]]
kind = "newegg"
url = "https://www.newegg.com/p/3D5-000Z-002C6"
[[discovery]]
kind = "discover-cyberpowerpc"
url = "https://www.cyberpowerpc.com/gaming-pcs/prebuilt/"
[[catalog]]
kind = "ibuypower"
url = "https://www.ibuypower.com/gaming-pcs/prebuilt-gaming-pcs"
''')
    retired = ("hp", "newegg", "cyberpowerpc", "skytech", "ibuypower", "discover-newegg", "discover-hp")
    (runtime / "schedule.json").write_text(json.dumps({"jobs": {
        f"old-{kind}": {"kind":kind, "url":"https://www.newegg.com/p/3D5-000Z-002C6"}
        for kind in retired}}))
    mon = monitor.Monitor(config, tmp_path / "state", runtime, dry_run=False)
    assert not {job["kind"] for job in mon.jobs.values()} & set(retired)
    before = set(mon.jobs)
    key = next(k for k, job in mon.jobs.items() if job["kind"] == "slickdeals")
    pc = listing("Gaming PC RTX 5090 64GB DDR5 4TB SSD", 4000)
    peripheral = listing("USB-C dock with HDMI and Ethernet", 25, listing_id="dock")
    mon.process(key, Batch(listings=[pc, peripheral], discovered=[pc.url]))
    mon.recheck_starts()
    assert set(mon.jobs) == before
    assert mon.results[-1]["assessed"] == 0
    exported = mon.shopping.batches[key]["rows"]
    assert [row["title"] for row in exported] == [peripheral.title]
    mon.write_health()
    assert json.loads(mon.shopping.path.read_text())["capabilities"] == ["judgments", "watches-v3"]
    assert not list((tmp_path / "state").rglob("prebuilt-*"))


def test_active_cli_and_watchlist_have_no_machine_purchase_strategy():
    assert PLUGINS["hardware"] is PartsHardwarePlugin
    cfg = Config.load(ROOT / "config/hardware.toml", ROOT / "config/watchlist.toml")
    assert cfg.digest_at == cfg.push_at == "EXCEPTIONAL"
    assert all("gaming pc" not in query.lower() for query in cfg.search_queries)
    assert "zenbook_duo_2026_x9_388h" not in cfg.all_watched_parts()
    assert cfg.all_watched_parts()["rtx_3090"].quantity_wanted == 1
    assert {"monitor", "motherboard", "case"} <= INTERESTING_FLAIRS
    assert not {"prebuilt", "laptop"} & INTERESTING_FLAIRS


def test_manual_complete_pc_is_rejected_before_writing_and_mac_source_is_retired(tmp_path):
    plugin = PartsHardwarePlugin(ROOT / "config/hardware.toml", tmp_path)
    try:
        assert "apple-refurb" not in {source.name for source in plugin.sources}
        with pytest.raises(ValueError, match="complete machines are retired"):
            plugin.add_manual(url="https://example.invalid/pc", price=4000,
                              title="Gaming PC RTX 5090 128GB DDR5 4TB SSD", condition="new")
        assert not plugin.manual_path.exists()
    finally:
        plugin.close()


@pytest.mark.parametrize("opt_in", [False, True])
def test_community_bargain_keeps_assessment_but_never_notifies(tmp_path, opt_in):
    sent, result = execute(tmp_path, [listing()], include_target_notices=opt_in)
    assert not sent
    assert len(result.assessments) == 1 and result.assessments[0].verdict.name == "EXCEPTIONAL"


def test_inherited_card_target_requires_explicit_opt_in(tmp_path):
    row = verified_listing("NVIDIA GeForce RTX 5080 graphics card", 1400, key="rtx_5080")
    sent, result = execute(tmp_path, [row])
    assert result.assessments[0].target_override and not sent
    sent, _ = execute(tmp_path / "opt-in", [row], include_target_notices=True)
    assert len(sent) == 1


def test_exact_model_monitor_discount_is_standout_without_target_opt_in(tmp_path):
    sent, result = execute(tmp_path, [verified_listing('Alienware AW2725QF 27" 4K 180Hz IPS DisplayPort',
                                                    299.99, key="AW2725QF")])
    assert len(sent) == 1 and result.assessments[0].verdict.name == "STRONG"


@pytest.mark.parametrize("field,value", [
    ("shipping", None), ("shipping", -1), ("item_price", 849),
    ("available", False), ("stock", "unknown"), ("verified_price_watch", "rtx_5090"),
    ("availability_checked_at", "2020-01-01T00:00:00+00:00"),
])
def test_incomplete_exact_offer_cannot_notify_even_with_targets_enabled(tmp_path, field, value):
    row = verified_listing()
    row.extra["shopping"][field] = value
    sent, _ = execute(tmp_path, [row], include_target_notices=True)
    assert not sent


def test_missing_seller_cannot_notify(tmp_path):
    row = verified_listing()
    row.extra.pop("seller")
    sent, _ = execute(tmp_path, [row], include_target_notices=True)
    assert not sent



def test_email_digest_contains_only_verified_standout_deals(tmp_path):
    rows = [verified_listing(), listing(price=1400, listing_id="community-pass")]
    sent, result = execute(tmp_path, rows, channel_kind="email")
    assert len(result.assessments) == 2
    assert len(sent) == 1 and len(sent[0].buys) == 1 and not sent[0].others
    assert sent[0].buys[0].url == rows[0].url



def test_live_cli_clock_accepts_stock_verified_after_plugin_construction(tmp_path):
    plugin = PartsHardwarePlugin(ROOT / "config/hardware.toml", tmp_path)
    def fetch():
        row = verified_listing()
        row.extra["shopping"]["availability_checked_at"] = datetime.now(timezone.utc).isoformat()
        return FetchResult([row])
    plugin.sources = (SimpleNamespace(name="fixture", fetch=fetch),)
    sent = []
    result = run(plugin, AlertState(plugin.state_dir / "alerts.json", plugin.normalise_key),
                 replace(plugin.options, quiet_when_empty=True, preview=tmp_path / "preview.html"),
                 (Channel("fixture", "push", sent.append),))
    assert not result.problems and len(sent) == 1
