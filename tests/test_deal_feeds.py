from datetime import datetime, timezone
import json

import pytest
import requests

from alerters.techscout.deal_feeds import DealFeeds, FeedClient, SOURCES, parse_feed
from alerters.techscout.deal_overlap import amazon_asin, combine_leads
from alerters.techscout.dashboard import snapshot

NOW = datetime(2026, 10, 7, 3, tzinfo=timezone.utc).timestamp()
ASIN = "B012345678"


def feed(title="Samsung 990 PRO 2TB SSD for $149", description="Amazon offers this SSD with a coupon.", extra="", link=None):
    return f'''<rss xmlns:dn="https://www.dealnews.com/ns/rss/1.0.htm"><channel><item>
        <title>{title}</title><description><![CDATA[{description}]]></description>
        <link>{link or "https://www.dealnews.com/products/Samsung/123.html?iref=rss"}</link>
        <pubDate>Wed, 07 Oct 2026 02:50:00 +0000</pubDate>{extra}
        </item></channel></rss>'''.encode()


def report(source="dealnews", **changes):
    row = parse_feed(feed(), "dealnews", NOW)[0]
    row.update(source=source, retailer=SOURCES[source]["label"], id=source+":"+"a"*24,
               url="https://"+SOURCES[source]["host"]+"/example")
    row.update(changes)
    return row


def test_exact_asin_combines_titles_with_all_quotes_and_original_links():
    a = report(asin=ASIN)
    b = report("bensbargains", asin=ASIN, title="Samsung 990 PRO 2TB PCIe NVMe SSD", price=139, terms=["Prime required"])
    cards = combine_leads([a, b])
    assert len(cards) == 1 and cards[0]["reported_prices"] == [139, 149]
    assert cards[0]["price"] is None and cards[0]["total"] is None and not cards[0]["available"]
    assert cards[0]["sources"] == ["bensbargains", "dealnews"]
    assert {r["url"] for r in cards[0]["reports"]} == {a["url"], b["url"]}
    assert any(r["terms"] == ["Prime required"] for r in cards[0]["reports"])


def test_exact_names_match_price_suffixes_and_keep_publisher_content():
    a = report()
    b = report("bensbargains", title="Samsung 990 PRO 2TB SSD $139 at Amazon", price=139)
    card = combine_leads([a,b])[0]
    assert len(card["reports"]) == 2 and "Exact product name" in card["match_basis"]
    assert card["reports"][0]["description"] == a["description"]


@pytest.mark.parametrize("changes", [
    {"title":"Samsung 990 PRO 4TB SSD for $149"},
    {"title":"Samsung 990 PRO 2TB SSD with heatsink for $149"},
    {"title":"Samsung 990 PRO 2TB SSD refurbished for $149"},
    {"merchant":"Walmart"}, {"merchant":None}, {"asin":"B087654321"},
])
def test_different_or_uncertain_products_do_not_merge(changes):
    a = report(asin=ASIN)
    b = report("bensbargains", **changes)
    assert len(combine_leads([a,b])) == 2


@pytest.mark.parametrize("title", ["Samsung 990 PRO 4TB SSD", "2-pack Samsung 990 PRO 2TB SSD"])
def test_conflicting_asin_variants_stay_separate(title):
    a = report(asin=ASIN, title="1-pack Samsung 990 PRO 2TB SSD")
    b = report("bensbargains", asin=ASIN, title=title)
    assert len(combine_leads([a,b])) == 2


def test_same_parent_asin_with_different_colors_has_distinct_cards():
    a = report(asin=ASIN, title="Samsung USB 2TB SSD Black")
    b = report("bensbargains", asin=ASIN, title="Samsung USB 2TB SSD White")
    cards = combine_leads([a,b])
    assert len(cards) == 2 and cards[0]["id"] != cards[1]["id"]


def test_card_id_survives_source_order_changes_and_missing_publisher():
    a, b = report(asin=ASIN), report("bensbargains", asin=ASIN)
    both = combine_leads([a,b])[0]
    assert both["id"] == combine_leads([b,a])[0]["id"] == combine_leads([a])[0]["id"]
    assert a["id"] in both["aliases"] and b["id"] in both["aliases"]


def test_unknown_id_cannot_bridge_distinct_asins():
    a, b = report(asin=ASIN), report("bensbargains", asin="B087654321")
    c = report("nine-to-five-toys")
    assert len(combine_leads([c,a,b])) == 3


def test_generic_title_without_product_id_stays_separate():
    a = report(title='Samsung USB Type C Charger')
    b = report('bensbargains',title=a['title'])
    assert len(combine_leads([a,b])) == 2


