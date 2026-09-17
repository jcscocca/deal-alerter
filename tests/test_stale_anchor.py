"""A sold anchor that recent asking prices have caught up with is out of date.

Asks sit above what a thing sells for. When the last 30 days of asks have
fallen to the sold average a part is measured against, that average describes a
market that has moved -- a successor shipped, usually -- and every ratio taken
against it reads a band too generous. Observed on 2026-09-17: the M5 Ultra put
Mac Studio M3 Ultra asks at 0.95-1.01x their August sold averages, and a $4,699
96GB rang a phone as EXCEPTIONAL while the untouched 512GB part still asked
1.78x its own anchor.
"""

from __future__ import annotations

from datetime import datetime, timezone

from alerters.hardware.native.catalog import BY_KEY
from alerters.hardware.native.config import Thresholds
from alerters.hardware.native.history import PriceStats
from alerters.hardware.native.verdict import Verdict, assess

NOW = datetime.now(timezone.utc)
TH = Thresholds()
SOLD = BY_KEY["mac_studio_m3_ultra_96"]  # $6,228, Terapeak sold average
ESTIMATE = BY_KEY["mac_studio_m4_max_128"]  # same shape, unverified anchor
PUSHED = 4699.0  # the listing that actually pushed, 0.75x the anchor


def stats(**kwargs) -> PriceStats:
    kwargs.setdefault("count", 6)
    kwargs.setdefault("span_days", 0.0)  # reference path unless a test says otherwise
    return PriceStats(part_key=SOLD.key, bucket="used", **kwargs)


def score(price: float = PUSHED, part=SOLD, **kwargs):
    defaults = dict(
        listing_id="t",
        source="test",
        part=part,
        title="Apple Mac Studio M3 Ultra 96GB",
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


class TestStaleAnchor:
    def test_asks_that_have_fallen_to_the_anchor_hold_it_below_push(self) -> None:
        item = score(stats=stats(recent_median=5999.0, recent_count=5))
        assert item.verdict == Verdict.STRONG
        assert "out of date" in item.reason

    def test_a_ranked_verdict_is_held_below_push_too(self) -> None:
        """The cap has to survive the percentile path, which is where the real
        listing landed once its log covered enough days to rank."""
        ranked = stats(count=31, span_days=40.0, low=4699.0, p10=5100.0, p25=5949.0,
                       median=6300.0, recent_median=5999.0, recent_count=7)
        item = score(stats=ranked)
        assert item.confidence == "history"
        assert item.verdict == Verdict.STRONG

    def test_a_market_still_asking_above_the_anchor_is_untouched(self) -> None:
        item = score(stats=stats(recent_median=SOLD.reference_price * 1.78, recent_count=11))
        assert item.verdict == Verdict.EXCEPTIONAL

    def test_too_few_recent_prices_cannot_declare_an_anchor_stale(self) -> None:
        item = score(stats=stats(recent_median=5999.0, recent_count=4))
        assert item.verdict == Verdict.EXCEPTIONAL

    def test_an_estimate_still_says_it_is_an_estimate(self) -> None:
        """Estimates were already held below push. They must not start
        reporting the stale-anchor reason instead of their own."""
        item = score(
            price=ESTIMATE.reference_price * 0.75,
            part=ESTIMATE,
            stats=stats(recent_median=ESTIMATE.reference_price * 0.98, recent_count=9),
        )
        assert item.verdict == Verdict.STRONG
        assert "unverified estimate" in item.reason
        assert "out of date" not in item.reason
