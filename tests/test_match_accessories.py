"""The eBay accessory dialect.

The junk list was calibrated on Reddit and Slickdeals, and eBay speaks
differently. Its accessory sellers rarely say "water block" -- they say "EKWB
Quantum Vector ... Nickel Plexi", lead the title with "For" or "fits", or sell
NVLink bridges that name every card they connect. Every positive case here is a
listing observed live on the first day of eBay ingestion; the negative cases
are the real listings that look similar and must keep matching.
"""

from __future__ import annotations

import pytest

from alerters.hardware.native.match import match


class TestObservedAccessories:
    """Each of these matched a catalog part on 2026-08-08 and none is a card."""

    @pytest.mark.parametrize(
        "title",
        [
            # Leading brand + block-material vocabulary, no "water block" anywhere.
            "EKWB Quantum Vector RTX 3080/3090 Referenc D-RGB Nickel Plexi Active 145",
            # NVLink bridge naming the cards it connects, $190-$202 -- right in
            # the suspicious-price band for a 3090, so it cluttered the digest.
            "NVIDIA NVLink Bridge 2-Slot 900-53651 P3651 for RTX 3090 A5000",
            "used NVIDIA NVLink Bridge 2-Slot 900-53651 P3651 for RTX 3090",
            # Leading "For": the title is *about* the named GPU, not selling it.
            "For MSI RTX3080/ RTX3080Ti/ RTX3090 SUPRIM X Fan Heatsink (worn)",
            "2 x  fits GeForce RTX 3090 Sticker  Label  Decal Badge, Small 13mm",
            # Replacement fan, reversed word order the old pattern missed.
            "Replacement Fan for EVGA RTX 3090 FTW3 Graphics Card",
        ],
    )
    def test_is_rejected(self, title: str) -> None:
        assert match(title).junk, title


class TestRealCardsSurvive:
    """The strict direction is the expensive one: a killed listing is a missed
    deal. These are real or realistic card listings that share vocabulary with
    the accessories above and must not be caught."""

    @pytest.mark.parametrize(
        ("title", "part_key"),
        [
            # Observed live at $2,230: a real 3090 Ti with an EK block fitted.
            # "Water blocked" and a mid-title brand mention are not a block.
            (
                "NVIDIA GeForce RTX 3090 Ti Founders Edition - Water blocked "
                "EK-Quantum Vector",
                "rtx_3090_ti",
            ),
            # NVLink *capability* is a selling point on the cards themselves --
            # the A6000 hunt exists partly because of it.
            ("NVIDIA RTX A6000 48GB NVLink capable, workstation pull", "rtx_a6000"),
            # A bridge included with a card is a card.
            ("RTX A6000 48GB with NVLink bridge included", "rtx_a6000"),
            ("Dell Nvidia GeForce RTX 3090 24GB - MS-V388 - GDDR6X - Tested", "rtx_3090"),
            ("NVIDIA GeForce RTX 3090 Ti Founders Edition Dual Fan 24GB", "rtx_3090_ti"),
            # Mid-title "for" in sale phrasing must not read as compatibility.
            ("EVGA RTX 3090 FTW3 Ultra, priced for quick sale - $700", "rtx_3090"),
        ],
    )
    def test_still_matches(self, title: str, part_key: str) -> None:
        result = match(title)
        assert not result.junk, title
        assert result.part is not None and result.part.key == part_key, title


class TestSpecificity:
    def test_ti_title_is_not_the_plain_part(self) -> None:
        """'geforce rtx 3090' is a longer alias than 'rtx 3090 ti'; length must
        not outrank the reading that covers more of the title."""
        result = match("NVIDIA GeForce RTX 3090 Ti Founders Edition Dual Fan 24GB")
        assert result.part.key == "rtx_3090_ti"
        assert not result.is_bundle, "one card must not be a bundle with itself"

    def test_two_distinct_cards_still_bundle(self) -> None:
        result = match("[USA-TX] [H] Gigabyte RTX 4090, RTX 3090 FE [W] PayPal")
        assert result.is_bundle


class TestModelNumberCollision:
    def test_dell_g5_5090_is_not_an_rtx_5090(self) -> None:
        """Observed live at $650: the G5 5090 is a 2019 Dell desktop SKU."""
        result = match("USED Dell G5 5090 Tower Gaming Desktop Intel Core i7 GeForce")
        assert result.part is None

    def test_prebuilt_naming_the_card_properly_is_kept(self) -> None:
        result = match(
            "HP Omen 45L Intel i9-14900KF, NVIDIA GeForce RTX 5090, "
            "64GB RAM, 2TB SSD - $4987"
        )
        assert result.part is not None and result.part.key == "rtx_5090"
        assert result.is_system

    def test_bare_number_on_a_swap_post_still_matches(self) -> None:
        result = match("[USA-WA] [H] 5090, local only [W] PayPal")
        assert result.part is not None and result.part.key == "rtx_5090"
