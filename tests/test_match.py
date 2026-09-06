"""Matcher tests.

Most of these are real titles, or near-copies of real titles, taken from the
sources while building this. The junk and lot cases matter most: a false
positive there means a 3am push notification about a cardboard box, and a
missed lot means throwing away the best deals on the board.
"""

from __future__ import annotations

import pytest

from alerters.hardware.native.match import detect_quantity, extract_price, is_junk, match


class TestJunk:
    @pytest.mark.parametrize(
        "title",
        [
            "RTX 3090 *BOX ONLY* no card - $25",
            "NVIDIA RTX A6000 48GB -- FOR PARTS, NOT WORKING",
            "EVGA RTX 3090 FTW3 waterblock (card not included)",
            "RTX 4090 backplate replacement",
            "RTX 3090 cooler only, no GPU",
            "Broken RTX 3090 for parts",
        ],
    )
    def test_rejects_non_hardware(self, title: str) -> None:
        assert is_junk(title)
        assert match(title).junk

    @pytest.mark.parametrize(
        "title",
        [
            "[GPU] EVGA GeForce RTX 3090 FTW3 Ultra Gaming - $749.99 (eBay)",
            "NVIDIA RTX A6000 48GB GDDR6 Workstation Graphics Card",
        ],
    )
    def test_keeps_real_cards(self, title: str) -> None:
        assert not is_junk(title)


class TestPartMatching:
    def test_ti_beats_base_model(self) -> None:
        """The specificity rule: '3090 Ti' must not be claimed by the 3090 entry."""
        assert match("MSI RTX 3090 Ti SUPRIM X - $899").part.key == "rtx_3090_ti"
        assert match("EVGA RTX 3090 FTW3 - $749").part.key == "rtx_3090"

    def test_word_boundaries(self) -> None:
        """'a100' must not match inside 'a1000'."""
        assert match("NVIDIA RTX A1000 8GB - $300").part is None

    def test_capacity_disambiguates_configurable_products(self) -> None:
        assert (
            match("Mac Studio M3 Ultra 512GB").part.key == "mac_studio_m3_ultra_512"
        )
        assert (
            match("Mac Studio M3 Ultra 256GB").part.key == "mac_studio_m3_ultra_256"
        )

    def test_wrong_capacity_is_rejected_not_guessed(self) -> None:
        """A 64GB Studio is not a 512GB Studio going cheap."""
        result = match("Apple Mac Studio M3 Ultra 64GB")
        assert result.part is None


class TestPrice:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("[GPU] RTX 3090 - $749.99 (eBay)", 749.99),
            ("RTX 4090 $1,599.00 shipped", 1599.00),
            ("A6000 3299 USD", 3299.0),
        ],
    )
    def test_extracts(self, title: str, expected: float) -> None:
        assert extract_price(title) == expected

    def test_ignores_capacity_as_price(self) -> None:
        """'RTX 3090 24GB' must not parse as a $24 card."""
        assert extract_price("RTX 3090 24GB GDDR6X") is None


class TestQuantity:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Lot of 6 RTX 3090 mining cards - $3600", 6),
            ("2x RTX 3090 FE - $1400 for the pair", 2),
            ("Set of 4 NVIDIA A100 40GB PCIe $14000", 4),
            ("(3) RTX A6000 cards", 3),
            ("EVGA RTX 3090 FTW3 - $749", 1),
        ],
    )
    def test_detects(self, title: str, expected: int) -> None:
        assert detect_quantity(title) == expected

    def test_does_not_read_model_numbers_as_quantities(self) -> None:
        assert detect_quantity("RTX 3090 Ti 24GB GDDR6X") == 1
        assert detect_quantity("NVIDIA A100 80GB") == 1

    def test_unit_price_is_what_gets_scored(self) -> None:
        """A lot of six at $3600 is a $600 card, and must be judged as one."""
        result = match("Lot of 6 RTX 3090 mining rig cards - $3600")
        assert result.quantity == 6
        assert result.price == 3600.0
        assert result.unit_price == 600.0


