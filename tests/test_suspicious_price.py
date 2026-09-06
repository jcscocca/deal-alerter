"""A price the tool won't record must not headline the digest.

Mispriced and bait listings are, by construction, the cheapest things in a run,
so they score best and lead every digest. Observed live on the first eBay run: a
$200 EKWB water block matched to rtx_3090 and took the subject line as
"22 AI hardware deals (best: RTX 3090 24GB at $200)". Refusing to log the price
protected the history and left the alert untouched, which is backwards.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from alerters.hardware.native.catalog import BY_KEY
from alerters.hardware.native.config import Thresholds
from alerters.hardware.native.history import PriceStats
from alerters.hardware.native.verdict import Verdict, assess

PART = BY_KEY["rtx_3090"]
REF = PART.reference_price
# Ratios rather than dollars: a catalog recalibration must not silently
# reclassify these fixtures. See the 2026-08-08 sold-data correction.
BAIT = REF * 0.27
CREDIBLE = REF * 0.87
ABSURD = REF * 0.05


def _assess(price: float, **kw):
    part = PART
    return assess(
        listing_id="x",
        source="ebay",
        part=part,
        title="t",
        url="u",
        unit_price=price,
        quantity=1,
        condition="used",
        posted_at=datetime.now(timezone.utc),
        stats=PriceStats(part_key=part.key, bucket="used", count=0),
        thresholds=Thresholds(),
        **kw,
    )


class TestSuspiciousPrice:
    def test_bait_price_is_capped_below_push(self) -> None:
        """Ratio 0.27 of reference: plausible enough to show, not to believe."""
        item = _assess(BAIT)
        assert item is not None
        assert item.verdict <= Verdict.GOOD, "must not reach the STRONG push floor"
        assert not item.loggable

    def test_the_cap_is_stated_in_the_reason(self) -> None:
        item = _assess(BAIT)
        assert "bait rather than a bargain" in item.reason
        assert "never recorded" in item.reason

    def test_an_ordinary_price_is_untouched(self) -> None:
        """The cap must not touch prices in the believable range."""
        item = _assess(CREDIBLE)
        assert item is not None
        assert item.loggable
        assert "bait" not in item.reason

    def test_a_bait_price_cannot_outrank_a_real_deal(self) -> None:
        """The regression that started this: cheapest must not mean best."""
        bait = _assess(BAIT)
        real = _assess(CREDIBLE)
        assert real.score > bait.score

    @pytest.mark.parametrize("scale", [0.05, 0.08])
    def test_absurd_prices_are_still_rejected_outright(self, scale: float) -> None:
        """Below min_price_ratio nothing is shown at all -- unchanged behaviour."""
        assert _assess(REF * scale) is None


class TestTargetCannotResurrect:
    """The target override runs last and used to undo every safeguard above it.

    A bait price is under your target *because* it's mispriced, so the override
    promoted exactly the listings that had just been held back -- back to
    STRONG, which is the push threshold. The $200 water block would have rung
    the phone.
    """

    def test_bait_under_target_is_not_promoted_to_push(self) -> None:
        item = _assess(BAIT, target_price=CREDIBLE)
        assert item.target_hit
        assert item.verdict < Verdict.STRONG, "must not reach the push floor"

    def test_high_risk_seller_under_target_is_not_promoted(self) -> None:
        item = _assess(
            CREDIBLE * 0.92, target_price=CREDIBLE, seller_risk="high",
            seller_note="3 feedback"
        )
        assert item.target_hit
        assert item.verdict < Verdict.STRONG

    def test_a_trusted_listing_under_target_still_gets_through(self) -> None:
        """The override must keep working for prices we believe.

        Priced at the reference rather than under it: after the 2026-08-17
        recalibration a price at 0.85x already earns STRONG on its own, so the
        old fixture proved nothing about the override. Only a price that would
        not otherwise alert can show that the target is what promoted it.
        """
        ordinary = REF * 1.00
        item = _assess(ordinary, target_price=ordinary * 1.02)
        assert item.target_hit
        assert item.verdict >= Verdict.STRONG
        assert "under your" in item.headline