def test_reports_cannot_turn_stale_quotes_into_confirmed_inventory():
    a, b = report(asin=ASIN, expires_at=0), report("bensbargains", asin=ASIN)
    card = combine_leads([a,b])[0]
    assert card["expires_at"] == b["expires_at"]
    assert next(r for r in card["reports"] if r["source"] == "dealnews")["expires_at"] == 0
    assert card["available"] is False and card["reasons"] and card["total"] is None


def test_only_tech_and_recent_usd_quotes_are_accepted():
    assert not parse_feed(feed(title="Dog food for $10"), "dealnews", NOW)
    row = parse_feed(feed(description="Walmart offers this SSD"), "dealnews", NOW)[0]
    assert row["merchant"] == "Walmart" and row["lead"] and not row["available"] and row["total"] is None
    assert not parse_feed(feed(), "dealnews", NOW+73*3600)
    assert not parse_feed(feed(), "dealnews", NOW-3600)
    row = parse_feed(feed(extra='<dn:price currency="USD">145.99</dn:price>'), "dealnews", NOW)[0]
    assert row["price"] == 145.99 and "Coupon or code mentioned" in row["terms"]
    assert parse_feed(feed(title="Save $50 on Samsung 990 PRO 2TB SSD"), "dealnews", NOW)[0]["price"] is None


def test_merchant_attribution_does_not_use_comparison_amazon_links():
    description = f'Adorama has this SSD. Compare with <a href="https://www.amazon.com/dp/{ASIN}">Amazon</a>.'
    row = parse_feed(feed(description=description), "dealnews", NOW)[0]
    assert row["merchant"] == "Adorama" and row["asin"] is None
    row = parse_feed(feed(description=description, extra='<dn:retailer>Newegg</dn:retailer>'), "dealnews", NOW)[0]
    assert row["merchant"] == "Newegg"
    unknown = parse_feed(feed(description="This SSD costs less than Amazon's previous price."), "dealnews", NOW)[0]
    assert unknown["merchant"] is None and unknown["asin"] is None
    ambiguous = parse_feed(feed(description="Amazon has this SSD. Walmart has it too."), "dealnews", NOW)[0]
    assert ambiguous["merchant"] is None


def test_non_amazon_reports_survive_restart_without_leaking_into_amazon_tab(tmp_path):
    from alerters.techscout.deal_feeds import cached_row
    row = parse_feed(feed(description="CyberPowerPC offers this SSD"), "dealnews", NOW)[0]
    row.update(asin=ASIN, available=True, total=100)
    clean = cached_row(row, "dealnews")
    assert clean["merchant"] == "CyberPowerPC" and clean["asin"] is None
    assert not clean["available"] and clean["total"] is None
    data = {"sources": {"dealnews": {"rows": [row], "checked_at": row["checked_at"], "failed": False}}, "metadata": {}}
    (tmp_path/'deal-feeds.json').write_text(json.dumps(data))
    collector = DealFeeds(tmp_path)
    assert collector.snapshot("monitor", NOW)["rows"][0]["merchant"] == "CyberPowerPC"
    assert collector.snapshot("supplies", NOW)["rows"]
    assert not collector.snapshot("amazon", NOW)["rows"]


def test_multiple_publishers_combine_only_same_merchant():
    a, b = report(merchant="Newegg"), report("bensbargains", merchant="Newegg")
    assert len(combine_leads([a, b])) == 1
    b["merchant"] = "Adorama"
    assert len(combine_leads([a, b])) == 2


@pytest.mark.parametrize("body", [b"<html>challenge</html>", b"<rss><channel>", b'<!DOCTYPE rss [<!ENTITY e "test">]><rss><channel/></rss>', b'x'*2_000_001], ids=["html", "malformed", "entity", "large"])
def test_invalid_or_unsafe_feed_fails_closed(body):
    with pytest.raises(ValueError):
        parse_feed(body, "dealnews", NOW)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://www.dealnews.com.evil.test/x", "https://www.dealnews.com@evil.test/x", "https://www.dealnews.com:443/x"])
def test_feed_links_cannot_escape_publisher(url):
    assert not parse_feed(feed(link=url), "dealnews", NOW)


def test_amazon_identity_is_us_product_specific():
    assert amazon_asin("https://www.amazon.com/dp/B012345678?tag=publisher") == ASIN
    assert amazon_asin("https://www.amazon.com/gp/product/B012345678/ref=abc") == ASIN
    assert amazon_asin("https://www.amazon.co.uk/dp/B012345678") is None
    assert amazon_asin("https://www.amazon.com.evil.test/dp/B012345678") is None
    assert amazon_asin("https://www.amazon.com/s?k=B012345678") is None