class TestSystemListings:
    def test_prebuilt_containing_a_gpu_is_flagged(self) -> None:
        """Observed on Slickdeals -- would otherwise poison the 3090 history."""
        result = match(
            "ASUS ROG Strix GA35 Gaming Desktop PC, RTX 3090, "
            "AMD 9 5900X, 32GB DDR4 RAM, 1TB SSD - $1,899"
        )
        assert result.part.key == "rtx_3090"
        assert result.is_system

    def test_bare_card_is_not_flagged(self) -> None:
        assert not match("[GPU] EVGA RTX 3090 FTW3 - $749").is_system

    def test_unified_boxes_are_not_flagged(self) -> None:
        """A Mac Studio is supposed to be a whole computer."""
        assert not match("Apple Mac Studio M3 Ultra 256GB - $4,799").is_system
        assert not match("Framework Desktop Ryzen AI Max+ 395 128GB").is_system


class TestHaveWant:
    """r/hardwareswap titles encode direction. Getting this backwards means
    alerting on someone who wants to *buy* the card you want to buy.

    All of these are real titles sampled from the subreddit.
    """

    def test_have_section_is_what_is_for_sale(self) -> None:
        result = match("[USA-TN] [H] EVGA RTX 3090 FTW3 24GB [W] Paypal, Local Cash")
        assert result.part is not None
        assert result.part.key == "rtx_3090"

    def test_want_section_is_never_matched(self) -> None:
        """The critical case. This person is BUYING a 5090, not selling one."""
        result = match("[USA-MI][H]Local cash, PayPal [W] RTX 5090")
        assert result.part is None

    def test_want_section_ignored_even_with_a_price_in_the_body(self) -> None:
        """Body says 'below $3800' -- that's a budget, not an asking price."""
        result = match(
            "[USA-FL] [H] PayPal, Local Cash [W] RTX 3090 Ti Founders Edition",
            body="Looking to purchase an RTX 3090 Ti. Willing to pay up to $1200.",
        )
        assert result.part is None
        assert result.price is None

    def test_splitter(self) -> None:
        from alerters.hardware.native.match import split_have_want

        have, is_swap = split_have_want("[USA-TN] [H] HP OMEN RTX 3090 [W] Local Cash")
        assert is_swap
        assert "3090" in have
        assert "Local Cash" not in have

        plain, is_swap = split_have_want("[GPU] EVGA RTX 3090 FTW3 - $749")
        assert not is_swap
        assert plain == "[GPU] EVGA RTX 3090 FTW3 - $749"

    def test_price_falls_back_to_body_on_swap_posts(self) -> None:
        """Private sellers put the price in the post, not the headline."""
        result = match(
            "[USA-TN] [H] HP OMEN RTX 3090 [W] Local Cash",
            body="$1000 local @ 38506. Will consider shipping later.",
        )
        assert result.part.key == "rtx_3090"
        assert result.price == 1000.0

    def test_retail_listings_do_not_take_prices_from_the_body(self) -> None:
        """On a retail feed a body price is as likely to be a competitor's."""
        result = match(
            "[GPU] EVGA RTX 3090 FTW3 Ultra",
            body="Was $899 last month, historical low $650.",
        )
        assert result.price is None


class TestBundles:
    def test_multi_item_post_is_flagged(self) -> None:
        """One post, four items, prices scattered through the body -- no single
        price can be attributed to the 4090."""
        result = match(
            "[USA-TX] [H] Gigabyte 4090, 3090 FE, 32gb DDR5, 1TB NVME SSD [W] PayPal"
        )
        assert result.is_bundle

    def test_single_item_is_not_a_bundle(self) -> None:
        assert not match("[USA-TN] [H] HP OMEN RTX 3090 [W] Local Cash").is_bundle

    def test_find_all_parts(self) -> None:
        from alerters.hardware.native.match import find_all_parts

        keys = {part.key for part in find_all_parts("RTX 4090 and RTX 3090 for sale")}
        assert keys == {"rtx_4090", "rtx_3090"}


class TestMiningRisk:
    def test_scores_obvious_rig_pulls(self) -> None:
        assert match("Lot of 8 RTX 3090 mining farm pull").mining_risk == "high"

    def test_clean_listing_scores_low(self) -> None:
        assert match("[GPU] EVGA RTX 3090 FTW3 - $749 (Newegg)").mining_risk == "low"
