"""Cooler model names are not quantities.

"MSI GeForce RTX 5090 Ventus 3X OC 32GB" is one card: Ventus 3X is MSI's
triple-fan cooler line. Read as a lot of three, its $4,499.99 became $1,500 a
card -- which is not merely a wrong alert but a logged one, since $1,500 sits
above the bait threshold for a $2,000-reference part. A model name in the
distribution is worse than a missed lot: alerts are transient, the log is not.

Every 3X/2X vendor line below is real: MSI Ventus, Gigabyte WINDFORCE, and the
Trio/Trinity families all encode fan count in the product name.
"""

from __future__ import annotations

import pytest

from alerters.hardware.native.match import detect_quantity, match


class TestCoolerNamesAreNotQuantities:
    @pytest.mark.parametrize(
        "title",
        [
            # Observed live at $4,499.99, parsed as 3 x $1,500.
            "MSI GeForce RTX 5090 Ventus 3X OC 32GB GDDR7 GPU - BRAND NEW SEALED!",
            "MSI RTX 4090 Ventus 3X E 24G OC",
            "MSI GeForce RTX 4070 Ventus 2X OC 12GB",
            "GIGABYTE GeForce RTX 3090 WINDFORCE 3X 24GB GDDR6X",
            "ZOTAC GAMING GeForce RTX 3090 Trinity OC 3X Fan 24GB",
        ],
    )
    def test_reads_as_one_unit(self, title: str) -> None:
        assert detect_quantity(title) == 1, title

    def test_the_observed_listing_prices_as_one_card(self) -> None:
        result = match(
            "MSI GeForce RTX 5090 Ventus 3X OC 32GB GDDR7 GPU - BRAND NEW SEALED!",
            price=4499.99,
        )
        assert result.quantity == 1
        assert result.unit_price == pytest.approx(4499.99)


class TestRealLotsStillDivide:
    """The strict direction has its own cost: 'Lot of 6 RTX 3090 - $3600' read
    as one card looks terrible and gets discarded, losing a real deal."""

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("3x RTX 3090 Founders Edition - $2100", 3),
            ("2X NVIDIA RTX A6000 48GB", 2),
            ("4 x GeForce RTX 3090 mining pull", 4),
            ("Lot of 6 RTX 3090 mining rig - $3600", 6),
            ("RTX 3090 qty: 2", 2),
            ("(3) NVIDIA Tesla A100 40GB", 3),
            ("Set of 2 RTX A6000", 2),
        ],
    )
    def test_counts(self, title: str, expected: int) -> None:
        assert detect_quantity(title) == expected, title

    def test_lot_of_six_still_divides_the_price(self) -> None:
        result = match("Lot of 6 RTX 3090 mining rig - $3600")
        assert result.quantity == 6
        assert result.unit_price == pytest.approx(600.0)
