"""Our own price history, because nobody else keeps one for hardware.

This is the module that the Steam version of this project didn't need. ITAD had
already logged every Steam price change for a decade, so `verdict.py` could ask
"how does today compare?" and get a real answer on day one. There is no ITAD for
GPUs. Keepa covers Amazon only; eBay's sold-listing history is 90 days and
behind a restricted API; r/buildapcsales is a firehose with no memory.

So the tool logs every listing it sees, forever, and grows its own answer to
"is $700 cheap for a 3090?". Two consequences worth knowing:

  * The first few weeks are weak. Below `min_observations` the verdict engine
    falls back to catalog reference prices, and says so in the alert rather than
    pretending to a confidence it doesn't have.
  * Used and new are never mixed. A refurb A6000 and a sealed one are different
    products that happen to share a name, and pooling them makes the percentile
    meaningless in both directions.

The observation log is committed back to the repo by the workflow, the same way
the Steam project committed alerts.json -- that's what makes the history
survive between stateless Actions runs.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dealcore.state import atomic_write

# Conditions that are priced comparably enough to pool. Anything not listed
# here is bucketed on its own.
CONDITION_BUCKETS = {
    "new": "new",
    "open_box": "new",
    "refurbished": "refurb",
    "used": "used",
    "unknown": "used",  # the used market is where unlabelled listings live
    # Never pooled with anything. A dead card's price is not evidence about
    # working ones, and letting it default into `used` would make a $300
    # for-parts 3090 the all-time low for working 3090s.
    "parts": "parts",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id           INTEGER PRIMARY KEY,
    part_key     TEXT    NOT NULL,
    bucket       TEXT    NOT NULL,
    unit_price   REAL    NOT NULL,
    source       TEXT    NOT NULL,
    listing_id   TEXT    NOT NULL,
    -- What the listing called itself. Carried for auditing, never for matching.
    -- Every rule in match.py was written from a title someone read after the
    -- fact, and until now the log kept none: the 3060 Ti sold as an RTX 3090 on
    -- 2026-08-13 could be identified only because the listing was still live on
    -- eBay to go and look at, and the rows purged with it had to be found by
    -- the shape of their ids rather than by what they said. Blank on anything
    -- recorded before 2026-08-13.
    title        TEXT    NOT NULL DEFAULT '',
    quantity     INTEGER NOT NULL DEFAULT 1,
    -- 1 when the price is what something actually *sold* for rather than what
    -- it was listed at. Asking prices skew high; sold prices are the truth.
    sold         INTEGER NOT NULL DEFAULT 0,
    first_seen   TEXT    NOT NULL,
    last_seen    TEXT    NOT NULL,
    UNIQUE(source, listing_id, unit_price)
);
CREATE INDEX IF NOT EXISTS idx_part_bucket ON observations(part_key, bucket);
CREATE INDEX IF NOT EXISTS idx_last_seen   ON observations(last_seen);
"""


def bucket_for(condition: str) -> str:
    return CONDITION_BUCKETS.get(condition, "used")


