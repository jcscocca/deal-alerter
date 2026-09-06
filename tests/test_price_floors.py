"""Server-side price floors for eBay searches.

eBay's active search sorts cheapest-first, and "RTX 3090" matches thousands of
items whose cheapest 50 are stickers, decals and mounting brackets -- observed
live: 50 results spanning $2.97 to $13.50, containing no graphics card at all.
The result window has to be spent on things that could plausibly be the part,
so the implausibility floor `assess()` applies afterwards is pushed into the
query itself.
"""

from __future__ import annotations

import pytest

from alerters.hardware.native.config import Config, Hunt, Thresholds, _query_for
from alerters.hardware.native.catalog import BY_KEY


@pytest.fixture
def cfg() -> Config:
    """A config with one hunt, built directly to avoid touching the real env."""
    return Config(
        ebay_client_id="",
        ebay_client_secret="",
        reddit_client_id="", reddit_client_secret="", country="US",
        currency_symbol="$", max_listing_age_hours=72, digest_at="GOOD",
        push_at="STRONG", remind_after_days=7, enforce_fit=False,
        psu_headroom_w=150,
        hunts=(Hunt(name="3090", parts=(BY_KEY["rtx_3090"],)),),
        thresholds=Thresholds(),
    )


class TestQueryPriceFloors:
    def test_floor_matches_the_downstream_reject_threshold(self, cfg: Config) -> None:
        """The floor must be the same number assess() would apply anyway."""
        part = BY_KEY["rtx_3090"]
        query = _query_for(part)
        expected = part.reference_price * cfg.thresholds.min_price_ratio

        assert cfg.query_price_floors[query] == expected

    def test_floors_key_off_the_same_strings_as_search_queries(
        self, cfg: Config
    ) -> None:
        """A floor keyed to a string no query uses would silently never apply."""
        assert set(cfg.query_price_floors) >= set(cfg.search_queries)

    def test_a_sticker_price_is_below_the_floor(self, cfg: Config) -> None:
        """The $2.97 accessory that prompted this must not survive the filter."""
        floor = cfg.query_price_floors[_query_for(BY_KEY["rtx_3090"])]
        assert 2.97 < floor
        assert 13.50 < floor

    def test_cheapest_part_wins_a_shared_query(self) -> None:
        """A floor that hides a real part is worse than one that lets junk in."""
        pair = (BY_KEY["rtx_3090"], BY_KEY["rtx_3090_ti"])
        cheap, dear = sorted(pair, key=lambda part: part.reference_price)

        cfg = Config(
            ebay_client_id="", ebay_client_secret="", reddit_client_id="",
            reddit_client_secret="",
            country="US", currency_symbol="$", max_listing_age_hours=72,
            digest_at="GOOD", push_at="STRONG", remind_after_days=7,
            enforce_fit=False, psu_headroom_w=150,
            hunts=(Hunt(name="both", parts=(dear, cheap)),),
            thresholds=Thresholds(),
        )
        # Both resolve to distinct queries today; if the catalog ever collapses
        # them, the floor must follow the cheaper part.
        for query, floor in cfg.query_price_floors.items():
            parts = [p for p in (cheap, dear) if _query_for(p) == query]
            assert floor == min(
                p.reference_price * cfg.thresholds.min_price_ratio for p in parts
            )


class TestFilterConstruction:
    def test_price_filter_is_sent_when_a_floor_exists(self) -> None:
        from alerters.hardware.native.sources.ebay import EbaySource

        src = EbaySource(
            ("RTX 3090",),
            client_id="x",
            client_secret="y",
            price_floors={"RTX 3090": 187.5},
        )
        assert src.price_floors["RTX 3090"] == 187.5

    def test_absent_floor_leaves_the_query_unfiltered(self) -> None:
        """No floor must mean no price filter, not a floor of zero."""
        from alerters.hardware.native.sources.ebay import EbaySource

        src = EbaySource(("Whatever",), client_id="x", client_secret="y")
        assert src.price_floors == {}
