"""One listing, several prices, one title that names all of them.

Observed live on 2026-08-13, pushed as an EXCEPTIONAL RTX 3090 at $593:

  Dell NVIDIA GeForce RTX 3060 3070 3080 3090 8 10 12 24GB GDDR6X GRAPHICS CARD

It is a multi-variation eBay listing with five options behind a dropdown, and
the option the search returned was `v1|318721947819|616991316905` -- a 3060 Ti
8GB. The 3090 variant in the same listing is $2,187.55. The title names every
model the seller stocks, so the matcher read "3090", took the price sitting
next to it, and produced a card that is not for sale at a price that is not the
3090's.

Nothing already in the file could have caught it. The price is *plausible*: 59%
of the 3090 reference, well clear of the bait band, so no threshold saves you.
`is_bundle` counts catalog parts, and 3060/3070/3080 are not in a catalog built
for 24GB-plus inference cards, so one part was named and the title looked
unambiguous. It logged.

The general shape: a Browse item id is `v1|<listing>|<variation>`, and a
non-zero variation segment means the title belongs to the group while the price
belongs to one option nobody names. So two rules, and they are different rules:

  - A variation listing is never an observation. Which option eBay surfaced is
    its choice, not the market's, and the same listing comes back under
    different options on different queries -- the log already holds one ASUS
    workstation three times at $3,999, $4,599 and $4,999.
  - A variation listing whose title names *several cards* is not shown either.
    A bundle sells you every card in its title and is worth seeing; a menu
    sells you one of them, and the cheapest is what you are being quoted.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from alerters.hardware.native.match import match, names_multiple_models
from alerters.hardware.native.sources.base import Listing, group_id
from alerters.hardware.native.sources.ebay import _variant_of_many

OBSERVED = "Dell NVIDIA GeForce RTX 3060 3070 3080 3090 8 10 12 24GB GDDR6X GRAPHICS CARD"


class TestModelEnumeration:
    """A title carrying several model numbers cannot price any one of them."""

    @pytest.mark.parametrize(
        "title",
        [
            OBSERVED,
            "Dell NVIDIA GeForce RTX 3060 3070 3080 3090 GRAPHICS CARD 10GB GDDR6X -Alienware",
            "DELL PRECISION 3660 I7-13700K 1TB SSD 16GB RTX 4060 4070 4070Ti 5070",
            "NVIDIA RTX A4000 A5000 A6000 Professional GPU - pick your model",
        ],
    )
    def test_reads_as_several_models(self, title: str) -> None:
        assert names_multiple_models(title), title

    @pytest.mark.parametrize(
        "title",
        [
            # One card, stated three ways. None of these is a menu.
            "GIGABYTE GeForce RTX 3090 WINDFORCE 3X 24GB GDDR6X",
            "NVIDIA GeForce RTX 3090 Ti Founders Edition 24GB",
            "MSI GeForce RTX 5090 Ventus 3X OC 32GB GDDR7 GPU - BRAND NEW SEALED!",
            "PNY NVIDIA RTX A6000 48GB GDDR6 Professional Graphics Card",
            # Numbers that are not model numbers: PSU wattage, storage, screen
            # resolution, an Intel SKU, and a year.
            "EVGA RTX 3090 FTW3 Ultra + Corsair RM1000x 1000W PSU",
            "ASUS ROG RTX 4090 24GB, i9-14900KF, 2TB NVMe, 3840x2160 bundle",
            "Apple MacBook Pro 2020 16in M3 Max 128GB RAM 2TB SSD",
        ],
    )
    def test_reads_as_one_model(self, title: str) -> None:
        assert not names_multiple_models(title), title


class TestTheObservedListing:
    def test_a_variation_menu_is_dropped_entirely(self) -> None:
        """Not downgraded, not captioned -- the matched card is not on offer.

        Mobile and accessory listings already take this exit for the same
        reason: a near miss on identity is worse than no match at all.
        """
        result = match(OBSERVED, price=593.40, multi_variant=True)
        assert result.part is None
        assert result.junk

    def test_without_the_variation_signal_it_is_still_never_logged(self) -> None:
        """The title alone can't distinguish a menu from a real bundle, so a
        multi-model title stays visible -- 'RTX 3090 + 4090, $2500' is a deal
        worth seeing -- but its price never reaches the distribution."""
        result = match(OBSERVED, price=593.40)
        assert result.is_bundle

    def test_a_single_card_is_still_a_single_card(self) -> None:
        result = match("EVGA GeForce RTX 3090 FTW3 24GB", price=800.0)
        assert result.part is not None
        assert result.part.key == "rtx_3090"
        assert not result.is_bundle

    def test_a_variation_listing_naming_one_card_still_matches(self) -> None:
        """Variants by condition or capacity are not an identity problem. The
        card is what the title says; only the price is unattributable, and that
        is `loggable`'s job, not the matcher's."""
        result = match(
            "Dell Nvidia L40S 48GB GPU Accelerator", price=9499.0, multi_variant=True
        )
        assert result.part is not None
        assert result.part.key == "l40s"


class TestVariationIds:
    @pytest.mark.parametrize(
        ("item_id", "expected"),
        [
            ("v1|318721947819|616991316905", True),
            ("v1|117348165461|417248627113", True),
            ("v1|123456789012|0", False),
            ("v1|123456789012", False),
            ("", False),
        ],
    )
    def test_reads_the_variation_segment(self, item_id: str, expected: bool) -> None:
        assert _variant_of_many(item_id) is expected


class TestEbaySourceMarksThem:
    def _listings(self, item: dict) -> list:
        from alerters.hardware.native.sources import ebay

        source = ebay.EbaySource((), client_id="x", client_secret="y")
        source._token = "token"

        class FakeResponse:
            status_code = 200

            @staticmethod
            def json() -> dict:
                return {"itemSummaries": [item]}

        source.session.get = lambda *a, **k: FakeResponse()  # type: ignore[assignment]
        return source._search_active("RTX 3090")

    def test_a_variation_listing_is_never_loggable(self) -> None:
        [listing] = self._listings(
            {
                "itemId": "v1|318721947819|616991316905",
                "title": OBSERVED,
                "price": {"value": "593.40"},
                "condition": "New",
            }
        )
        assert listing.multi_variant
        assert not listing.loggable

    def test_an_ordinary_listing_is_untouched(self) -> None:
        [listing] = self._listings(
            {
                "itemId": "v1|123456789012|0",
                "title": "EVGA GeForce RTX 3090 FTW3 24GB",
                "price": {"value": "800.00"},
                "condition": "Used",
            }
        )
        assert not listing.multi_variant
        assert listing.loggable


class TestSoldSearchTakesTheSameGuard:
    """Insights ids carry the same variation segment, and a sold row is the
    observation everything else defers to -- price_stats switches a part to
    sold-only the moment it has enough of them, so a variation-level sale would
    arrive with that authority and supersede every honest asking price."""

    def _sold(self, item: dict) -> list:
        from alerters.hardware.native.sources import ebay

        source = ebay.EbaySource((), client_id="x", client_secret="y")
        source._token = "token"

        class FakeResponse:
            status_code = 200

            @staticmethod
            def json() -> dict:
                return {"itemSales": [item]}

        source.session.get = lambda *a, **k: FakeResponse()  # type: ignore[assignment]
        return source._search_sold("RTX 3090")

    def test_a_variation_sale_is_never_loggable(self) -> None:
        [listing] = self._sold(
            {
                "itemId": "v1|318721947819|616991316905",
                "title": OBSERVED,
                "lastSoldPrice": {"value": "593.40"},
                "lastSoldDate": "2026-08-01T00:00:00.000Z",
            }
        )
        assert listing.multi_variant
        assert not listing.loggable
        assert listing.sold

    def test_an_ordinary_sale_still_logs(self) -> None:
        [listing] = self._sold(
            {
                "itemId": "v1|123456789012|0",
                "title": "EVGA GeForce RTX 3090 FTW3 24GB",
                "lastSoldPrice": {"value": "800.00"},
                "lastSoldDate": "2026-08-01T00:00:00.000Z",
            }
        )
        assert not listing.multi_variant
        assert listing.loggable


class TestGroupId:
    """Which listing an option belongs to, for dedup and the alert history."""

    @pytest.mark.parametrize(
        ("listing_id", "expected"),
        [
            ("v1|318721947819|616991316905", "v1|318721947819"),
            ("v1|123456789012|0", "v1|123456789012"),
            ("sold-v1|123456789012|7", "sold-v1|123456789012"),
            ("t3_abc123", "t3_abc123"),
            ("", ""),
        ],
    )
    def test_collapses_the_option(self, listing_id: str, expected: str) -> None:
        assert group_id(listing_id) == expected


class TestDedupe:
    """The watchlist overlaps on purpose and eBay answers every query with the
    same listings. Measured across three Mac Studio queries: 51 ids came back
    more than once, and one $3,999 machine was printed three times in a digest.
    """

    def _listing(self, listing_id: str, price: float | None) -> Listing:
        return Listing(
            listing_id=listing_id,
            source="ebay",
            title="Apple Mac Studio M3 Ultra 256GB",
            url="https://example.invalid",
            posted_at=datetime.now(timezone.utc),
            price=price,
        )

    def test_the_same_listing_from_two_queries_appears_once(self) -> None:
        import check_deals

        out = check_deals._dedupe(
            [self._listing("v1|800499630296|0", 3999.0)] * 3
        )
        assert len(out) == 1

    def test_options_of_one_listing_collapse_to_the_cheapest(self) -> None:
        import check_deals

        out = check_deals._dedupe(
            [
                self._listing("v1|117348165461|417248627113", 4999.99),
                self._listing("v1|117348165461|417248627114", 3999.99),
                self._listing("v1|117348165461|417248627115", 4599.99),
            ]
        )
        assert len(out) == 1
        assert out[0].price == pytest.approx(3999.99)

    def test_an_unpriced_duplicate_never_wins(self) -> None:
        """None must not sort as free, or a Reddit post with no structured
        price would displace the eBay row that has one."""
        import check_deals

        out = check_deals._dedupe(
            [
                self._listing("v1|800499630296|0", None),
                self._listing("v1|800499630296|0", 3999.0),
            ]
        )
        assert len(out) == 1
        assert out[0].price == pytest.approx(3999.0)

    def test_distinct_listings_survive(self) -> None:
        import check_deals

        out = check_deals._dedupe(
            [
                self._listing("v1|800499630296|0", 3999.0),
                self._listing("v1|168609628892|0", 3400.0),
            ]
        )
        assert len(out) == 2


class TestAlertKeysCollapse:
    """eBay hands back a different option of the same listing depending on
    which query found it, so keying the alert history on the full id makes one
    listing look like several and defeats remind_after_days."""

    def _assessment(self, listing_id: str):
        from alerters.hardware.native.catalog import PARTS
        from alerters.hardware.native.config import Thresholds
        from alerters.hardware.native.history import PriceStats
        from alerters.hardware.native.verdict import assess

        part = next(p for p in PARTS if p.key == "rtx_3090")
        return assess(
            listing_id=listing_id,
            source="ebay",
            part=part,
            title="EVGA GeForce RTX 3090 FTW3 24GB",
            url="https://example.invalid",
            unit_price=part.reference_price * 0.8,
            quantity=1,
            condition="used",
            posted_at=datetime.now(timezone.utc),
            stats=PriceStats(part_key="rtx_3090", bucket="used", count=0),
            thresholds=Thresholds(),
        )

    def test_two_options_share_one_key(self, tmp_path) -> None:
        from alerters.hardware.native.state import AlertState

        state = AlertState(tmp_path / "alerts.json")
        first = self._assessment("v1|147488693237|445806612036")
        second = self._assessment("v1|147488693237|445806612039")
        assert AlertState.key(first) == AlertState.key(second)

        state.record([first], pushed=True)
        assert not state.should_push(second, remind_after_days=7)

    def test_an_old_file_is_migrated_rather_than_orphaned(self, tmp_path) -> None:
        import json

        from alerters.hardware.native.state import AlertState

        path = tmp_path / "alerts.json"
        path.write_text(
            json.dumps(
                {
                    "updated_at": "2026-08-13T00:00:00+00:00",
                    "alerts": {
                        "ebay:v1|147488693237|445806612036": {
                            "price": 800.0,
                            "verdict": 5,
                            "pushed_at": "2026-08-13T00:00:00+00:00",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        state = AlertState(path)
        assert "ebay:v1|147488693237" in state.records
        assert not state.should_push(
            self._assessment("v1|147488693237|445806612039"), remind_after_days=7
        )


class TestVerdictKeepsItOutOfTheLog:
    def test_multi_variant_forces_loggable_false(self) -> None:
        from alerters.hardware.native.catalog import PARTS
        from alerters.hardware.native.config import Thresholds
        from alerters.hardware.native.history import PriceStats
        from alerters.hardware.native.verdict import assess

        part = next(p for p in PARTS if p.key == "l40s")
        item = assess(
            listing_id="v1|137427059410|435638611301",
            source="ebay",
            part=part,
            title="Dell Nvidia L40S 48GB GPU Accelerator",
            url="https://example.invalid",
            unit_price=part.reference_price * 0.8,
            quantity=1,
            condition="used",
            posted_at=datetime.now(timezone.utc),
            stats=PriceStats(part_key="l40s", bucket="used", count=0),
            thresholds=Thresholds(),
            multi_variant=True,
        )
        assert item is not None
        assert not item.loggable
        assert "option" in item.reason or "variant" in item.reason
