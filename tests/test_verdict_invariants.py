"""Safety invariants over every combination of risk flags.

_decide() is a chain of order-dependent modifiers, and its worst historical bug
was positional: the target override ran last and re-promoted listings the trust
caps had just held back. The ordering is deliberate (a sidegrade with mining
wear should end below a clean sidegrade), so rather than restructure it, this
grid pins the properties that must survive any future reordering:

  1. for-parts is PASS, always
  2. an untrusted price (bait-band or high-risk seller) never reaches STRONG --
     the push threshold -- no matter what else is true of the listing
  3. untrusted prices are never logged
  4. a trusted in-band price is logged

If a new modifier breaks one of these, the failure names the exact flag
combination that did it.
"""

from __future__ import annotations

import itertools

from datetime import datetime, timezone

import pytest

from alerters.hardware.native.catalog import BY_KEY

PART = BY_KEY["rtx_3090"]
from alerters.hardware.native.config import Thresholds
from alerters.hardware.native.history import PriceStats
from alerters.hardware.native.verdict import Verdict, assess

# Ratios, not dollars. Pinning literal prices couples every case to whatever
# reference_price happens to be, so a catalog recalibration silently turns a
# "credible price" fixture into a bait-band one -- which is exactly what
# happened when the constants were corrected from sold data on 2026-08-08.
BAIT = PART.reference_price * 0.27     # inside the suspicious band
CREDIBLE = PART.reference_price * 0.87  # plainly believable
GRID = list(
    itertools.product(
        [BAIT, CREDIBLE],                # unit_price
        ["low", "moderate", "high"],     # mining_risk
        ["low", "moderate", "high"],     # seller_risk
        [None, 650.0],                   # target_price
        [False, True],                   # is_system
        ["used", "new", "parts"],        # condition
    )
)


def run(price, mining, seller, target, system, condition):
    part = PART
    return assess(
        listing_id="x",
        source="test",
        part=part,
        title="t",
        url="u",
        unit_price=price,
        quantity=1,
        condition=condition,
        posted_at=datetime.now(timezone.utc),
        stats=PriceStats(part_key=part.key, bucket="used", count=0),
        thresholds=Thresholds(),
        mining_risk=mining,
        seller_risk=seller,
        is_system=system,
        target_price=target,
    )


@pytest.mark.parametrize("combo", GRID, ids=lambda c: "/".join(map(str, c)))
def test_invariants(combo) -> None:
    price, mining, seller, target, system, condition = combo
    item = run(*combo)
    assert item is not None  # both grid prices are inside the plausible band

    suspicious = price == BAIT
    untrusted = suspicious or seller == "high"

    if condition == "parts":
        assert item.verdict == Verdict.PASS
        assert not item.loggable
        return

    if untrusted:
        assert item.verdict < Verdict.STRONG, (
            f"untrusted price reached push level via {combo}"
        )
        assert not item.loggable, f"untrusted price marked loggable via {combo}"
    elif not system:
        assert item.loggable, f"trusted bare-card price not loggable via {combo}"
