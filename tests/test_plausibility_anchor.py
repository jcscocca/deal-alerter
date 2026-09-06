"""What "implausible" is measured against.

assess() rejects anything outside min/max_price_ratio before percentile logic
runs, and it measured those ratios against catalog reference_price -- a constant
nobody had verified. Measured live on 2026-08-08, once the log had real data:
twelve of sixteen references sat below the *lowest price observed*, and the 1.6x
ceiling therefore landed under the market median. 501 of 743 matched listings
(67%) were discarded as implausibly expensive, including real single cards.

The fix is not a better constant -- it's to stop depending on one. Once a part
has enough observations to rank against, the observed median is the anchor, and
the constant only covers parts with no history yet.

A note on the existing log: those observations came in *through* the old gate,
so the sample is censored above 1.6x reference and its median reads low. That
biases the new anchor low too, but it converges -- a looser gate admits pricier
listings, which raises the median, which loosens the gate, settling where the
log holds everything up to 1.6x the true median.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from alerters.hardware.native.catalog import BY_KEY
from alerters.hardware.native.config import Thresholds
from alerters.hardware.native.history import PriceStats
from alerters.hardware.native.verdict import assess

PART = BY_KEY["rtx_3090"]
REF = PART.reference_price
# Ratios, not dollars -- reference_price is recalibrated from sold data as
# it becomes available, and these cases are about multiples of it.
MARKET = REF * 1.18  # a plausible observed median: asking runs above sold


def _stats(count: int, median: float | None = None) -> PriceStats:
    s = PriceStats(part_key=PART.key, bucket="used", count=count, span_days=60.0)
    if median is not None:
        s.low = median * 0.85
        s.p10 = median * 0.9
        s.p25 = median * 0.95
        s.median = median
    return s


def _assess(price: float, stats: PriceStats, **kw):
    return assess(
        listing_id="x",
        source="ebay",
        part=PART,
        title="EVGA RTX 3090 FTW3",
        url="u",
        unit_price=price,
        quantity=1,
        condition="used",
        posted_at=datetime.now(timezone.utc),
        stats=stats,
        thresholds=Thresholds(),
        **kw,
    )


class TestNoHistory:
    """Unchanged behaviour: with nothing logged, the constant is all there is."""

    def test_the_ceiling_is_loose_around_an_unverified_constant(self) -> None:
        """2x, not 1.6x. Asking prices run 23-49% above sold, so a legitimate
        listing against a sold-sourced constant reaches roughly 1.5x -- but not
        the 2.5x-and-up tail the log audit found, which nobody will buy."""
        assert _assess(REF * 1.7, _stats(0)) is not None, "1.7x ref: a real asking price"
        assert _assess(REF * 1.9, _stats(0)) is not None, "1.9x ref, still admitted"
        assert _assess(REF * 2.1, _stats(0)) is None, "2.1x ref, beyond any real ask"

    def test_plausible_against_reference_still_scores(self) -> None:
        assert _assess(REF * 0.9, _stats(0)) is not None


class TestWithHistory:
    """Once a part can be ranked, the market sets the bounds."""

    def test_real_card_above_stale_reference_is_no_longer_discarded(self) -> None:
        """1.4x the constant, but only 1.2x the median the log actually earned."""
        item = _assess(REF * 1.4, _stats(25, median=MARKET))
        assert item is not None, "a real card at market price must not be rejected"

    def test_genuinely_overpriced_is_still_rejected(self) -> None:
        """1.6x the observed median, not the constant."""
        assert _assess(MARKET * 2.0, _stats(25, median=MARKET)) is None

    def test_bait_band_follows_the_market_too(self) -> None:
        """The same price is credible against the constant and bait against the
        market, and the anchor swap is what decides which.

        The ratio moved from 0.55 to 0.90 on 2026-08-17 when
        suspicious_price_ratio was recalibrated: 0.55x a *sold* anchor is not
        the fair price this fixture used to call it, it is squarely in the bait
        band. 0.90x is the honest version of "credible against the constant".
        """
        stale = _assess(REF * 0.90, _stats(0))
        assert stale.loggable, "against the constant it looks like a fair price"

        live = _assess(REF * 0.90, _stats(25, median=MARKET * 1.6))
        assert not live.loggable, "against the market it is bait"

    def test_absurd_is_still_absurd(self) -> None:
        assert _assess(MARKET * 0.1, _stats(25, median=MARKET)) is None

    def test_untrustworthy_history_does_not_anchor(self) -> None:
        """Below min_observations the median is noise, so the constant holds --
        and with it the loose ceiling, since the constant is still unverified."""
        thin = _stats(3, median=MARKET)
        assert not thin.trustworthy
        assert _assess(REF * 2.1, thin) is None, "2.1x the constant, rejected"
        assert _assess(MARKET * 2.0, _stats(25, median=MARKET)) is None, (
            "2.0x the observed median, rejected by the tight ceiling"
        )
        assert _assess(REF * 1.9, thin) is not None, "1.9x constant: admitted"
        assert _assess(MARKET * 1.5, _stats(25, median=MARKET)) is not None, (
            "1.5x median: admitted"
        )


class TestSystemListings:
    """A machine containing four cards is not an overpriced card.

    Observed live: 'AMD EPYC 9375F 4x NVIDIA RTX PRO 6000 Blackwell' at $20,685
    was rejected at 2.4x reference. Prebuilts are never logged anyway, so the
    price gate protects nothing here and only hides them from you.
    """

    def test_multi_gpu_server_is_shown_not_rejected(self) -> None:
        item = _assess(REF * 5, _stats(0), is_system=True)
        assert item is not None
        assert not item.loggable, "still never enters the distribution"

    def test_bare_card_at_the_same_price_is_still_rejected(self) -> None:
        assert _assess(REF * 5, _stats(0), is_system=False) is None
