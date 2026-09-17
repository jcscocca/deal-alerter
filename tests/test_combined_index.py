"""Price against capacity *and* speed, not capacity alone.

$/GB is the metric this project has always reported, and on its own it points
at the wrong hardware: a 128GB box at 256 GB/s beats a 3090 four to one on
capacity per dollar and generates tokens at a quarter of the rate. The combined
index -- price over (GB x TB/s) -- prices the half that $/GB throws away.

The tests that matter here are the ones where the two measures disagree. Any
metric can agree with another on an obvious case.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from alerters.hardware.native.catalog import (
    BY_KEY,
    PARTS,
    Kind,
    class_median_dollars_per_gb,
    class_median_dollars_per_gb_bandwidth,
)
from alerters.hardware.native.config import Thresholds
from alerters.hardware.native.history import PriceStats
from alerters.hardware.native.verdict import _value_sentence, assess

NOW = datetime.now(timezone.utc)


def score(part_key: str, price: float):
    return assess(
        listing_id="t", source="test", part=BY_KEY[part_key], title="test listing",
        url="https://example.invalid", unit_price=price, quantity=1, condition="used",
        posted_at=NOW, stats=PriceStats(part_key="x", bucket="used", count=0, span_days=60.0),
        thresholds=Thresholds(),
    )


def sentence(part_key: str, price: float) -> str:
    part = BY_KEY[part_key]
    return _value_sentence(
        part,
        price / part.vram_gb,
        class_median_dollars_per_gb(part.kind),
        price / part.capacity_bandwidth,
        class_median_dollars_per_gb_bandwidth(part.kind),
    )


class TestTheArithmetic:
    def test_index_is_price_over_capacity_times_bandwidth_in_tb(self) -> None:
        part = BY_KEY["rtx_3090"]
        # 24GB x 0.936 TB/s = 22.464. Scaled to TB/s so the dollar figure reads
        # as tens rather than hundredths; the ratio is unaffected either way.
        assert part.capacity_bandwidth == pytest.approx(22.464)
        assert score("rtx_3090", 700).dollars_per_gb_bandwidth == pytest.approx(700 / 22.464)

    def test_every_class_has_a_median_to_compare_against(self) -> None:
        for kind in Kind:
            assert class_median_dollars_per_gb_bandwidth(kind) > 0, kind

    def test_the_index_travels_with_the_assessment(self) -> None:
        # The plugin reads this off the assessment for the card and the value
        # axis, so a default of 0.0 reaching a report would be silent nonsense.
        assert score("rtx_3090", 700).dollars_per_gb_bandwidth > 0


class TestTheTwoMeasuresDisagree:
    """The whole reason for a second number."""

    def test_capacity_per_dollar_prefers_the_slow_box(self) -> None:
        # A DGX Spark holds five times what a 3090 holds for three times the
        # money, so $/GB says it is the better buy. It is also a third of the
        # bandwidth, which is the part $/GB cannot see.
        spark, card = score("dgx_spark", 2500), score("rtx_3090", 700)
        assert spark.dollars_per_gb < card.dollars_per_gb
        assert spark.dollars_per_gb_bandwidth > card.dollars_per_gb_bandwidth

    def test_slow_capacity_is_named_in_the_sentence(self) -> None:
        said = sentence("dgx_spark", 2500)
        assert "better than typical" in said  # cheap per GB
        assert "worse than typical" in said  # dear once speed counts
        assert "holds large models rather than running them quickly" in said

    def test_a_card_that_agrees_on_both_gets_no_disagreement_note(self) -> None:
        said = sentence("rtx_3090", 700)
        assert "holds large models rather than running them quickly" not in said
        assert "buying bandwidth here" not in said

    def test_paying_for_speed_is_called_that(self) -> None:
        # An H100 asked above its class on capacity is still cheap for its
        # 2 TB/s: 80GB is unremarkable next to datacenter peers, the bandwidth
        # is not, and the index is the only measure that notices.
        said = sentence("h100_80", 12600)
        assert "buying bandwidth here, not capacity" in said

    def test_both_figures_always_appear(self) -> None:
        for part in PARTS:
            said = sentence(part.key, part.reference_price)
            assert "/GB of VRAM" in said, part.key
            assert "per GB-TB/s" in said, part.key
