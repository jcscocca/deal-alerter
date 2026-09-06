"""Verdict engine tests.

The rules worth protecting are the ones that keep the tool quiet: the
capability cap, the mining downgrade, and the refusal to call something a
record price when there's no record to compare it to.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from alerters.hardware.native.catalog import BY_KEY
from alerters.hardware.native.config import Thresholds
from alerters.hardware.native.history import PriceStats
from alerters.hardware.native.rig import host_vram_gb, largest_model_at, usable_for_weights
from alerters.hardware.native.verdict import Verdict, assess

NOW = datetime.now(timezone.utc)
TH = Thresholds()


def stats(count: int = 0, **kwargs) -> PriceStats:
    # span_days defaults to real depth: these fixtures mean "a part with
    # history", and history is time as well as row count.
    kwargs.setdefault("span_days", 60.0)
    return PriceStats(part_key="x", bucket="used", count=count, **kwargs)


def score(part_key: str, price: float, **kwargs):
    defaults = dict(
        listing_id="t",
        source="test",
        part=BY_KEY[part_key],
        title="test listing",
        url="https://example.invalid",
        unit_price=price,
        quantity=1,
        condition="used",
        posted_at=NOW,
        stats=stats(),
        thresholds=TH,
    )
    defaults.update(kwargs)
    return assess(**defaults)


class TestPlausibility:
    def test_rejects_scam_prices(self) -> None:
        """A $150 A6000 is not a deal, it's a scam or a mislabelled cable."""
        assert score("rtx_a6000", 150.0) is None

    def test_rejects_absurdly_overpriced(self) -> None:
        assert score("rtx_3090", 4000.0) is None

    def test_accepts_plausible(self) -> None:
        assert score("rtx_3090", 700.0) is not None


class TestCapabilityCap:
    def test_card_smaller_than_current_pool_is_capped(self) -> None:
        """The rule that stops 16GB cards ever reaching the push threshold.

        The desktop already holds 18GB, so a 16GB card is a sidegrade however
        cheap it is -- and at $400 against a $1000 reference it is very cheap.
        """
        item = score("rtx_5080", 400.0)
        assert item.verdict <= Verdict.GOOD
        assert "not an upgrade" in item.reason

    def test_bigger_card_is_not_capped(self) -> None:
        item = score("rtx_3090", 800.0)
        assert item.verdict > Verdict.GOOD
        assert "not an upgrade" not in item.reason


class TestMiningRisk:
    def test_high_risk_downgrades_one_level(self) -> None:
        clean = score("rtx_3090", 800.0, mining_risk="low")
        mined = score("rtx_3090", 800.0, mining_risk="high")
        assert mined.verdict == Verdict(int(clean.verdict) - 1)
        assert "ex-mining" in mined.reason

    def test_moderate_risk_warns_without_downgrading(self) -> None:
        clean = score("rtx_3090", 800.0, mining_risk="low")
        some = score("rtx_3090", 800.0, mining_risk="moderate")
        assert some.verdict == clean.verdict
        assert "mining signals" in some.reason


class TestHistoryVsReference:
    def test_thin_history_falls_back_to_reference(self) -> None:
        item = score("rtx_3090", 500.0, stats=stats(count=3, low=480, median=700))
        assert item.confidence == "reference"
        assert item.percentile is None
        assert "reference" in item.reason

    def test_thin_history_cannot_claim_grail(self) -> None:
        """Without observations, the strongest claim available is EXCEPTIONAL.

        "Cheapest ever" from a config file constant is a claim the tool has not
        earned, and dressing it up as one would make the badge meaningless.
        """
        ref = BY_KEY["rtx_3090"].reference_price
        item = score("rtx_3090", ref * 0.27, stats=stats(count=1))
        assert item.verdict <= Verdict.EXCEPTIONAL

    def test_rich_history_uses_percentiles(self) -> None:
        rich = stats(count=50, low=575, p10=610, p25=665, median=745)
        item = score("rtx_3090", 580.0, stats=rich)
        assert item.confidence == "history"
        assert item.percentile is not None
        assert item.verdict == Verdict.GRAIL

    def test_price_at_median_is_not_a_deal(self) -> None:
        rich = stats(count=50, low=575, p10=610, p25=665, median=745)
        item = score("rtx_3090", 745.0, stats=rich)
        assert item.verdict <= Verdict.FAIR