class FakeClient:
    calls = []
    fail = False
    def get(self, url):
        self.calls.append(url)
        if self.fail:
            raise requests.HTTPError("503")
        return feed(link="https://"+url.split('/')[2]+"/example"), None
    def enrich(self, row):
        return {"asin": ASIN}
    def close(self):
        pass


def test_collection_cache_cadence_failure_and_empty_replacement(tmp_path):
    clock = [NOW]
    FakeClient.calls, FakeClient.fail = [], False
    collector = DealFeeds(tmp_path, clock=lambda:clock[0], client_factory=FakeClient)
    collector.check()
    calls = len(FakeClient.calls)
    assert calls == sum(len(s["feeds"]) for s in SOURCES.values())
    assert len(collector.snapshot("amazon", NOW)["rows"]) == 3
    collector.check()
    assert len(FakeClient.calls) == calls
    restarted = DealFeeds(tmp_path,clock=lambda:clock[0],client_factory=FakeClient)
    restarted.check()
    assert len(FakeClient.calls) == calls
    clock[0] += 901
    FakeClient.fail = True
    restarted.check()
    state = restarted.snapshot("amazon",clock[0])
    assert len(state["rows"]) == 3 and not any(s["ready"] for s in state["sources"])
    assert all(r["expires_at"] == 0 for r in state["rows"])
    FakeClient.fail = False


def test_dashboard_combines_across_feeds_without_ranking_or_network(tmp_path):
    collector = DealFeeds(tmp_path)
    for source in SOURCES:
        collector.data["sources"][source] = {"checked_at":datetime.fromtimestamp(NOW,timezone.utc).isoformat(),
                                            "failed":False,"rows":[report(source,asin=ASIN)]}
    state = snapshot(tmp_path,"amazon",now=NOW,deal_feeds=collector)
    assert state["count"] == 1 and state["overlap_count"] == 2 and state["report_count"] == 3
    assert not state["groups"] and not state["held"]
    assert len(state["leads"][0]["reports"]) == 3


@pytest.mark.parametrize("data", [[], {"sources":{"dealnews":[]},"metadata":{}}, {"sources":{"dealnews":{"rows":[{"url":"javascript:alert(1)"}]}},"metadata":{}}])
def test_corrupt_cache_is_ignored(tmp_path, data):
    (tmp_path/'deal-feeds.json').write_text(json.dumps(data))
    collector = DealFeeds(tmp_path)
    assert not collector.snapshot('amazon',NOW)['rows']


def test_successfully_empty_feed_removes_old_reports(tmp_path):
    class EmptyClient(FakeClient):
        def get(self, url):
            return b'<rss><channel/></rss>', None
    collector=DealFeeds(tmp_path,clock=lambda:NOW,client_factory=EmptyClient)
    collector.data['sources']['dealnews']={'rows':[report()], 'checked_at':None, 'attempted_at':0}
    collector.check()
    assert not collector.snapshot('amazon',NOW)['rows']


def test_cached_public_projection_rejects_nonfinite_and_unknown_fields(tmp_path):
    collector=DealFeeds(tmp_path)
    row=report(price=float('nan'),secret='DO NOT EXPORT',total=99,available=True)
    collector.data['sources']['dealnews']={'rows':[row], 'checked_at':row['checked_at'],'failed':False}
    clean=collector.snapshot('amazon',NOW)['rows'][0]
    assert clean['price'] is None and clean['total'] is None and clean['available'] is False and 'secret' not in clean


def test_article_enrichment_ignores_sidebar_and_multiple_targets():
    row = report("nine-to-five-toys",title="Samsung 990 PRO 2TB SSD")
    client = FeedClient()
    client.article_allowed = lambda _: True
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        if url.startswith("https://amzn.to/"):
            return b"", "https://www.amazon.com/dp/B012345678?tag=original"
        return b'<aside><a href="https://www.amazon.com/dp/B087654321">Other product</a></aside><div class="entry-content"><p><a href="https://amzn.to/test">SSD</a></p></div>', None
    client.get = get
    assert client.enrich(row)["asin"] == ASIN
    assert not any(url.startswith("https://www.amazon.com") for url in calls)
    client.get = lambda *a, **kw: (b'<div class="entry-content"><p><a href="https://www.amazon.com/dp/B012345678">A</a><a href="https://www.amazon.com/dp/B087654321">B</a></p></div>', None)
    assert "asin" not in client.enrich(row)
    client.close()
