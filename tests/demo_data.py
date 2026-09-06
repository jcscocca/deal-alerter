"""Sample assessments so `--demo` renders a realistic report with no network.

Useful for working on report.py without waiting on four HTTP sources, and for
seeing what the digest looks like before the price log has anything in it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from alerters.hardware.native.catalog import BY_KEY
from alerters.hardware.native.config import Thresholds
from alerters.hardware.native.history import PriceStats
from alerters.hardware.native.verdict import Assessment, assess


def _stats(part_key: str, count: int, low: float, p10: float, p25: float, median: float) -> PriceStats:
    return PriceStats(
        part_key=part_key,
        bucket="used",
        count=count,
        low=low,
        p10=p10,
        p25=p25,
        median=median,
        all_time_low=low,
        all_time_low_at=datetime.now(timezone.utc) - timedelta(days=48),
        recent_median=median * 1.04,
        sold_count=count // 3,
    )


def build_demo_assessments() -> list[Assessment]:
    now = datetime.now(timezone.utc)
    thresholds = Thresholds()
    out: list[Assessment] = []

    # A genuinely exceptional 3090: cheaper than anything logged, and the first
    # thing that makes a 70B fit on the desktop.
    out.append(
        assess(
            listing_id="demo1",
            source="reddit/buildapcsales",
            part=BY_KEY["rtx_3090"],
            title="[GPU] EVGA RTX 3090 FTW3 Ultra 24GB - $585 (eBay, open box)",
            url="https://example.invalid/3090",
            unit_price=585.0,
            quantity=1,
            condition="used",
            posted_at=now - timedelta(minutes=12),
            stats=_stats("rtx_3090", 64, 575.0, 610.0, 665.0, 745.0),
            thresholds=thresholds,
            mining_risk="low",
            target_price=650.0,
            hunt_name="RTX 3090 (pair up)",
        )
    )

    # The recommendation, at a real discount, from a source that actually
    # carries them.
    out.append(
        assess(
            listing_id="demo2",
            source="ebay",
            part=BY_KEY["rtx_pro_6000_blackwell_maxq"],
            title="NVIDIA RTX PRO 6000 Blackwell Max-Q 96GB GDDR7 Workstation GPU",
            url="https://example.invalid/pro6000",
            unit_price=7100.0,
            quantity=1,
            condition="new",
            posted_at=now - timedelta(hours=3),
            stats=PriceStats(part_key="rtx_pro_6000_blackwell_maxq", bucket="new", count=2),
            thresholds=thresholds,
            target_price=7500.0,
            hunt_name="RTX PRO 6000 Blackwell",
        )
    )

    # A lot of four A6000s -- unit price is what matters, and the mining
    # signals should visibly knock it down a level.
    out.append(
        assess(
            listing_id="demo3",
            source="ebay",
            part=BY_KEY["rtx_a6000"],
            title="Lot of 4 NVIDIA RTX A6000 48GB - mining rig pull, tested working",
            url="https://example.invalid/a6000",
            unit_price=2450.0,
            quantity=4,
            condition="used",
            posted_at=now - timedelta(hours=9),
            stats=_stats("rtx_a6000", 31, 2380.0, 2500.0, 2760.0, 3150.0),
            thresholds=thresholds,
            mining_risk="high",
            hunt_name="48GB pro cards",
        )
    )

    # Apple refurb: great capacity per dollar, and the bandwidth caveat should
    # show up in the reasoning rather than being quietly omitted.
    out.append(
        assess(
            listing_id="demo4",
            source="apple-refurb",
            part=BY_KEY["mac_studio_m3_ultra_256"],
            title="Refurbished Mac Studio Apple M3 Ultra chip 256GB",
            url="https://example.invalid/macstudio",
            unit_price=4589.0,
            quantity=1,
            condition="refurbished",
            posted_at=now - timedelta(hours=1),
            stats=_stats("mac_studio_m3_ultra_256", 12, 4400.0, 4520.0, 4700.0, 4990.0),
            thresholds=thresholds,
            hunt_name="Mac Studio (big memory)",
        )
    )

    # A 5080 at a fine price that is nonetheless pointless -- the capability cap
    # should keep this out of the push tier no matter how cheap it gets.
    out.append(
        assess(
            listing_id="demo5",
            source="slickdeals",
            part=BY_KEY["rtx_5080"],
            title="MSI RTX 5080 16GB Gaming Trio OC - $749",
            url="https://example.invalid/5080",
            unit_price=749.0,
            quantity=1,
            condition="new",
            posted_at=now - timedelta(hours=20),
            stats=_stats("rtx_5080", 44, 720.0, 760.0, 830.0, 940.0),
            thresholds=thresholds,
            hunt_name="Anything with lots of VRAM, cheap",
        )
    )

    return [item for item in out if item is not None]
