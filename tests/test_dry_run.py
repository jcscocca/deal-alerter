"""--dry-run must not touch the price log.

The whole verdict engine is measured against recorded history, so "just
checking" quietly adding observations is worse than it sounds: a dry run at an
arbitrary moment logs whatever asking prices happen to be up, and every future
percentile is computed against them. Skipping only the JSONL export isn't
enough -- the SQLite cache is never re-seeded once it has rows, so anything
committed there survives and gets exported by the next real run.

The cache is now private to a single run and rebuilt from the JSONL, so that
particular leak cannot recur. What these guard is the log the next run loads.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from alerters.hardware.native.sources.base import Listing
from tests.hardware_pipeline import evaluate, logged


@pytest.fixture
def state(tmp_path) -> Path:
    return tmp_path / "state"


@pytest.fixture
def listing() -> Listing:
    return Listing(
        listing_id="dry-1",
        source="test",
        title="EVGA RTX 3090 FTW3 24GB - $700 shipped",
        url="https://example.invalid/3090",
        posted_at=datetime.now(timezone.utc),
        price=700.0,
    )


class TestDryRunLeavesNoTrace:
    def test_a_real_run_records_the_observation(
        self, state: Path, listing: Listing
    ) -> None:
        """The control: this listing does reach the record loop."""
        _, matched = evaluate(state, [listing])
        assert matched == 1
        assert logged(state) == 1

    def test_dry_run_records_nothing(self, state: Path, listing: Listing) -> None:
        assessments, matched = evaluate(state, [listing], record=False)
        assert matched == 1
        assert assessments, "the listing should still be scored and reported"
        assert logged(state) == 0
