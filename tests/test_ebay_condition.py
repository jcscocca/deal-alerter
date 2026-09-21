"""eBay's condition names, as eBay writes them.

The 2026-09-21 digest led with three refurbished MacBook Pro M4 Max listings
marked "via ebay; unknown" and measured "against 32 recorded used prices":

  278363058075  "MacBook Pro 16 Space Black 2024 M4 Max ... 128GB 1TB NANO"
  277881553263  "MacBook Pro 16 Space Black 2024 M4 Max ... 128GB 2TB Very Good"
  276964221825  "Apple MacBook Pro 16 2024 M4 Max ... 128GB 4TB Space Black"

Their pages say "Very Good - Refurbished" and "Excellent - Refurbished".
CONDITION_MAP carries VERY_GOOD_REFURBISHED and EXCELLENT_REFURBISHED, but the
lookup only turned spaces into underscores, so the " - " became "_-_" and no
key matched. Unknown pools with used, so refurbished units were judged -- and
logged -- as used ones.
"""

from __future__ import annotations

import pytest


def _listings(item: dict) -> list:
    from alerters.hardware.native.sources import ebay

    source = ebay.EbaySource((), client_id="x", client_secret="y")
    source._token = "token"

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> dict:
            return {"itemSummaries": [item], "itemSales": [item]}

    source.session.get = lambda *a, **k: FakeResponse()  # type: ignore[assignment]
    out = source._search_active("MacBook Pro M4 Max 128GB") + source._search_sold(
        "MacBook Pro M4 Max 128GB"
    )
    assert len(out) == 2
    return out


def _item(condition: str) -> dict:
    return {
        "itemId": "v1|278363058075|0",
        "title": "MacBook Pro 16 Space Black 2024 M4 Max 16-Core CPU 40-Core GPU 128GB 1TB NANO",
        "price": {"value": "4199.99"},
        "lastSoldPrice": {"value": "4199.99"},
        "lastSoldDate": "2026-09-20T00:00:00.000Z",
        "condition": condition,
    }


@pytest.mark.parametrize(
    "condition",
    [
        "Very Good - Refurbished",
        "Excellent - Refurbished",
        "Good - Refurbished",
        "Certified - Refurbished",
    ],
)
def test_graded_refurbished_is_refurbished(condition: str) -> None:
    for listing in _listings(_item(condition)):
        assert listing.condition_hint == "refurbished", listing.source


@pytest.mark.parametrize(
    "condition,expected",
    [
        ("New", "new"),
        ("Open box", "open_box"),
        ("Seller refurbished", "refurbished"),
        ("For parts or not working", "parts"),
    ],
)
def test_names_that_already_mapped_still_do(condition: str, expected: str) -> None:
    for listing in _listings(_item(condition)):
        assert listing.condition_hint == expected, listing.source


@pytest.mark.parametrize(
    "condition,expected",
    [
        # Plain "Used" matched nothing either, so every used eBay listing fell
        # back to whatever its title claimed. eBay's stated condition is the
        # one to trust.
        ("Used", "used"),
        ("Pre-owned", "used"),
        ("Pre-owned - Good", "used"),
        ("New other (see details)", "open_box"),
    ],
)
def test_every_ebay_condition_maps(condition: str, expected: str) -> None:
    for listing in _listings(_item(condition)):
        assert listing.condition_hint == expected, listing.source