@dataclass
class PriceStats:
    """What the log knows about one part in one condition bucket."""

    part_key: str
    bucket: str
    count: int
    low: float | None = None
    p10: float | None = None
    p25: float | None = None
    median: float | None = None
    # Cheapest we have ever recorded, and when.
    all_time_low: float | None = None
    all_time_low_at: datetime | None = None
    # Median over the last 30 days, to spot a market that is moving.
    recent_median: float | None = None
    # How many of the observations are confirmed sales rather than asking prices.
    sold_count: int = 0

    # Below this many observations the percentiles are noise. Overridden per
    # run from thresholds.min_observations in config.toml; the default is here
    # so PriceStats stays usable standalone (tests, --stats).
    min_observations: int = 8
    # How much wall-clock time the observations cover, oldest to newest.
    span_days: float = 0.0
    min_span_days: float = 14.0

    @property
    def trustworthy(self) -> bool:
        """Enough prices, gathered over enough time to mean anything.

        Counting rows alone was safe while the log filled one listing at a time
        from Reddit. eBay deposits ~180 in a single run, so a part clears any
        row count inside one snapshot of current inventory -- and ranking that
        inventory against a distribution built from itself makes the cheapest
        3% GRAIL by construction, in any market, forever. Observed on
        2026-08-08 with a 22-hour-old log: 10 GRAIL, 34 push-worthy, one run.

        evaluate() already refuses to let a listing join the distribution it is
        being ranked within. This is the same rule across runs, since the same
        listings are still on sale tomorrow: percentiles wait until the log
        covers enough time for inventory to have genuinely turned over.
        """
        return self.count >= self.min_observations and self.span_days >= self.min_span_days

    def percentile_of(self, price: float) -> float | None:
        """Roughly where `price` sits in the recorded distribution, 0-100.

        Interpolating properly would need the full sample in memory; the four
        anchors we keep are enough to answer "is this a top-10% price?", which
        is the only question the verdict engine actually asks.
        """
        if not self.count or self.median is None:
            return None
        anchors = [
            (self.low, 0.0),
            (self.p10, 10.0),
            (self.p25, 25.0),
            (self.median, 50.0),
        ]
        anchors = [(value, pct) for value, pct in anchors if value is not None]
        if not anchors:
            return None
        if price <= anchors[0][0]:
            return 0.0
        for (low_value, low_pct), (high_value, high_pct) in zip(anchors, anchors[1:]):
            if price <= high_value:
                span = high_value - low_value
                if span <= 0:
                    return high_pct
                return low_pct + (price - low_value) / span * (high_pct - low_pct)
        return 100.0


