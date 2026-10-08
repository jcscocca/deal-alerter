from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from alerters.hardware.prebuilt import Coupon, Offer, OfferState, PrebuiltHistory, announced_start, exact_desktop, priority
from alerters.hardware.prebuilt_plugin import MonitorHardwarePlugin, community_offer, offer_listing
from alerters.hardware.retailers import canonical_product, parse_newegg, parse_hp, reviewed_coupon
from alerters.hardware.retail_http import Deferred, PublicClient, Robots, retry_after
from alerters.hardware.monitor import check_owner, failure_delay, health_problems, Monitor
from dealcore.locking import WriterLock
from dealcore.notify import Channel
from dealcore.run import run
from dealcore.state import AlertState
from dealcore.types import FetchResult, Listing

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 4, 17, tzinfo=timezone.utc)
URL = "https://www.newegg.com/p/3D5-000Z-002C6?Item=9SIA1HJKEB7401"


@pytest.fixture
def offer():
    return Offer("newegg", "TEST5090", "Skytech Gaming PC Desktop RTX 5090 32GB, 64GB RAM, 2TB SSD",
                 URL, "Skytech", "new", {"GPU": "RTX 5090 32GB", "CPU": "285K", "RAM": "64GB", "SSD": "2TB"},
                 4499, 0, "in_stock", True, NOW.isoformat())


def evaluate(tmp_path, offers, *, dry=False, fail=False, sent=None):
    sent = [] if sent is None else sent
    plugin = MonitorHardwarePlugin(ROOT / "config/hardware.toml", tmp_path, now=NOW)
    plugin.sources = (SimpleNamespace(name="fixture", fetch=lambda: FetchResult([offer_listing(o) for o in offers])),)
    state = AlertState(plugin.state_dir / "alerts.json", plugin.normalise_key)
    def deliver(report):
        if fail:
            raise RuntimeError("simulated transport failure")
        sent.append(report)
    options = replace(plugin.options, dry_run=dry, quiet_when_empty=True, preview=tmp_path / "preview.html")
    result = run(plugin, state, options, (Channel("ntfy", "push", deliver),), now=NOW)
    return result, sent


@pytest.mark.parametrize("price,expected", [(5000,3),(4500,3),(4499.99,4),(4000,4),(3999.99,5)])
def test_priority_boundaries(price, expected):
    assert priority(price) == expected


def test_eligible_coupon_total_includes_accessory_shipping_excludes_cashback(offer):
    coupon = Coupon("PC25", "Add required $39 accessory; enter PC25", 1250, True, ends_at="2026-10-05T00:00:00Z", required_accessories=39)
    pc = replace(offer, base_price=5000, shipping=20, coupon=coupon, cashback="10% possible")
    assert pc.total(NOW) == 3809
    assert replace(pc, coupon=replace(coupon, eligible=False)).total(NOW) == 5020
    assert replace(pc, coupon=replace(coupon, required_accessories=None)).total(NOW) == 5020
    assert replace(pc, shipping=None).total(NOW) is None
    assert pc.total(NOW + timedelta(days=2)) == 5020


def test_full_core_success_receipt_suppresses_and_failed_delivery_retries(tmp_path, offer):
    result, sent = evaluate(tmp_path, [offer], fail=True)
    assert result.problems and not sent
    result, sent = evaluate(tmp_path, [offer])
    assert not result.problems and len(sent) == 1
    assert sent[0].buys[0].priority == 4
    _, sent = evaluate(tmp_path, [offer])
    assert not sent
    _, sent = evaluate(tmp_path, [replace(offer, base_price=3999)])
    assert len(sent) == 1 and sent[0].buys[0].priority == 5


def test_stock_cycle_and_sale_status_generate_one_new_receipt(tmp_path, offer):
    evaluate(tmp_path, [offer])
    _, sent = evaluate(tmp_path, [replace(offer, stock="out_of_stock")])
    assert not sent
    _, sent = evaluate(tmp_path, [offer])
    assert len(sent) == 1 and "RESTOCK" in sent[0].buys[0].badge
    _, sent = evaluate(tmp_path, [offer])
    assert not sent
    evaluate(tmp_path, [replace(offer, stock="out_of_stock")])
    _, sent = evaluate(tmp_path, [offer])
    assert len(sent) == 1


