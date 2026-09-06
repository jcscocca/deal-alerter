"""Price-log tests.

The dedup rule is the one that matters. A 15-minute cron sees the same live
listing ~96 times a day; if each sighting were its own observation, one
stubbornly overpriced 3090 sitting unsold for a month would contribute ~2,900
rows and drag every percentile up with it, making the tool progressively more
willing to call ordinary prices a bargain.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from alerters.hardware.native.history import History, PriceStats, bucket_for


@pytest.fixture
def history(tmp_path):
    store = History(tmp_path / "prices.db")
    yield store
    store.close()


class TestDedup:
    def test_same_listing_seen_repeatedly_counts_once(self, history: History) -> None:
        for _ in range(96):
            history.record(
                part_key="rtx_3090",
                condition="used",
                unit_price=900.0,
                source="ebay",
                listing_id="item-1",
            )
        history.commit()
        assert history.total_observations() == 1

    def test_price_change_on_same_listing_is_new_information(
        self, history: History
    ) -> None:
        """A seller dropping their price is a real signal and must be recorded."""
        for price in (900.0, 850.0, 800.0):
            history.record(
                part_key="rtx_3090",
                condition="used",
                unit_price=price,
                source="ebay",
                listing_id="item-1",
            )
        history.commit()
        assert history.total_observations() == 3
        assert history.stats("rtx_3090", "used").low == 800.0

    def test_distinct_listings_count_separately(self, history: History) -> None:
        for index in range(5):
            history.record(
                part_key="rtx_3090",
                condition="used",
                unit_price=700.0 + index,
                source="ebay",
                listing_id=f"item-{index}",
            )
        history.commit()
        assert history.total_observations() == 5


class TestBuckets:
    def test_used_and_new_never_pool(self, history: History) -> None:
        """A sealed A6000 and a used one are different products."""
        history.record(
            part_key="rtx_a6000",
            condition="used",
            unit_price=2400.0,
            source="ebay",
            listing_id="u1",
        )
        history.record(
            part_key="rtx_a6000",
            condition="new",
            unit_price=4200.0,
            source="ebay",
            listing_id="n1",
        )
        history.commit()
        assert history.stats("rtx_a6000", "used").count == 1
        assert history.stats("rtx_a6000", "new").count == 1
        assert history.stats("rtx_a6000", "used").low == 2400.0

    def test_unknown_condition_is_treated_as_used(self) -> None:
        """Unlabelled listings live in the used market, not the new one."""
        assert bucket_for("unknown") == "used"
        assert bucket_for("open_box") == "new"
        assert bucket_for("refurbished") == "refurb"


class TestStats:
    def test_percentiles_track_the_distribution(self, history: History) -> None:
        for index, price in enumerate(range(600, 1100, 25)):
            history.record(
                part_key="rtx_3090",
                condition="used",
                unit_price=float(price),
                source="ebay",
                listing_id=f"i{index}",
            )
        history.commit()
        stats = history.stats("rtx_3090", "used")
        assert stats.count == 20
        assert stats.low == 600.0
        assert stats.median == pytest.approx(837.5)
        assert stats.percentile_of(600.0) == 0.0
        assert stats.percentile_of(837.5) == pytest.approx(50.0)

    def test_min_observations_is_configurable(self) -> None:
        """config.toml's threshold has to actually reach the trust decision."""
        deep = {"span_days": 60.0}
        assert not PriceStats("x", "used", count=5, min_observations=8, **deep).trustworthy
        assert PriceStats("x", "used", count=5, min_observations=3, **deep).trustworthy

    def test_no_history_is_not_trustworthy(self, history: History) -> None:
        assert not history.stats("rtx_4090", "used").trustworthy


