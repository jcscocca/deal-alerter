"""--dry-run must not touch the price log.

The whole verdict engine is measured against recorded history, so "just
checking" quietly adding observations is worse than it sounds: a dry run at an
arbitrary moment logs whatever asking prices happen to be up, and every future
percentile is computed against them. Skipping only the JSONL export isn't
enough -- the SQLite cache is never re-seeded once it has rows, so anything
committed there survives and gets exported by the next real run.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from alerters.hardware.native.config import Config
from alerters.hardware.native.history import History
from alerters.hardware.native.sources.base import Listing
from check_deals import evaluate


@pytest.fixture
def cfg(monkeypatch) -> Config:
    for name, value in (
        ("SMTP_USER", "nobody@example.invalid"),
        ("SMTP_PASSWORD", "unused"),
        ("MAIL_TO", "nobody@example.invalid"),
    ):
        monkeypatch.setenv(name, value)
    return Config.load()


@pytest.fixture
def history(tmp_path):
    store = History(tmp_path / "prices.db")
    yield store
    store.close()


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
        self, cfg: Config, history: History, listing: Listing
    ) -> None:
        """The control: this listing does reach the record loop."""
        _, matched = evaluate(cfg, [listing], history)
        assert matched == 1
        assert history.total_observations() == 1

    def test_dry_run_records_nothing(
        self, cfg: Config, history: History, listing: Listing
    ) -> None:
        assessments, matched = evaluate(cfg, [listing], history, record=False)
        assert matched == 1
        assert assessments, "the listing should still be scored and reported"
        assert history.total_observations() == 0