def test_sold_out_card_is_saved_price_never_live_deal_or_announcement(tmp_path, offer):
    plugin = MonitorHardwarePlugin(ROOT / "config/hardware.toml", tmp_path, now=NOW)
    try:
        candidate = plugin.prepare(offer_listing(replace(offer, stock="out_of_stock")))
        assessment = plugin.judge(candidate, plugin.read_history(candidate))
        card = plugin.card(assessment)
    finally:
        plugin.close()
    assert not assessment.alertable
    assert card.badge.startswith("OUT OF STOCK · SAVED PRICE")
    assert "LIVE-DEAL" not in card.badge and "ANNOUNCEMENT" not in card.badge
    assert any("Price and stock checked: Oct 04, 2026 10:00 AM PDT" == fact for fact in card.facts)


def test_minor_price_changes_do_not_repeat_but_cumulative_change_does(tmp_path, offer):
    evaluate(tmp_path, [offer])
    assert not evaluate(tmp_path, [replace(offer, base_price=4498)])[1]
    assert not evaluate(tmp_path, [replace(offer, base_price=4480)])[1]
    assert len(evaluate(tmp_path, [replace(offer, base_price=4390)])[1]) == 1


def test_dry_run_leaves_hardware_state_and_receipts_unchanged(tmp_path, offer):
    evaluate(tmp_path, [offer])
    before = {p.relative_to(tmp_path): p.read_bytes() for p in (tmp_path / "hardware").rglob("*") if p.is_file()}
    result, sent = evaluate(tmp_path, [replace(offer, base_price=3900)], dry=True)
    after = {p.relative_to(tmp_path): p.read_bytes() for p in (tmp_path / "hardware").rglob("*") if p.is_file()}
    assert before == after and not sent and not result.problems
    assert "CONFIRMED OFFER" in (tmp_path / "preview.html").read_text(encoding="utf-8")


def test_pc_history_never_contaminates_bare_gpu_history_and_conditions_separate(tmp_path, offer):
    evaluate(tmp_path, [offer, replace(offer, condition="open_box"), replace(offer, condition="refurbished")])
    directory = tmp_path / "hardware/US"
    assert (directory / "prices.jsonl").read_text(encoding="utf-8") == ""
    rows = PrebuiltHistory(directory).rows
    assert len(rows) == 3
    assert {r["condition"] for r in rows} == {"new", "open_box", "refurbished"}
    evaluate(tmp_path, [offer])
    assert len(PrebuiltHistory(directory).rows) == 3


@pytest.mark.parametrize("changes", [{"confirmed":False},{"shipping":None},{"stock":"out_of_stock"},{"stock":"preorder"},{"condition":"unknown"},{"base_price":5000.01}])
def test_unconfirmed_or_over_target_cannot_push(tmp_path, offer, changes):
    assert not evaluate(tmp_path, [replace(offer, **changes)])[1]


def test_announcement_without_price_arrives_with_pacific_start_and_due_recheck(tmp_path):
    row = Listing("notice", "reddit/buildapcsales", "[Prebuilt] HP OMEN 45L RTX 5090 sale starts tomorrow 10 AM PT",
                  "https://www.reddit.com/r/buildapcsales/comments/example", NOW,
                  body="Purchase https://www.hp.com/us-en/shop/pdp/omen-example")
    pc = community_offer(row)
    assert pc and pc.base_price is None and pc.starts_at == "2026-10-05T17:00:00+00:00"
    result, sent = evaluate(tmp_path, [pc])
    assert not result.problems and len(sent) == 1
    assert "UNVERIFIED ANNOUNCEMENT" in sent[0].buys[0].badge
    assert "UPCOMING-SALE" in sent[0].buys[0].badge
    assert any("10:00 AM PDT" in fact for fact in sent[0].buys[0].facts)
    assert not PrebuiltHistory(tmp_path / "hardware/US").rows
    state = OfferState(tmp_path / "hardware/US")
    assert not state.due_announcements(NOW)
    assert state.due_announcements(NOW + timedelta(days=1, seconds=1))