class TestDurableFormat:
    """The JSONL is the committed source of truth; the .db is a throwaway cache.

    If a round trip loses or alters observations, every future verdict shifts
    silently, so this is worth pinning down.
    """

    def test_round_trip_preserves_the_distribution(self, tmp_path) -> None:
        first = History(tmp_path / "a.db")
        for index in range(25):
            first.record(
                part_key="rtx_3090",
                condition="used",
                unit_price=600.0 + index * 10,
                source="ebay",
                listing_id=f"i{index}",
            )
        first.commit()
        before = first.stats("rtx_3090", "used")
        log = tmp_path / "prices.jsonl"
        assert first.export_jsonl(log) == 25
        first.close()

        second = History(tmp_path / "b.db")
        assert second.import_jsonl(log) == 25
        after = second.stats("rtx_3090", "used")
        second.close()

        assert (after.count, after.low, after.median) == (
            before.count,
            before.low,
            before.median,
        )

    def test_export_is_deterministic(self, tmp_path) -> None:
        """An unchanged log must produce a byte-identical file, or the workflow's
        'did anything change?' check would commit noise on every run."""
        store = History(tmp_path / "a.db")
        for index in range(5):
            store.record(
                part_key="rtx_3090",
                condition="used",
                unit_price=600.0 + index,
                source="ebay",
                listing_id=f"i{index}",
            )
        store.commit()
        one, two = tmp_path / "1.jsonl", tmp_path / "2.jsonl"
        store.export_jsonl(one)
        store.export_jsonl(two)
        store.close()
        assert one.read_bytes() == two.read_bytes()

    def test_corrupt_line_does_not_lose_the_file(self, tmp_path) -> None:
        log = tmp_path / "prices.jsonl"
        log.write_text(
            '{"part_key":"rtx_3090","bucket":"used","unit_price":600.0,'
            '"source":"ebay","listing_id":"a","quantity":1,"sold":0,'
            '"first_seen":"2026-01-01T00:00:00+00:00","last_seen":"2026-01-01T00:00:00+00:00"}\n'
            "{ this is not json\n"
            '{"part_key":"rtx_3090","bucket":"used","unit_price":700.0,'
            '"source":"ebay","listing_id":"b","quantity":1,"sold":0,'
            '"first_seen":"2026-01-01T00:00:00+00:00","last_seen":"2026-01-01T00:00:00+00:00"}\n',
            encoding="utf-8",
        )
        store = History(tmp_path / "a.db")
        store.import_jsonl(log)
        assert store.total_observations() == 2
        store.close()

    def test_import_is_idempotent(self, tmp_path) -> None:
        """Re-importing the same log must not double every observation."""
        store = History(tmp_path / "a.db")
        store.record(
            part_key="rtx_3090",
            condition="used",
            unit_price=600.0,
            source="ebay",
            listing_id="a",
        )
        store.commit()
        log = tmp_path / "prices.jsonl"
        store.export_jsonl(log)
        store.import_jsonl(log)
        store.import_jsonl(log)
        assert store.total_observations() == 1
        store.close()


class TestPrune:
    def test_drops_stale_rows(self, history: History) -> None:
        old = datetime.now(timezone.utc) - timedelta(days=900)
        history.record(
            part_key="rtx_3090",
            condition="used",
            unit_price=700.0,
            source="ebay",
            listing_id="ancient",
            seen_at=old,
        )
        history.record(
            part_key="rtx_3090",
            condition="used",
            unit_price=650.0,
            source="ebay",
            listing_id="fresh",
        )
        history.commit()
        assert history.prune(keep_days=730) == 1
        history.commit()
        assert history.total_observations() == 1


class TestTitlesAreKept:
    """What the listing called itself, for auditing only.

    Every rule in match.py was written from a title someone read after the
    fact, and until 2026-08-13 the log kept none. The 3060 Ti sold as an RTX
    3090 could be identified only because the listing was still live on eBay to
    go and look at, and the rows purged alongside it had to be found by the
    shape of their ids rather than by what they said.
    """

    def test_a_title_survives_the_jsonl_round_trip(self, tmp_path) -> None:
        first = History(tmp_path / "a.db")
        first.record(
            part_key="rtx_3090",
            condition="used",
            unit_price=800.0,
            source="ebay",
            listing_id="v1|1|0",
            title="EVGA GeForce RTX 3090 FTW3 24GB",
        )
        first.commit()
        log = tmp_path / "prices.jsonl"
        first.export_jsonl(log)

        second = History(tmp_path / "b.db")
        second.import_jsonl(log)
        row = second.conn.execute("SELECT title FROM observations").fetchone()
        assert row["title"] == "EVGA GeForce RTX 3090 FTW3 24GB"

    def test_a_log_written_before_titles_still_loads(self, tmp_path) -> None:
        log = tmp_path / "prices.jsonl"
        log.write_text(
            json.dumps(
                {
                    "part_key": "rtx_3090",
                    "bucket": "used",
                    "unit_price": 800.0,
                    "source": "ebay",
                    "listing_id": "v1|1|0",
                    "quantity": 1,
                    "sold": 0,
                    "first_seen": "2026-08-01T00:00:00+00:00",
                    "last_seen": "2026-08-01T00:00:00+00:00",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        store = History(tmp_path / "a.db")
        assert store.import_jsonl(log) == 1
        assert store.conn.execute("SELECT title FROM observations").fetchone()["title"] == ""

    def test_a_database_made_before_the_column_is_migrated(self, tmp_path) -> None:
        """CREATE TABLE IF NOT EXISTS leaves an older store alone, so the
        column has to be added on open or the next write fails."""
        import sqlite3

        path = tmp_path / "old.db"
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE observations (
                id INTEGER PRIMARY KEY, part_key TEXT NOT NULL,
                bucket TEXT NOT NULL, unit_price REAL NOT NULL,
                source TEXT NOT NULL, listing_id TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                sold INTEGER NOT NULL DEFAULT 0,
                first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                UNIQUE(source, listing_id, unit_price)
            );
            """
        )
        conn.commit()
        conn.close()

        store = History(path)
        store.record(
            part_key="rtx_3090",
            condition="used",
            unit_price=800.0,
            source="ebay",
            listing_id="v1|1|0",
            title="EVGA GeForce RTX 3090 FTW3 24GB",
        )
        store.commit()
        assert store.total_observations() == 1
