"""Public page fragments captured October 7, 2026; no live network in tests."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from alerters.hardware.builders import (builder_product, discover_cyberpowerpc, discover_skytech,
                                       parse_cyberpowerpc, parse_skytech, parse_ibuypower_catalog)
from alerters.hardware.monitor import Monitor
from alerters.hardware.monitor_sources import fetch_job
from alerters.hardware.prebuilt import PrebuiltHistory
from alerters.hardware.retail_http import Deferred
from alerters.hardware.prebuilt_specs import build_specs
from alerters.techscout.prebuilt_value import history_view

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).with_name("fixtures")
NOW = datetime(2026, 10, 8, 3, tzinfo=timezone.utc)
CP_URL = "https://www.cyberpowerpc.com/system/Prebuilt-PC-GML-99752"


def cp_page():
    return (FIXTURES / "cyberpowerpc_prebuilt.html").read_text(encoding="utf-8")


def sky_fixture():
    return json.loads((FIXTURES / "skytech_prebuilt.json").read_text(encoding="utf-8"))


def sky_page(fixture):
    # Nuxt serializes values by index. Include an unrelated product and the
    # null error entry for the same request to exercise exact-SKU selection.
    data = []
    def encode(value):
        index = len(data)
        data.append(None)
        if isinstance(value, dict):
            value = {k: encode(v) for k,v in value.items()}
        elif isinstance(value, list):
            value = [encode(v) for v in value]
        data[index] = value
        return index
    key = "api:/products/" + fixture["state"]["sku"] + "?source=Generally|q:|b:"
    encode({"data": {key: fixture["state"], "api:/products/OTHER?source=Generally": {"sku": "OTHER", "price": 1}},
            "errors": {key: None}})
    return (f'<script type="application/ld+json">{json.dumps({"@graph": [fixture["product"]]})}</script>'
            f'<script id="__NUXT_DATA__" type="application/json">{json.dumps(data)}</script>' + fixture["panel"])


def ibp_fixture():
    return json.loads((FIXTURES / "ibuypower_catalog.json").read_text(encoding="utf-8"))


def ibp_page(fixture):
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps({"props": {"pageProps": fixture}})}</script>'


def test_cyberpower_selected_offer_has_exact_specs_and_landed_total():
    offer = parse_cyberpowerpc(cp_page(), CP_URL, NOW)
    assert offer.stock == "in_stock" and offer.confirmed and offer.total(NOW) == 3109
    assert offer.sku == "PBET99752" and offer.seller == "CyberPowerPC" and offer.condition == "new"
    build = build_specs(offer.title, offer.specs, offer.condition)
    assert build["core"] == {"gpu": "5080", "cpu": "9850X3D", "ram_gb": 32, "ram_type": "DDR5", "ssd_gb": 2000, "condition": "new"}
    assert not build["issues"]


@pytest.mark.parametrize("label,stock", [("Out of Stock", "out_of_stock"), ("Pre-order", "preorder"),
                                        ("Special order", "preorder"), ("Check availability", "unknown")])
def test_cyberpower_cart_button_alone_cannot_confirm_stock(label, stock):
    page = cp_page().replace("In Stock", label)
    offer = parse_cyberpowerpc(page, CP_URL, NOW)
    assert offer.stock == stock and offer.sale_status(NOW) == "unavailable"


def test_cyberpower_product_price_and_sku_must_agree():
    page = cp_page().replace('name="fp" type="hidden" value="3109"', 'name="fp" type="hidden" value="1"')
    assert page != cp_page()
    with pytest.raises(Deferred, match="price disagrees"):
        parse_cyberpowerpc(page, CP_URL, NOW)
    with pytest.raises(Deferred, match="selected product"):
        parse_cyberpowerpc(cp_page(), CP_URL.replace("99752", "11111"), NOW)
    soup = BeautifulSoup(cp_page(), "html.parser")
    soup.select_one('input[name="code"]')["value"] = "OTHER"
    with pytest.raises(Deferred, match="configuration mismatch"):
        parse_cyberpowerpc(str(soup), CP_URL, NOW)


def test_cyberpower_recommendations_cannot_supply_selected_gpu_or_price():
    soup = BeautifulSoup(cp_page(), "html.parser")
    for node in soup.select('[data-summary-sec="VIDEO"]'):
        node.decompose()
    soup.append(BeautifulSoup('<aside>RTX 5090 Gaming PC $1 In Stock</aside>', "html.parser"))
    assert parse_cyberpowerpc(str(soup), CP_URL, NOW) is None
    soup = BeautifulSoup(cp_page(), "html.parser")
    soup.select_one('[data-summary-sec="VIDEO"] [data-type="sumamry-sec-val"]').string = "RTX 5090"
    with pytest.raises(Deferred, match="specifications disagree"):
        parse_cyberpowerpc(str(soup), CP_URL, NOW)


def test_cyberpower_discovery_only_uses_fixed_prebuilt_cards():
    body = '''<div class="system" data-system="X"><p class="system__spec">GeForce RTX 5080</p>
      <a href="/system/Prebuilt-PC-GML-99752">Shop</a><a href="/system/Prebuilt-PC-GML-99752">Details</a></div>
      <div class="system" data-system="Y"><p class="system__spec">RTX 5070</p><a href="/system/Prebuilt-PC-X">Shop</a></div>
      <a href="/system/Custom-PC-RTX-5090">RTX 5090</a>'''
    assert discover_cyberpowerpc(body) == [CP_URL]
    with pytest.raises(Deferred):
        discover_cyberpowerpc("<html>Challenge</html>")


def test_skytech_conflicting_real_stock_signals_do_not_create_history(tmp_path):
    f = sky_fixture()
    offer = parse_skytech(sky_page(f), f["url"], NOW)
    assert offer.stock == "unknown" and not offer.confirmed
    assert offer.base_price == 8999.99 and "conflicting" in offer.evidence
    history = PrebuiltHistory(tmp_path)
    history.record(offer, NOW)
    assert not history.rows and history.evidence(offer, NOW)["observed_days"] == 0


def test_skytech_positive_selected_inventory_requires_both_signals_and_button():
    f = sky_fixture()
    f["state"]["quantity_available"] = 3
    offer = parse_skytech(sky_page(f), f["url"], NOW)
    assert offer.confirmed and offer.stock == "in_stock" and offer.shipping == 0
    assert build_specs(offer.title, offer.specs, offer.condition)["key"]
    f["panel"] = f["panel"].replace("<button>", "<button disabled>")
    assert not parse_skytech(sky_page(f), f["url"], NOW).confirmed


@pytest.mark.parametrize("change", ["sku", "price", "options", "published", "state"])
def test_skytech_conflicting_or_configurable_product_fails_closed(change):
    f = sky_fixture()
    if change == "sku":
        f["product"]["sku"] = "ST-OTHER"
    elif change == "price":
        f["state"]["price"] = 1
    elif change == "options":
        f["state"]["product_options"]["gpu"] = [{"name": "RTX 5080", "price": 0}]
    elif change == "published":
        f["state"]["published"] = False
    elif change == "state":
        f["state"]["sku"] = "OTHER"
    with pytest.raises(Deferred):
        parse_skytech(sky_page(f), f["url"], NOW)


def test_skytech_sold_out_overrides_schema_and_recommendations():
    f = sky_fixture()
    f["state"]["in_stock"] = False
    f["panel"] += '<section aria-labelledby="suggested-items-heading">In Stock RTX 5080</section>'
    offer = parse_skytech(sky_page(f), f["url"], NOW)
    assert offer.stock == "out_of_stock" and offer.sale_status(NOW) == "unavailable"


def test_skytech_sitemap_uses_only_exact_gpu_skus():
    url = sky_fixture()["url"]
    body = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(
        '<url><loc>' + u + '</loc></url>' for u in (url, url, url.replace("5090", "5070"), url.replace("skytechgaming.com", "evil.test"), "https://skytechgaming.com/prebuilt-gaming-pc/prism-5")) + '</urlset>'
    assert discover_skytech(body) == [url]
    with pytest.raises(Deferred):
        discover_skytech('<!DOCTYPE urlset><urlset/>')


@pytest.mark.parametrize("url", [CP_URL + "?gpu=5090", CP_URL.replace("Prebuilt-PC", "Custom-PC"),
                                CP_URL.replace("www.cyberpowerpc.com", "evil.test"),
                                "https://skytechgaming.com/prebuilt-gaming-pc/prism-5",
                                "https://www.ibuypower.com/store/custom-pc"])
def test_builder_urls_reject_families_and_configuration_selectors(url):
    with pytest.raises(ValueError):
        builder_product(url)


def test_ibuypower_catalog_never_confirms_purchasable_inventory(tmp_path):
    offers = parse_ibuypower_catalog(ibp_page(ibp_fixture()), NOW)
    assert len(offers) == 2
    assert {o.stock for o in offers} == {"unknown", "out_of_stock"}
    history = PrebuiltHistory(tmp_path)
    for offer in offers:
        assert not offer.confirmed and offer.total(NOW) is None and offer.condition == "unknown"
        history.record(offer, NOW)
    assert not history.rows
    f = ibp_fixture()
    f["models"][0]["FullContent"]["Prebuild"] = False
    assert len(parse_ibuypower_catalog(ibp_page(f), NOW)) == 1


def test_ibuypower_conflicting_catalog_rows_are_not_silently_overwritten():
    f = ibp_fixture()
    duplicate = deepcopy(f["models"][0])
    duplicate["FullContent"]["Price"] = 1
    f["models"].append(duplicate)
    with pytest.raises(Deferred, match="conflicting"):
        parse_ibuypower_catalog(ibp_page(f), NOW)


def test_new_source_jobs_preserve_config_limits_and_restart(tmp_path, monkeypatch):
    from alerters.hardware import monitor as module
    monkeypatch.setattr(module, "channels", lambda **_: ())
    mon = Monitor(ROOT / "config/monitor.toml", tmp_path / "state", tmp_path / "runtime", dry_run=False)
    key = mon.add_product(CP_URL)
    mon.jobs[key]["next"] = 9999999999
    mon.jobs[key]["error"] = "Backoff"
    mon.jobs[key].update(last_fetch_success=1234, last_error_at=1500, listing_notes=["Unverified shipping"])
    mon.client.host("www.cyberpowerpc.com")["blocked_until"] = 9999999999
    mon.write_health()
    again = Monitor(ROOT / "config/monitor.toml", tmp_path / "state", tmp_path / "runtime", dry_run=False)
    assert again.jobs[key]["next"] == 9999999999 and again.jobs[key]["interval"] >= 600
    assert again.jobs[key]["last_fetch_success"] == 1234 and again.jobs[key]["last_error_at"] == 1500
    assert again.jobs[key]["listing_notes"] == ["Unverified shipping"]
    assert again.client.host("www.cyberpowerpc.com")["blocked_until"] == 9999999999
    assert any(j["kind"] == "ibuypower" and j["limit"] == 48 for j in again.jobs.values())
    assert any(j["kind"] == "discover-skytech" and j["interval"] >= 21600 for j in again.jobs.values())
    assert mon.add_product("https://www.ibuypower.com/store/rdy-y50-r02") is None


def test_unverified_offer_is_a_successful_check_without_inventory_or_deal_promotion(tmp_path, monkeypatch):
    from alerters.hardware import monitor as module
    from alerters.hardware.monitor_sources import Batch
    from dealcore.notify import Channel
    f = sky_fixture()
    f["state"]["quantity_available"] = 0
    offer = parse_skytech(sky_page(f), f["url"], NOW)
    assert not offer.confirmed and offer.stock == "unknown"
    sent = []
    monkeypatch.setattr(module, "channels", lambda **_: (Channel("ntfy", "push", sent.append),))
    mon = Monitor(ROOT / "config/monitor.toml", tmp_path / "state", tmp_path / "runtime", dry_run=False)
    mon.jobs.clear()
    key = mon.add_product(offer.url)
    monkeypatch.setattr(module, "fetch_job", lambda *_: Batch(offers=[offer]))
    assert mon.loop(once=True) == 0
    job = mon.jobs[key]
    assert job["last_success"] > 0 and job["last_fetch_success"] > 0
    assert job["error"] == "" and job["failures"] == 0
    assert job["listing_notes"] == [module.LISTING_UNVERIFIED]
    assert not sent
    raw = mon.shopping.batches[key]["rows"][0]
    assert raw["offer"]["confirmed"] is False and raw["offer"]["stock"] == "unknown"
    assert raw["judgment"]["eligible"] is False


def test_fetch_and_dashboard_include_new_sources_without_promoting_catalog_quotes(tmp_path, monkeypatch):
    from alerters.hardware import monitor as module
    monkeypatch.setattr(module, "channels", lambda **_: ())
    class Client:
        def get(self, url):
            return cp_page() if url == CP_URL else ibp_page(ibp_fixture())
    cp = fetch_job({"kind": "cyberpowerpc", "url": CP_URL}, Client(), [])
    ibp = fetch_job({"kind": "ibuypower", "url": "https://www.ibuypower.com/gaming-pcs/prebuilt-gaming-pcs", "limit": 1}, Client(), [])
    assert len(ibp.offers) == 1 and any("cap reached" in n for n in ibp.notes)
    runtime = tmp_path / "runtime"
    mon = Monitor(ROOT / "config/monitor.toml", tmp_path / "state", runtime, dry_run=True)
    key = mon.add_product(CP_URL)
    mon.process(key, cp)
    ibp_key = next(k for k,j in mon.jobs.items() if j["kind"] == "ibuypower")
    mon.process(ibp_key, ibp)
    for k in (key, ibp_key):
        mon.jobs[k]["last_success"] = datetime.now(timezone.utc).timestamp()
    mon.write_health()
    # Dry-run exports intentionally aren't accepted as live shopping evidence.
    from alerters.techscout.monitor_bridge import public_row
    from alerters.hardware.desktop_profile import DesktopProfile, DEFAULT_PROFILE
    profile = DesktopProfile(DEFAULT_PROFILE)
    ts = datetime.now(timezone.utc).timestamp()
    for source,k in (("cyberpowerpc",key),("ibuypower",ibp_key)):
        raw = mon.shopping.batches[k]["rows"][0]
        row = public_row(raw, source, raw["offer"]["observed_at"], ts+600, [], ts, profile)
        assert row["source"] == source
        if source == "ibuypower":
            assert not row["available"] and row["reasons"] and row["total"] is None
        else:
            assert row["available"] and row["total"] == 3109
            assert history_view(row["price_history"], row, ts)["tracked"]