@pytest.mark.parametrize("text,expected", [("2026-12-01 10 AM PT", "2026-12-01T18:00:00+00:00"), ("10/05 1 PM ET", "2026-10-05T17:00:00+00:00"), ("2026-11-01 1:30 AM PT",None),("sale at 10 AM",None),("2026-10-05T17:00:00Z","2026-10-05T17:00:00+00:00")])
def test_start_times_and_ambiguous_dst(text, expected):
    assert announced_start(text, NOW) == expected


def fixture():
    return json.loads((ROOT / "tests/fixtures/newegg_selected_5090.json").read_text(encoding="utf-8"))


def page(data):
    return '<html><script>window.__initialState__ = ' + json.dumps(data) + ';</script></html>'


def test_live_newegg_fixture_confirms_exact_selected_config():
    pc = parse_newegg(page(fixture()), URL, NOW)
    assert pc.confirmed and pc.specs["Selected GPU"] == "5090" and pc.condition == "new"
    assert pc.total(NOW) == 7599.99


def test_direct_newegg_abs_inventory_uses_the_primary_sold_by_label():
    data = json.loads((ROOT / "tests/fixtures/newegg_selected_abs.json").read_text(encoding="utf-8"))
    body = page(data) + data["primary_seller_html"]
    url = "https://www.newegg.com/p/83-360-990C?Item=83-360-990C"
    pc = parse_newegg(body, url, NOW)
    assert pc.seller == "Newegg" and pc.confirmed
    assert pc.condition == "refurbished" and pc.stock == "out_of_stock"
    assert pc.total(NOW) == 4999.99
    assert pc.specs["GPU/VGA Type"] == "GeForce RTX 5090"


@pytest.mark.parametrize("label", ["Shipped by Newegg", "Sold by Other Seller", "",
                                  "Sold by Newegg Marketplace"])
def test_newegg_fulfilment_or_ambiguous_seller_does_not_establish_trust(label):
    data = fixture()
    data["ItemDetail"]["Seller"] = {"SellerId": "", "SellerName": None}
    body = page(data) + f'<div class="product-seller-box"><div class="product-seller-sold-by">{label}</div></div>'
    assert not parse_newegg(body, URL, NOW).confirmed


def test_seller_label_cannot_override_marketplace_id_or_conflicting_primary_labels():
    data = fixture()
    data["ItemDetail"]["Seller"] = {"SellerId": "OTHER", "SellerName": None}
    label = '<div class="product-seller-box"><div class="product-seller-sold-by">Sold by Newegg</div></div>'
    assert not parse_newegg(page(data) + label, URL, NOW).confirmed
    data["ItemDetail"]["Seller"]["SellerId"] = ""
    assert not parse_newegg(page(data) + label + label, URL, NOW).confirmed


def test_wrong_selected_gpu_rejected_even_when_page_mentions_5090():
    data = fixture()
    data["PropertyCollection"]["PropertyGroups"][1]["SelectedProperty"]["Description"] = "5080"
    with pytest.raises(Deferred, match="Selected GPU"):
        parse_newegg(page(data), URL, NOW)


def test_seller_switch_and_marketplace_impostor_fail_closed():
    data = fixture()
    data["ItemDetail"]["Item"] = "DIFFERENT"
    with pytest.raises(Deferred, match="selected seller"):
        parse_newegg(page(data), URL, NOW)
    data = fixture()
    data["ItemDetail"]["Seller"]["SellerId"] = "IMPOSTOR"
    assert not parse_newegg(page(data), URL, NOW).confirmed


@pytest.mark.parametrize("title", ["RTX 5090 laptop", "OMEN desktop up to RTX 5090", "Skytech gaming PC RTX 5090 D", "RTX 5090 graphics card"])
def test_only_desktop_included_gpu(title):
    assert not exact_desktop(title)


