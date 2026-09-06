"""Eight observations from one afternoon is not history.

`min_observations` counted rows and nothing else, which was safe while the log
filled a listing at a time from Reddit. eBay changed that: one run deposits ~180
observations, so a part crosses the threshold within a single snapshot of
current inventory.

Scoring that inventory against a distribution built from itself makes the
cheapest 3% GRAIL *by construction* -- in any market, forever, regardless of
whether prices are good. Measured on 2026-08-08 with a log 22 hours deep: 10
GRAIL and 34 push-worthy listings in one run. A GRAIL that fires 34 times a day
is not a signal.

evaluate() already guards the within-run case ("scoring after recording would
let a listing contribute to the distribution it's being ranked within"). The
same reasoning applies across runs, because the same listings are still there
tomorrow. Percentiles need the log to span enough time for inventory to have
actually turned over.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from alerters.hardware.native.history import History


@pytest.fixture
def history(tmp_path):
    store = History(tmp_path / "prices.db")
    yield store
    store.close()


def _fill(history: History, n: int, *, spread_days: float) -> None:
    """n distinct listings, first_seen spread evenly over `spread_days`."""
    now = datetime.now(timezone.utc)
    for i in range(n):
        history.record(
            part_key="rtx_3090",
            condition="used",
            unit_price=900.0 + i,
            source="ebay",
            listing_id=f"item-{i}",
            seen_at=now - timedelta(days=spread_days * (1 - i / max(n - 1, 1))),
        )
    history.commit()


class TestDepthRequirement:
    def test_a_single_snapshot_is_not_trustworthy(self, history: History) -> None:
        """20 listings scraped in one afternoon: plenty of rows, no history."""
        _fill(history, 20, spread_days=0.02)
        stats = history.stats("rtx_3090", "used", min_observations=8)
        assert stats.count == 20
        assert not stats.trustworthy

    def test_the_same_count_spread_over_weeks_is(self, history: History) -> None:
        _fill(history, 20, spread_days=30)
        stats = history.stats("rtx_3090", "used", min_observations=8)
        assert stats.trustworthy

    def test_depth_alone_is_not_enough_either(self, history: History) -> None:
        """Three listings six months apart is still three listings."""
        _fill(history, 3, spread_days=180)
        stats = history.stats("rtx_3090", "used", min_observations=8)
        assert not stats.trustworthy

    def test_span_is_reported(self, history: History) -> None:
        _fill(history, 10, spread_days=21)
        stats = history.stats("rtx_3090", "used")
        assert 20 <= stats.span_days <= 22

    def test_empty_log_has_no_span(self, history: History) -> None:
        stats = history.stats("rtx_3090", "used")
        assert stats.span_days == 0.0
        assert not stats.trustworthy