class History:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        # CREATE TABLE IF NOT EXISTS leaves a database made by an older version
        # alone, so a column added later has to be added here too. Cheap enough
        # to check on every open, and it keeps the working store and a log
        # rebuilt from JSONL on the same shape.
        columns = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(observations)")
        }
        if "title" not in columns:
            self.conn.execute(
                "ALTER TABLE observations ADD COLUMN title TEXT NOT NULL DEFAULT ''"
            )
        self.conn.commit()

    # ------------------------------------------------------------------ writes

    def record(
        self,
        *,
        part_key: str,
        condition: str,
        unit_price: float,
        source: str,
        listing_id: str,
        title: str = "",
        quantity: int = 1,
        sold: bool = False,
        seen_at: datetime | None = None,
    ) -> None:
        """Log one sighting.

        The UNIQUE(source, listing_id, unit_price) constraint is the important
        part. A 15-minute cron sees the same live listing ~96 times a day; without
        it, one stubbornly overpriced 3090 would contribute a hundred rows a day
        and drag every percentile up with it. Instead the first sighting inserts
        and the rest just bump last_seen -- one listing, one vote. A *price
        change* on the same listing does insert, because that's genuinely new
        information about what the seller will accept.
        """
        now = (seen_at or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        self.conn.execute(
            """
            INSERT INTO observations
                (part_key, bucket, unit_price, source, listing_id, title,
                 quantity, sold, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, listing_id, unit_price)
            DO UPDATE SET last_seen = excluded.last_seen,
                          title = COALESCE(NULLIF(excluded.title, ''), title)
            """,
            (
                part_key,
                bucket_for(condition),
                round(unit_price, 2),
                source,
                listing_id,
                title,
                quantity,
                1 if sold else 0,
                now,
                now,
            ),
        )

    def commit(self) -> None:
        self.conn.commit()

    def prune(self, keep_days: int = 730) -> int:
        """Drop observations older than two years. Returns rows removed.

        GPU prices decay fast enough that a 2021 listing tells you nothing about
        2026, and an unbounded table eventually makes the git-committed database
        unpleasant to move around.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
        cursor = self.conn.execute(
            "DELETE FROM observations WHERE last_seen < ?", (cutoff,)
        )
        return cursor.rowcount

    # ------------------------------------------------------------------- reads

    def stats(
        self,
        part_key: str,
        condition: str,
        *,
        min_observations: int = 8,
        min_span_days: float = 14.0,
        sold_only: bool = False,
    ) -> PriceStats:
        """Distribution summary for one part in the bucket matching `condition`.

        `sold_only` restricts to confirmed sales. Asking and sold prices are two
        different distributions -- an asking price is what nobody has paid yet --
        and pooling them makes the percentile mean neither, the same way pooling
        used and new does. Callers should prefer sold stats once there are
        enough of them and fall back to the pooled view before that.
        """
        bucket = bucket_for(condition)
        rows = self.conn.execute(
            f"""
            SELECT unit_price, first_seen, last_seen, sold
              FROM observations
             WHERE part_key = ? AND bucket = ?
                   {"AND sold = 1" if sold_only else ""}
             ORDER BY unit_price ASC
            """,
            (part_key, bucket),
        ).fetchall()

        stats = PriceStats(
            part_key=part_key,
            bucket=bucket,
            count=len(rows),
            min_observations=min_observations,
            min_span_days=min_span_days,
        )
        if not rows:
            return stats

        prices = [row["unit_price"] for row in rows]
        stats.low = prices[0]
        stats.p10 = _quantile(prices, 0.10)
        stats.p25 = _quantile(prices, 0.25)
        stats.median = _quantile(prices, 0.50)
        stats.sold_count = sum(row["sold"] for row in rows)

        cheapest = min(rows, key=lambda row: row["unit_price"])
        stats.all_time_low = cheapest["unit_price"]
        stats.all_time_low_at = _parse(cheapest["last_seen"])

        # Oldest sighting to newest. first_seen on one end and last_seen on the
        # other, so a listing that has sat unsold for a month counts as the
        # month of coverage it actually represents.
        seen = [t for t in (_parse(r["first_seen"]) for r in rows) if t]
        latest = [t for t in (_parse(r["last_seen"]) for r in rows) if t]
        if seen and latest:
            stats.span_days = max(
                (max(latest) - min(seen)).total_seconds() / 86400, 0.0
            )

        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        recent = [
            row["unit_price"]
            for row in rows
            if (parsed := _parse(row["last_seen"])) and parsed >= cutoff
        ]
        if recent:
            stats.recent_median = _quantile(sorted(recent), 0.50)

        return stats

    def total_observations(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM observations").fetchone()
        return int(row["n"])

    def close(self) -> None:
        self.conn.close()

    # --------------------------------------------------------- durable format

    def export_jsonl(self, path: Path) -> int:
        """Write the log as sorted JSONL. Returns rows written.

        SQLite is the working store but a terrible thing to commit: it's binary,
        so every run rewrites the whole file in git's eyes, and a 15-minute cron
        would add ~96 opaque blobs a day forever. JSONL diffs line by line,
        compresses well, appends cleanly, and can be read without the tool --
        which also means a bad parse can be fixed by editing a text file rather
        than by surgery on a database.

        Sorted deterministically so an unchanged log produces an unchanged file
        and the workflow's "did anything change?" check stays meaningful.
        """
        rows = self.conn.execute(
            """
            SELECT part_key, bucket, unit_price, source, listing_id, title,
                   quantity, sold, first_seen, last_seen
              FROM observations
             ORDER BY part_key, bucket, source, listing_id, unit_price
            """
        ).fetchall()

        # Through the core's atomic write. This file is the committed price
        # history and it is rewritten whole; a crash or a cancelled CI job
        # partway through a plain open("w") truncates it, and there is no
        # second copy of a log that took months to accumulate.
        atomic_write(path, "".join(
            json.dumps(dict(row), sort_keys=True) + "\n" for row in rows))
        return len(rows)

    def import_jsonl(self, path: Path) -> int:
        """Load a committed JSONL log into the database. Returns rows read."""
        if not path.exists():
            return 0
        count = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # one corrupt line must not lose the whole history
            self.conn.execute(
                """
                INSERT INTO observations
                    (part_key, bucket, unit_price, source, listing_id, title,
                     quantity, sold, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, listing_id, unit_price) DO NOTHING
                """,
                (
                    row.get("part_key"),
                    row.get("bucket"),
                    row.get("unit_price"),
                    row.get("source"),
                    row.get("listing_id"),
                    row.get("title", ""),
                    row.get("quantity", 1),
                    row.get("sold", 0),
                    row.get("first_seen"),
                    row.get("last_seen"),
                ),
            )
            count += 1
        self.conn.commit()
        return count


def _quantile(sorted_values: list[float], q: float) -> float | None:
    """Linear-interpolation quantile over an already-sorted list."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = q * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _parse(raw: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