def hp_page(price=4799, *, aggregate=False, title="OMEN 45L Gaming Desktop RTX 5090 32GB, 64GB RAM, 2TB SSD", sku="B91WJAA#ABA"):
    product = {"@type":"Product", "name":title, "sku":sku, "description":"Intel Ultra 9 285K; 64GB DDR5; 2TB SSD; RTX 5090 32GB",
               "offers":{"@type":"AggregateOffer" if aggregate else "Offer", "price":price, "priceCurrency":"USD", "availability":"https://schema.org/InStock", "itemCondition":"https://schema.org/NewCondition"}}
    return f'<h1>{title}</h1><script type="application/ld+json">{json.dumps(product)}</script>FREE Storewide Shipping <h2>Recommended accessories</h2>25% off monitor with HPDEAL25'


def test_hp_fixed_sku_and_accessory_coupon_does_not_discount_pc():
    pc = parse_hp(hp_page(), "https://www.hp.com/us-en/shop/pdp/omen-example", NOW)
    assert pc.confirmed and pc.total(NOW) == 4799 and pc.coupon is None


@pytest.mark.parametrize("kwargs", [{"price":0},{"aggregate":True},{"title":"OMEN 45L Gaming Desktop up to RTX 5090"},{"sku":"CF1E5AV_1"}])
def test_hp_placeholder_family_or_configurable_price_rejected(kwargs):
    with pytest.raises(Deferred):
        parse_hp(hp_page(**kwargs), "https://www.hp.com/us-en/shop/pdp/omen-example", NOW)


def test_rate_limit_http_date_and_exponential_backoff():
    assert retry_after("Sun, 04 Oct 2026 18:00:00 GMT", NOW) == 3600
    assert failure_delay(6,120,7200) == 7200
    assert failure_delay(1,120) == 240


def test_robots_wildcards_specific_allow_and_delay():
    robots = Robots("User-agent: *\nDisallow: /*api/\nDisallow: /private*\nAllow: /private/public\nCrawl-delay: 130")
    assert not robots.allows("https://www.hp.com/us-en/shop/api/prices")
    assert robots.allows("https://www.hp.com/private/public")
    assert robots.delay() == 130


def test_http_429_blocks_host_without_immediate_retry(monkeypatch):
    clock = [1000.0]
    client = PublicClient(clock=lambda:clock[0], sleeper=lambda n:clock.__setitem__(0,clock[0]+n))
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        if url.endswith("robots.txt"):
            return SimpleNamespace(status_code=200, text="User-agent: *\nAllow: /", headers={}, content=b"")
        return SimpleNamespace(status_code=429, headers={"Retry-After":"7200"})
    monkeypatch.setattr("requests.get", get)
    with pytest.raises(Deferred) as error:
        client.get(URL)
    assert error.value.seconds == 7200
    with pytest.raises(Deferred):
        client.get(URL)
    assert len(calls) == 2


def test_conditional_304_reuses_only_confirmed_cached_representation(monkeypatch):
    client = PublicClient(sleeper=lambda _:None)
    count = [0]
    def get(url, **kwargs):
        if url.endswith("robots.txt"):
            return SimpleNamespace(status_code=200,text="User-agent: *\nAllow: /",headers={},content=b"")
        count[0] += 1
        if count[0] == 1:
            return SimpleNamespace(status_code=200,text="PRODUCT",content=b"PRODUCT",headers={"ETag":"abc"})
        assert kwargs["headers"]["If-None-Match"] == "abc"
        return SimpleNamespace(status_code=304,headers={})
    monkeypatch.setattr("requests.get", get)
    assert client.get(URL) == client.get(URL) == "PRODUCT"


def test_network_disconnect_recovers_after_backoff_without_losing_cached_policy(monkeypatch):
    import requests
    clock = [1000.0]
    client = PublicClient(clock=lambda:clock[0], sleeper=lambda n:clock.__setitem__(0,clock[0]+n))
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        if url.endswith("robots.txt"):
            return SimpleNamespace(status_code=200,text="User-agent: *\nAllow: /",headers={},content=b"")
        if len(calls) == 2:
            raise requests.Timeout("simulated network loss")
        return SimpleNamespace(status_code=200,text="RECOVERED",headers={},content=b"RECOVERED")
    monkeypatch.setattr(requests,"get",get)
    with pytest.raises(Deferred, match="Network request failed") as error:
        client.get(URL)
    with pytest.raises(Deferred, match="backing off"):
        client.get(URL)
    assert len(calls) == 2
    clock[0] += error.value.seconds + 1
    assert client.get(URL) == "RECOVERED"
    assert len(calls) == 3