class TestTargets:
    # Both fixtures price at roughly the reference rather than far under it.
    # After the 2026-08-17 recalibration the old prices (0.64x and 0.79x a sold
    # anchor) either landed in the bait band or already earned STRONG on their
    # own, so neither one could demonstrate that the *target* is what promoted
    # the listing. A price the engine would otherwise call GOOD can.
    def test_target_forces_at_least_strong(self) -> None:
        item = score("rtx_3090", 1000.0, target_price=1020.0)
        assert item.target_hit
        assert item.verdict >= Verdict.STRONG

    def test_target_headline_quotes_the_target_not_the_price(self) -> None:
        item = score("rtx_pro_6000_blackwell_maxq", 9042.0, target_price=9200.0)
        assert "$9,200" in item.headline

    def test_missing_target_is_not_a_hit(self) -> None:
        assert not score("rtx_3090", 700.0, target_price=650.0).target_hit


class TestSystemListings:
    def test_prebuilt_is_capped(self) -> None:
        item = score("rtx_3090", 800.0, is_system=True)
        assert item.verdict <= Verdict.GOOD
        assert "complete system" in item.reason.lower()


class TestForParts:
    def test_for_parts_is_never_a_deal(self) -> None:
        item = score("rtx_a6000", 900.0, condition="parts")
        assert item.verdict == Verdict.PASS


class TestLadderMath:
    """The unlock claims have to survive contact with reality."""

    @pytest.mark.parametrize(
        "part_key,expected",
        [
            ("rtx_3090", "Qwen3 32B"),
            ("rtx_a6000", "Llama 3.3 70B"),
            ("rtx_pro_6000_blackwell_maxq", "gpt-oss 120B"),
            ("mac_studio_m3_ultra_512", "DeepSeek-V3 / R1 671B"),
        ],
    )
    def test_known_configurations(self, part_key: str, expected: str) -> None:
        part = BY_KEY[part_key]
        assert largest_model_at(part.usable_vram_gb).name == expected

    def test_context_reserve_is_capped(self) -> None:
        """A flat percentage would reserve 77GB on a 512GB Mac. It reserves 6."""
        assert usable_for_weights(512.0) == pytest.approx(506.0)
        assert usable_for_weights(24.0) == pytest.approx(20.4)

    def test_current_desktop_is_the_baseline(self) -> None:
        assert host_vram_gb() == 18


class TestBundlesAreNotSystems:
    """They used to share a sentence, and a listing naming two graphics cards
    was told it was a complete system containing one of them. Both are held out
    of the log for the same reason -- one price, more than one thing -- but
    they are different facts and the report says different things about them.
    """

    def test_a_bundle_says_so(self) -> None:
        item = score("rtx_3090", 800.0, is_bundle=True)
        assert item is not None
        assert item.is_bundle and not item.is_system
        assert "more than one card" in item.reason
        assert "complete system" not in item.reason
        assert not item.loggable

    def test_a_system_still_says_system(self) -> None:
        item = score("rtx_3090", 800.0, is_system=True)
        assert item is not None
        assert "complete system" in item.reason
        assert "more than one card" not in item.reason

    def test_a_bundle_is_not_rejected_for_being_expensive(self) -> None:
        """Several cards under one price legitimately exceeds the ceiling for
        one card, and the ceiling protects a log this never enters."""
        assert score("rtx_3090", 8000.0) is None
        assert score("rtx_3090", 8000.0, is_bundle=True) is not None

    def test_a_variation_listing_carries_its_flag(self) -> None:
        item = score("rtx_3090", 800.0, multi_variant=True)
        assert item is not None
        assert item.multi_variant
        assert not item.loggable
