"""Listings you found yourself.

Every other source is a search, and the listings a search misses are invisible
to the price log as well as to you. This is the way in for a card a colleague
is selling or a link somebody sent you, and it goes through the same matcher,
verdict engine and history as anything eBay returned.

The rules worth protecting: a stored URL is never fetched, re-adding one URL
replaces rather than duplicates, and a line you mangled by hand is reported
rather than silently skipped.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from alerters.hardware.manual import (
    ManualSource,
    add,
    canonical_url,
    entry_id,
    read,
)
from dealcore.types import SourceError


@pytest.fixture
def store(tmp_path):
    return tmp_path / "manual.jsonl"


class TestCanonicalUrl:
    @pytest.mark.parametrize("raw", [
        "https://www.ebay.com/itm/1234?utm_source=reddit&utm_campaign=x",
        "https://www.ebay.com/itm/1234#description",
        "https://www.ebay.com/itm/1234?hash=item1a2b&_trksid=p999",
    ])
    def test_the_route_you_arrived_by_is_not_the_listing(self, raw: str) -> None:
        assert canonical_url(raw) == "https://www.ebay.com/itm/1234"

    def test_a_variation_id_names_which_thing_is_for_sale_and_survives(self) -> None:
        # Stripping this would merge the 24GB option and the 48GB option of one
        # listing into a single entry at whichever price was typed last.
        assert canonical_url("https://x.test/i?var=42") != canonical_url("https://x.test/i?var=43")

    def test_parameter_order_is_not_a_difference(self) -> None:
        assert canonical_url("https://x.test/i?b=2&a=1") == canonical_url("https://x.test/i?a=1&b=2")

    @pytest.mark.parametrize("raw", [
        "javascript:alert(1)", "file:///etc/passwd", "not a url",
        "https://user:secret@x.test/i",
    ])
    def test_refuses_what_is_not_a_listing_link(self, raw: str) -> None:
        with pytest.raises(ValueError):
            canonical_url(raw)


class TestTheStore:
    def test_an_entry_round_trips(self, store) -> None:
        add(store, url="https://x.test/i", price=650.0, title="RTX 3090 FE", condition="used")
        (entry,) = read(store)
        assert (entry.price, entry.title, entry.condition) == (650.0, "RTX 3090 FE", "used")

    def test_re_adding_a_url_corrects_it_rather_than_duplicating(self, store) -> None:
        add(store, url="https://x.test/i?utm_source=a", price=650.0, title="RTX 3090")
        add(store, url="https://x.test/i", price=600.0, title="RTX 3090 FE")
        (entry,) = read(store)
        assert (entry.price, entry.title) == (600.0, "RTX 3090 FE")

    def test_two_listings_stay_two(self, store) -> None:
        add(store, url="https://x.test/a", price=650.0, title="RTX 3090")
        add(store, url="https://x.test/b", price=700.0, title="RTX 3090")
        assert len({row.listing_id for row in read(store)}) == 2

    def test_an_id_is_the_url_and_nothing_else(self, store) -> None:
        # The alert key is "manual:<id>", and dealcore splits that on the first
        # colon, so an id carrying one would corrupt every later dedup.
        assert ":" not in entry_id("https://x.test/i")

    def test_a_missing_store_is_empty_not_an_error(self, store) -> None:
        assert read(store) == []

    @pytest.mark.parametrize("line", ['{"url": "https://x.test/i"}', "{oh dear", '{"url": "nope", "title": "t", "price": 1}'])
    def test_a_hand_edited_mistake_is_reported_not_skipped(self, store, line: str) -> None:
        # Silently dropping the line would look exactly like a deletion, and you
        # would go on believing the tool was watching something it was not.
        store.write_text(line + "\n", encoding="utf-8")
        with pytest.raises(SourceError):
            read(store)

    @pytest.mark.parametrize("bad", [
        dict(price=0.0), dict(price=-5.0), dict(condition="mint"), dict(title="   "),
    ])
    def test_refuses_an_entry_it_could_not_judge(self, store, bad: dict) -> None:
        fields = dict(url="https://x.test/i", price=650.0, title="RTX 3090", **{}) | bad
        with pytest.raises(ValueError):
            add(store, **fields)


class TestAsAListing:
    def test_it_is_evidence(self, store) -> None:
        # You looked at this listing and chose to type it in. That is a fairer
        # sample than a search sorted by price ascending, so it may be logged.
        add(store, url="https://x.test/i", price=650.0, title="RTX 3090", condition="used")
        (listing,) = ManualSource(store).fetch()
        assert listing.loggable and listing.source == "manual"
        assert (listing.price, listing.condition_hint) == (650.0, "used")
        assert listing.sold is False

    def test_an_unstated_condition_is_left_for_the_matcher_to_read(self, store) -> None:
        add(store, url="https://x.test/i", price=650.0, title="RTX 3090, barely used")
        (listing,) = ManualSource(store).fetch()
        assert listing.condition_hint == ""

    def test_a_witnessed_sale_can_be_recorded_as_one(self, store) -> None:
        # Sold prices and asking prices are different populations and the log
        # keeps them apart. Nothing here can verify the claim; it is your word.
        add(store, url="https://x.test/i", price=620.0, title="RTX 3090", sold=True)
        assert ManualSource(store).fetch()[0].sold is True

    def test_the_timestamp_is_when_you_added_it(self, store) -> None:
        when = datetime.now(timezone.utc) - timedelta(days=9)
        add(store, url="https://x.test/i", price=650.0, title="RTX 3090", now=when)
        (listing,) = ManualSource(store).fetch()
        assert abs((listing.posted_at - when).total_seconds()) < 1


class TestAgeing:
    """A manual entry is a standing instruction, not a search hit."""

    def plugin(self):
        from types import SimpleNamespace as NS

        from alerters.hardware.native.match import match
        from alerters.hardware.plugin import HardwarePlugin

        plugin = HardwarePlugin.__new__(HardwarePlugin)
        plugin.cfg = NS(max_listing_age_hours=72)
        plugin.matcher, plugin.seen, plugin.matched = match, 0, 0
        plugin.watched = {"rtx_3090": NS(name="RTX 3090", target=700.0)}
        return plugin

    def listing(self, store, source: str):
        add(store, url="https://x.test/i", price=650.0, title="RTX 3090 24GB",
            now=datetime.now(timezone.utc) - timedelta(days=9))
        (listing,) = ManualSource(store).fetch()
        return listing if source == "manual" else type(listing)(
            **{**listing.__dict__, "source": source})

    def test_a_stale_search_hit_is_dropped(self, store) -> None:
        assert self.plugin().prepare(self.listing(store, "ebay")) is None

    def test_a_manual_entry_stays_until_you_delete_the_line(self, store) -> None:
        # Ageing it out would quietly stop watching a listing you asked for,
        # with nothing anywhere saying it had stopped.
        assert self.plugin().prepare(self.listing(store, "manual")) is not None