@pytest.mark.parametrize("url", ["https://127.0.0.1/p/a","http://www.newegg.com/p/a","https://user:password@www.hp.com/us-en/shop/pdp/x","https://www.newegg.com.evil.test/p/x"])
def test_feed_urls_cannot_reach_arbitrary_hosts(url):
    with pytest.raises(ValueError):
        canonical_product(url)


def test_os_lock_prevents_second_writer_and_releases(tmp_path):
    with WriterLock(tmp_path / "writer.lock"):
        with pytest.raises(ValueError, match="Another"):
            with WriterLock(tmp_path / "writer.lock"):
                pass
    with WriterLock(tmp_path / "writer.lock"):
        pass


def test_owner_and_stale_detection(tmp_path):
    with pytest.raises(ValueError, match="approved"):
        check_owner(tmp_path, tmp_path / "state")
    assert health_problems({"heartbeat":900,"started":0,"jobs":{"hp":{"interval":120,"last_success":10,"error":""}}},1000) == ["Monitor heartbeat is stale", "hp: checks stale (no result)"]


def test_corrupt_offer_state_fails_loudly(tmp_path):
    (tmp_path / "prebuilt-offers.json").write_text("broken")
    with pytest.raises(ValueError):
        OfferState(tmp_path)


def test_announcement_title_edit_does_not_change_identity_or_repeat(tmp_path):
    row = Listing("notice", "reddit/buildapcsales", "HP OMEN 45L RTX 5090 prebuilt tomorrow 10 AM PT $4499",
                  URL, NOW)
    first = community_offer(row)
    edited = community_offer(replace(row, title=row.title + " - updated details"))
    assert first.key == edited.key
    evaluate(tmp_path, [first])
    assert not evaluate(tmp_path, [edited])[1]
    changed = community_offer(replace(row, title=row.title.replace("$4499", "$3999")))
    assert evaluate(tmp_path, [changed])[1]


def test_original_same_condition_undercut_promotion_is_reused(tmp_path, offer):
    from alerters.hardware.native.catalog import PARTS
    from alerters.hardware.native.verdict import Assessment as Detail, Verdict
    from dealcore.types import Assessment
    plugin = MonitorHardwarePlugin(ROOT / "config/hardware.toml", tmp_path, now=NOW)
    try:
        pc = replace(offer, base_price=5500)
        candidate = plugin.prepare(offer_listing(pc))
        assessment = plugin.judge(candidate, plugin.read_history(candidate))
        part = next(p for p in PARTS if p.key == "rtx_5090")
        loose = Detail("loose", "test", part, "RTX 5090", "https://example.invalid", 6000, 1, "new", NOW,
                       Verdict.GOOD, "", "", 187.5)
        benchmark = Assessment("test:loose", 6000, Verdict.GOOD, loose, loggable=True)
        assert plugin.promote([assessment, benchmark])[0].verdict == Verdict.EXCEPTIONAL
        assert plugin.promote([assessment, replace(benchmark, detail=replace(loose, condition="used"))])[0].verdict == Verdict.GOOD
        notice = replace(pc, announcement=True, confirmed=False, base_price=None, shipping=None)
        candidate = plugin.prepare(offer_listing(notice))
        unpriced = plugin.judge(candidate, plugin.read_history(candidate))
        assert not plugin.arbitrage([unpriced, benchmark])
    finally:
        plugin.close()


