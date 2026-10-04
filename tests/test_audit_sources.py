"""Source-to-report regressions from the October alert audit.

Seller excerpts are supplied audit evidence, not archived complete API payloads.
All source responses and transports are offline.
"""
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from alerters.hardware.native.sources.ebay import EbaySource, _delivered_price
from alerters.hardware.native.sources.reddit import _strip_html
from dealcore.types import Listing
from tests.hardware_pipeline import evaluate, logged


SERVER = "ASUS ESC8000A-E12 4U 8 GPU Server For NVIDIA A100 H100 80GB , AMD EPYC 9004 CPU"
EMPTY = "GPU: None; Processor: None; Memory: None; HDD: None"
BRIDGE = "NVIDIA GeForce RTX NVLink HB Bridge 4-Slot P3657 RTX 3090/3090Ti Tested"


def search_item(item):
    source = EbaySource((), client_id="test", client_secret="test")
    source._token = "test"
    calls = []

    class Response:
        status_code = 200

        def json(self):
            return {"itemSummaries": [item]}

    def get(*args, **kwargs):
        calls.append(kwargs)
        return Response()

    source.session.get = get
    rows = source._search_active("RTX 3090")
    assert len(calls) == 1  # descriptions cost no extra listing requests
    assert calls[0]["params"]["fieldgroups"] == "EXTENDED"
    return rows[0]


def test_ebay_preserves_seller_exclusion_and_shipping(tmp_path):
    listing = search_item({
        "itemId": "v1|188936957585|0", "title": SERVER,
        "price": {"value": "5903.20", "currency": "USD"},
        "shortDescription": "<p>GPU: None</p><p>Processor: None; Memory: None; HDD: None</p>",
        "shippingOptions": [{"shippingCost": {"value": "188.00", "currency": "USD"}}],
    })
    assert "GPU: None" in listing.body
    assert listing.price == pytest.approx(6091.20)
    assert evaluate(tmp_path, [listing])[0] == []
    assert logged(tmp_path) == 0


@pytest.mark.parametrize("options, expected", [
    ([], 5903.20),
    ([{"shippingCost": {"value": "0", "currency": "USD"}}], 5903.20),
    ([{"shippingCost": {"value": "200"}}, {"shippingCost": {"value": "188"}}], 6091.20),
    ([{"shippingCost": {"value": "-20"}}, {"shippingCost": {"value": "NaN"}}], 5903.20),
    ([{"shippingCost": {"value": "20", "currency": "EUR"}}], 5903.20),
])
def test_quoted_shipping_is_added_once(options, expected):
    item = {"price": {"value": "5903.20", "currency": "USD"}, "shippingOptions": options}
    assert _delivered_price(item) == pytest.approx(expected)


def test_reddit_rss_keeps_separate_sale_rows():
    body = _strip_html("<p>3x RTX 5090 FE - $6300 local pickup only at a bank</p>"
                       "<p>Switch 2 bundle - BNIB - $400</p>")
    assert body.splitlines() == ["3x RTX 5090 FE - $6300 local pickup only at a bank",
                                 "Switch 2 bundle - BNIB - $400"]


@pytest.mark.parametrize("item_id,title,price,body", [
    ("960010926668", BRIDGE, 1199.99,
     "One bridge only. Tested between two cards; cards are not included."),
    ("188936957585", SERVER, 6091.20, EMPTY),
    ("318628291875", SERVER, 5903.20, EMPTY),
    ("server-without-details", SERVER, 5903.20, ""),
])
def test_excluded_hardware_has_no_rating_fit_savings_or_history(tmp_path, item_id, title, price, body):
    row = Listing(item_id, "ebay", title, f"https://www.ebay.com/itm/{item_id}",
                  datetime.now(timezone.utc), price=price, body=body, condition_hint="used")
    assessments, matched = evaluate(tmp_path, [row])
    assert assessments == []
    assert matched == 0
    assert logged(tmp_path) == 0
    # Preview is emitted only by dry runs; the first pass above exercises the
    # normal recording path with all transports stubbed out.
    evaluate(tmp_path, [row], record=False)
    report = (tmp_path / "report-hardware.html").read_text(encoding="utf-8")
    assert "STRONG BUY" not in report
    assert "of room" not in report
    assert title not in report


def test_genuine_card_still_flows_into_report_and_history(tmp_path):
    row = Listing("real-card", "ebay", "Used NVIDIA RTX 3090 Ti 24GB Graphics Card",
                  "https://example.test/card", datetime.now(timezone.utc),
                  price=1050, body="One working card included. No drivers installed.",
                  condition_hint="used")
    assessments, matched = evaluate(tmp_path, [row])
    assert matched == 1 and len(assessments) == 1
    assert assessments[0].part.key == "rtx_3090_ti"
    assert assessments[0].quantity == 1
    assert not assessments[0].is_system
    assert logged(tmp_path) == 1


def test_explicit_nonworking_description_overrides_generic_source_condition(tmp_path):
    row = Listing("parts-card", "ebay", "NVIDIA RTX 3090 Ti 24GB Graphics Card",
                  "https://example.test/parts", datetime.now(timezone.utc),
                  price=1050, body="For parts, not working.", condition_hint="used")
    assessments, matched = evaluate(tmp_path, [row])
    assert matched == 1 and len(assessments) == 1
    item = assessments[0]
    assert item.condition == "parts"
    assert item.verdict.label == "PASS"
    assert item.vram_after == item.vram_before
    assert item.fit is None
    assert "unverified" in item.unlock
    assert logged(tmp_path) == 0


CAPTURED = json.loads((Path(__file__).parent / "fixtures" / "ebay_october_public_excerpts.json").read_text())


@pytest.mark.parametrize("entry", CAPTURED["items"], ids=lambda row: row["itemId"])
@pytest.mark.parametrize("description", ["missing", "compatibility_only", "seller_excerpt"])
def test_source_adapter_never_restores_unsupported_gpu_from_incomplete_description(tmp_path, entry, description):
    # Public seller excerpts in a simulated Browse envelope. This tests the
    # actual adapter/parser path, NOT whether Browse supplies these fields.
    item = {key: entry[key] for key in ("itemId", "title", "price")}
    if description == "seller_excerpt":
        item["shortDescription"] = entry["seller_description_excerpt"]
    elif description == "compatibility_only":
        item["shortDescription"] = "Applicable GPU model: NVIDIA A100 40GB A100 80GB H100 A800 H800"
    listing = search_item(item)
    assert evaluate(tmp_path, [listing])[0] == []
    assert logged(tmp_path) == 0


def test_actual_seller_gpu_none_table_vetoes_even_an_inclusion_title():
    from alerters.hardware.native.match import match

    # The live ASUS table uses separate cells, not the synthesized 'GPU: None'.
    body = CAPTURED["items"][1]["seller_description_excerpt"]
    result = match("GPU Server with NVIDIA H100 80GB", body=body, price=5903.20)
    assert result.part is None
