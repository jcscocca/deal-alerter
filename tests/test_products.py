"""Products: things hunted for themselves, judged on price alone.

The hardware engine was built to answer "what does this add to the cluster",
and a laptop bought to use answers that with nothing. A PRODUCT part keeps the
engine's price discipline -- its own log, a trusted anchor, bait and seller
vetoes, a target that pushes -- and drops the parts that only mean something
for VRAM: $/GB, the model ladder, the fit check and the no-upgrade cap.

The first one is the 2026 Zenbook Duo with the Core Ultra X9 388H, so the
titles below are the shapes its listings take on Slickdeals, r/buildapcsales
and eBay.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from alerters.hardware.native.catalog import BY_KEY, Kind, in_class
from alerters.hardware.native.config import Config, _query_for, load_watchlist
from alerters.hardware.native.match import match
from alerters.techscout.facets import attributes
from dealcore.run import run
from dealcore.state import AlertState
from dealcore.types import Listing
from dealcore.verdict import qualifies
from tests.hardware_pipeline import CONFIG, StubSource, plugin

ZENBOOK = BY_KEY["zenbook_duo_2026_x9_388h"]
WATCHLIST = CONFIG.with_name("watchlist.toml")
LAPTOP = ('ASUS Zenbook Duo Laptop (2026), Dual 14" OLED 3K 144Hz Touch Display, '
          "Intel Core Ultra X9 388H, Intel Arc Graphics, 32GB RAM, 1TB SSD")


def judged(tmp_path: Path, listings: list[Listing]):
    """One dry run over the shipped config: (core assessment, native detail) pairs."""
    hardware = plugin(tmp_path)
    hardware.sources = (StubSource(listings),)
    state = AlertState(hardware.state_dir / "alerts.json", hardware.normalise_key)
    options = replace(hardware.options, dry_run=True, preview=tmp_path / "report-hardware.html")
    try:
        result = run(hardware, state, options, ())
        assert not result.problems, result.problems
        by_id = {item.detail.listing_id: item for item in result.assessments}
        return by_id, options, hardware
    except Exception:
        hardware.close()
        raise


def listing(listing_id, title, *, source="slickdeals", price=None, condition=None):
    return Listing(listing_id, source, title, f"https://example.invalid/{listing_id}",
                   datetime.now(timezone.utc), price=price, condition_hint=condition)


class TestMatching:
    @pytest.mark.parametrize("title", [
        LAPTOP + " $2487.91 at Amazon",
        # Best Buy's naming, as it reaches Slickdeals.
        'ASUS - Zenbook Duo Dual 14" 3K OLED Touch Laptop - Intel Core Ultra X9 388H - '
        "32GB Memory - 1TB SSD - Moher Gray $2,599.99",
        # r/buildapcsales flair and shorthand.
        '[Laptop] ASUS Zenbook Duo 14" 3K OLED Ultra X9 388H 32GB/1TB - $2349 (Best Buy)',
        # eBay resellers often lead with the model code and never name the CPU.
        'ASUS Zenbook Duo UX8407AA-PSXT 14" Touchscreen Detachable 2 in 1 Notebook - 3K - 144 Hz',
    ])
    def test_its_listings_match_despite_every_laptop_signal(self, title) -> None:
        # Screen sizes, refresh rates, "laptop" and "zenbook" itself are all on
        # the mobile-GPU reject list. None of them may veto a product.
        result = match(title)
        assert result.part is ZENBOOK and not result.junk
        assert not result.is_system and not result.is_bundle and result.quantity == 1

    def test_a_retail_post_carries_its_price(self) -> None:
        assert match(LAPTOP + " $2487.91 at Amazon").price == pytest.approx(2487.91)

    @pytest.mark.parametrize("title", [
        # The base model and last year's share the name, not the graphics.
        "ASUS Zenbook Duo (2026) Core Ultra 9 386H 32GB 1TB $2099",
        "ASUS Zenbook Duo UX8406CA Core Ultra 9 285H 32GB 1TB $1799",
        "ASUS Zenbook Duo 2026 Core Ultra 7 355 32GB 1TB $1999",
        # A menu names both CPUs under one price, so the price is no one's.
        "ASUS Zenbook Duo 2026 X9 388H / 386H choose config $2299",
        # Accessories name the laptop they fit.
        "Screen Protector for ASUS Zenbook Duo 2026 UX8407AA Core Ultra X9 388H $59",
        "Hard Case for ASUS Zenbook Duo 2026 X9 388H 14 inch $79",
    ])
    def test_other_models_menus_and_accessories_do_not(self, title) -> None:
        assert match(title).part is None

    def test_the_laptop_veto_still_protects_the_gpu_catalog(self) -> None:
        # The exemption is for products only. A laptop 5090 is still not a 5090.
        result = match('ASUS ROG Zephyrus G16 16" 240Hz OLED Laptop RTX 5090 $3999')
        assert result.part is None and result.junk

    def test_no_gpu_facet_is_claimed_from_a_product(self) -> None:
        facets = attributes({"title": LAPTOP + " GPU"})
        assert facets["gpu"] == "Not established"
        assert facets["kind"] == "Laptops"


class TestJudgment:
    def test_a_new_unit_at_target_reaches_your_phone(self, tmp_path) -> None:
        found, options, hardware = judged(tmp_path, [listing("deal", LAPTOP + " $2487.91 at Amazon")])
        try:
            item = found["deal"]
            assert item.detail.condition == "new"  # retail boards default to new
            assert item.detail.target_hit and item.target_override
            assert qualifies(item, options.push_floor) and qualifies(item, options.email_floor)
        finally:
            hardware.close()

    def test_above_target_and_near_list_stays_quiet(self, tmp_path) -> None:
        found, options, hardware = judged(tmp_path, [listing("list", LAPTOP + " $2599.99 at Best Buy")])
        try:
            item = found["list"]
            assert not item.detail.target_hit
            assert not qualifies(item, options.email_floor)
            # Still recorded: a list-price sighting is exactly what the log needs.
            assert item.loggable
        finally:
            hardware.close()

    def test_a_deep_cut_pushes_on_its_own(self, tmp_path) -> None:
        found, options, hardware = judged(tmp_path, [listing("cut", LAPTOP + " $2199 at Amazon")])
        try:
            item = found["cut"]
            assert item.verdict >= hardware.bands.EXCEPTIONAL
            assert qualifies(item, options.push_floor)
        finally:
            hardware.close()

    def test_no_memory_sentences_reach_a_product(self, tmp_path) -> None:
        found, _, hardware = judged(tmp_path, [listing("deal", LAPTOP + " $2487.91 at Amazon")])
        try:
            detail = found["deal"].detail
            for phrase in ("/GB", "GB-TB/s", "Capped", "desktop", "Qwen", "Q4"):
                assert phrase not in detail.reason, phrase
            assert "list price" in detail.reason
            card = hardware.card(found["deal"])
            assert card.bar == ()
            assert "List price $2,699.99; your target $2,500" in card.facts
        finally:
            hardware.close()

    def test_a_used_unit_is_watched_not_alerted(self, tmp_path) -> None:
        # Against a new list price every used unit looks discounted, so the
        # list price supports a buy claim for a new one only.
        found, options, hardware = judged(tmp_path, [
            listing("used", LAPTOP, source="ebay", price=2050.0, condition="used")])
        try:
            item = found["used"]
            assert not item.alertable and not item.detail.reference_trusted
            assert not qualifies(item, options.push_floor)
            assert "WATCH / used" in item.detail.headline
            assert "says nothing about what a used one is worth" in item.detail.reason
        finally:
            hardware.close()

    def test_an_open_box_unit_is_judged_as_new(self, tmp_path) -> None:
        # The log already pools open-box with new, so the list price is the
        # same fair question to ask of both.
        found, options, hardware = judged(tmp_path, [
            listing("ob", LAPTOP, source="ebay", price=2199.0, condition="open_box")])
        try:
            item = found["ob"]
            assert item.detail.reference_trusted and qualifies(item, options.push_floor)
        finally:
            hardware.close()

    def test_with_history_a_unit_under_target_still_pushes(self, tmp_path) -> None:
        # Once the log can rank, the list price becomes the second opinion and
        # can hold a verdict back. That is a modest discount, not doubt about
        # the price, so it may not stop the target you named.
        log = tmp_path / "hardware" / "US" / "prices.jsonl"
        log.parent.mkdir(parents=True)
        now = datetime.now(timezone.utc)
        rows = []
        for day in range(10):
            seen = (now - timedelta(days=30 - day * 3)).isoformat()
            rows.append(json.dumps({
                "part_key": ZENBOOK.key, "bucket": "new", "unit_price": 2489.99 + day * 20,
                "source": "slickdeals", "listing_id": f"seed{day}", "title": LAPTOP,
                "quantity": 1, "sold": 0, "first_seen": seen, "last_seen": seen}))
        log.write_text("\n".join(rows) + "\n", encoding="utf-8")
        found, options, hardware = judged(tmp_path, [listing("hist", LAPTOP + " $2299 at Amazon")])
        try:
            item = found["hist"]
            assert item.detail.confidence == "history"
            assert "modest discount" in item.detail.reason
            assert item.detail.target_hit and qualifies(item, options.push_floor)
        finally:
            hardware.close()

    def test_bait_prices_keep_their_veto(self, tmp_path) -> None:
        # Under the target, but a third off list from an eBay seller is the
        # shape of bait. Shown, never recorded, never pushed.
        found, options, hardware = judged(tmp_path, [
            listing("bait", LAPTOP, source="ebay", price=1799.0, condition="new")])
        try:
            item = found["bait"]
            assert not item.loggable
            assert not qualifies(item, options.push_floor)
        finally:
            hardware.close()


class TestWatchlist:
    def test_the_shipped_watchlist_hunts_the_zenbook_at_its_target(self) -> None:
        hunts = {hunt.name: hunt for hunt in load_watchlist(WATCHLIST)}
        hunt = hunts["Zenbook Duo 2026 (X9 388H)"]
        assert hunt.parts == (ZENBOOK,) and hunt.target == 2500.0

    def test_its_search_names_the_cpu(self) -> None:
        # "Zenbook Duo" alone would return two years of older models.
        assert _query_for(ZENBOOK) == "Zenbook Duo 388H"
        cfg = Config.load(CONFIG, WATCHLIST)
        assert "Zenbook Duo 388H" in cfg.search_queries

    def test_no_hunt_is_silently_dropped_by_the_query_cap(self) -> None:
        # search_queries keeps the first 24, so a hunt added past the cap is
        # never searched and nothing says so.
        cfg = Config.load(CONFIG, WATCHLIST)
        wanted = {_query_for(part) for hunt in cfg.hunts for part in hunt.parts}
        wanted |= {query for hunt in cfg.hunts for query in hunt.queries}
        assert wanted <= set(cfg.search_queries)

    def test_a_catch_all_never_sweeps_up_a_product(self) -> None:
        assert ZENBOOK not in in_class("any")
        assert ZENBOOK in in_class("product")
        assert all(part.is_product for part in in_class("product"))
        assert not set(part.key for part in in_class("product")) & set(part.key for part in in_class("any"))
        assert ZENBOOK.kind is Kind.PRODUCT