def test_slow_feed_does_not_hold_up_retailer_results(tmp_path, monkeypatch):
    import threading
    from alerters.hardware.monitor_sources import Batch
    from alerters.hardware import monitor as module
    mon = Monitor(ROOT / "config/monitor.toml", tmp_path / "state", tmp_path / "runtime", dry_run=True)
    mon.jobs.clear()
    mon.add_job("newegg", 120, URL)
    mon.add_job("reddit", 300)
    release_feed = threading.Event()
    processed = []
    def fetch(job, *_):
        if job["kind"] == "reddit":
            assert release_feed.wait(5), "retailer result was held behind a slow feed"
        return Batch()
    def process(key, batch):
        processed.append(key)
        if key.startswith("newegg"):
            release_feed.set()
    monkeypatch.setattr(module, "fetch_job", fetch)
    monkeypatch.setattr(mon, "process", process)
    assert mon.loop(once=True) == 0
    assert processed[0].startswith("newegg")


def test_restart_preserves_server_backoff(tmp_path, monkeypatch):
    from alerters.hardware import monitor as module
    monkeypatch.setattr(module, "channels", lambda **_:())
    runtime = tmp_path / "runtime"
    mon = Monitor(ROOT / "config/monitor.toml", tmp_path / "state", runtime, dry_run=False)
    mon.client.host("www.newegg.com")["blocked_until"] = 9999999999
    mon.jobs[next(iter(mon.jobs))]["next"] = 9999999999
    mon.write_health()
    restarted = Monitor(ROOT / "config/monitor.toml", tmp_path / "state", runtime, dry_run=False)
    assert restarted.client.host("www.newegg.com")["blocked_until"] == 9999999999
    assert restarted.jobs[next(iter(mon.jobs))]["next"] == 9999999999


def test_monitor_exports_real_decisions_and_watch_pause_preserves_receipts(tmp_path, monkeypatch, offer):
    from alerters.hardware import monitor as module
    from alerters.hardware.monitor_sources import Batch
    from alerters.hardware.shopping_controls import defaults
    from alerters.hardware.shopping_export import ShoppingExport
    from alerters.techscout.integration import activity
    sent = []
    monkeypatch.setattr(module, "channels", lambda **_: (Channel("ntfy", "push", sent.append),))
    runtime = tmp_path / "runtime"
    mon = Monitor(ROOT / "config/monitor.toml", tmp_path / "state", runtime, dry_run=False)
    key = mon.add_product(URL)
    mon.process(key, Batch(offers=[offer]))
    row = mon.shopping.batches[key]["rows"][0]
    assert len(sent) == 1 and row["judgment"]["eligible"]
    assert row["judgment"]["decisions"][0]["status"] == "sent"
    assert len(activity(runtime)) == 1
    first_seen = row["first_seen"]
    mon.write_health()
    mon.shopping = ShoppingExport(runtime)
    mon.process(key, Batch(offers=[offer]))
    row = mon.shopping.batches[key]["rows"][0]
    assert row["first_seen"] == first_seen
    assert row["judgment"]["decisions"][0]["status"] == "unchanged"
    (runtime / "ui").mkdir()
    mon.controls_path.write_text(json.dumps({**defaults(), "mode": "paused"}))
    mon.process(key, Batch(offers=[replace(offer, base_price=3500)]))
    row = mon.shopping.batches[key]["rows"][0]
    assert row["judgment"]["decisions"][0]["status"] == "watch-filtered"
    assert len(sent) == 1 and len(activity(runtime)) == 1
    assert row["judgment"]["deliveries"][0]["price"] == offer.base_price


def test_start_recheck_preserves_backoff(tmp_path):
    from alerters.hardware.monitor import job_id
    from alerters.hardware.retailers import canonical_product
    mon = Monitor(ROOT / "config/monitor.toml", tmp_path / "state", tmp_path / "runtime", dry_run=True)
    now = datetime.now(timezone.utc)
    announcement = Offer("community", "start", "HP OMEN desktop RTX 5090", URL, "unknown", "unknown", {},
                         None,None,"unknown",False,now.isoformat(),announcement=True,
                         starts_at=(now-timedelta(seconds=2)).isoformat())
    store = OfferState(tmp_path / "state/hardware/US")
    store.observe(announcement, now)
    store.save()
    key = job_id("newegg", canonical_product(URL))
    mon.jobs[key].update(failures=1,next=9999999999)
    mon.recheck_starts()
    assert mon.jobs[key]["next"] == 9999999999
    mon.jobs[key].update(failures=0)
    mon.recheck_starts()
    assert mon.jobs[key]["next"] < 9999999999


def test_watchdog_restarts_even_when_ntfy_is_offline(tmp_path, monkeypatch):
    from alerters.hardware import monitor as module
    calls = []
    monkeypatch.setattr(module, "check_owner", lambda *_:None)
    monkeypatch.setattr("subprocess.run", lambda argv,**kwargs:calls.append(argv))
    def fail(_):
        raise RuntimeError("offline")
    monkeypatch.setattr(module, "channels", lambda **_:(Channel("ntfy","push",fail),))
    with pytest.raises(RuntimeError):
        module.watchdog(tmp_path,dry_run=False)
    assert [c[1] for c in calls] == ["/End","/Run"]
    assert not (tmp_path / "watchdog-receipt.json").exists()


@pytest.mark.parametrize("final", [4900,4800])
def test_newegg_coupon_never_double_subtracts_final_price(final):
    data = fixture()
    data["ItemDetail"].update(UnitCost=5000, InstantRebateAmount=100, FinalPrice=final, PcodeDiscount=100,
                              PromotionInfo={"PCode":"SAVE100", "DisplayPromotionText":"Extra $100 off with code SAVE100"})
    offer = parse_newegg(page(data), URL, NOW)
    assert offer.total(NOW) == 4800
    data["ItemDetail"]["PromotionInfo"]["DisplayPromotionText"] = "Cardholder discount"
    assert parse_newegg(page(data), URL, NOW).total(NOW) == 4900


def test_official_future_offer_is_upcoming_then_live(tmp_path, offer):
    future = replace(offer, starts_at=(NOW+timedelta(hours=1)).isoformat())
    result, sent = evaluate(tmp_path, [future])
    assert sent and "UPCOMING-SALE" in sent[0].buys[0].badge
    assert sent[0].buys[0].priority == 3
    assert not PrebuiltHistory(tmp_path / "hardware/US").rows
    _, sent = evaluate(tmp_path, [replace(future, starts_at=(NOW-timedelta(hours=1)).isoformat())])
    assert sent and "LIVE-DEAL" in sent[0].buys[0].badge


def test_watchdog_retries_failed_transport_without_repeating_success(tmp_path, monkeypatch):
    from alerters.hardware import monitor as module
    monkeypatch.setattr(module,"check_owner",lambda *_:None)
    status={"heartbeat":__import__('time').time(),"jobs":{},"problems":["Coverage degraded"]}
    (tmp_path/'health.json').write_text(json.dumps(status))
    success=[]
    failed=[]
    def fail(_):
        raise RuntimeError('offline')
    monkeypatch.setattr(module,'channels',lambda **_:(Channel('ntfy','push',success.append),Channel('discord','push',fail)))
    with pytest.raises(RuntimeError):
        module.watchdog(tmp_path,dry_run=False)
    monkeypatch.setattr(module,'channels',lambda **_:(Channel('ntfy','push',success.append),Channel('discord','push',failed.append)))
    module.watchdog(tmp_path,dry_run=False)
    assert len(success)==len(failed)==1


def test_legacy_rate_limit_stops_query_loop_and_preserves_retry_after(monkeypatch):
    import requests
    from dealcore.types import SourceError
    from alerters.hardware.monitor_sources import fetch_job
    calls=[]
    class Legacy:
        name='ebay'
        session=requests.Session()
        def fetch(self):
            for query in range(22):
                try:
                    self.session.get('https://api.ebay.com/example')
                except SourceError:
                    continue
            return []
    monkeypatch.setattr('alerters.hardware.native.sources.build_sources',lambda _: [Legacy()])
    monkeypatch.setattr('time.sleep',lambda _:None)
    def limited(*args,**kwargs):
        calls.append(1)
        return SimpleNamespace(status_code=429,headers={'Retry-After':'7200'})
    monkeypatch.setattr(requests.Session,'request',limited)
    with pytest.raises(Deferred) as error:
        fetch_job({'kind':'legacy','source':'ebay','config':str(ROOT/'config/hardware.toml')},PublicClient(),[])
    assert error.value.seconds==7200 and len(calls)==1
