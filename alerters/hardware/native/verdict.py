"""Turning a listing into a buy / pass call.

The Steam version of this asked one question: is this discount good *for this
game*? A hardware listing needs three, because a price with no context is
meaningless and context alone doesn't tell you whether you want the thing.

  1. Is it cheap?      -- price against everything we've logged for that part
  2. Is it good value? -- dollars per GB of VRAM, the currency of local
                          inference, against the rest of its class
  3. Does it help?     -- what it changes about what the desktop can actually
                          load. A $200 RTX 5080 is a wonderful price and a
                          pointless purchase when you already have 18GB.

Cheapness leads, because that's what a deal alerter is for. The other two
modulate: a part that unlocks nothing is capped below the alert threshold no
matter how cheap it is, which is what stops this thing waking you at 3am about
a 16GB card.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum

from .catalog import (
    Kind,
    Part,
    class_median_dollars_per_gb,
    class_median_dollars_per_gb_bandwidth,
)
from .config import Thresholds
from .history import PriceStats
from .rig import Fit, capability_gain, check_fit, host_vram_gb, largest_model_at

# Prices within a dollar are the same price.
DOLLAR = 1.01


class Verdict(IntEnum):
    """Ordered worst to best so alert thresholds can be a simple >= compare."""

    PASS = 0
    FAIR = 1
    GOOD = 2
    STRONG = 3
    EXCEPTIONAL = 4
    GRAIL = 5

    @property
    def label(self) -> str:
        return {
            Verdict.PASS: "PASS",
            Verdict.FAIR: "FAIR",
            Verdict.GOOD: "GOOD",
            Verdict.STRONG: "STRONG BUY",
            Verdict.EXCEPTIONAL: "EXCEPTIONAL",
            Verdict.GRAIL: "GRAIL",
        }[self]


@dataclass
class Assessment:
    listing_id: str
    source: str
    part: Part
    title: str
    url: str

    unit_price: float
    quantity: int
    condition: str
    posted_at: datetime

    verdict: Verdict
    headline: str
    reason: str

    dollars_per_gb: float
    # The same price against capacity *and* speed, in dollars per GB-TB/s.
    # $/GB alone cannot tell a 3090 from a Mac mini; this can, and where the
    # two figures disagree the listing is slow capacity rather than a bargain.
    dollars_per_gb_bandwidth: float = 0.0
    # Where this price sits in our own log, 0-100. None until we have enough.
    percentile: float | None = None
    stats: PriceStats | None = None

    vram_before: float = 0.0
    vram_after: float = 0.0
    unlock: str = ""
    fit: Fit | None = None

    mining_risk: str = "low"
    seller_risk: str = "low"
    is_system: bool = False
    # Several cards named under one price, and one option out of several priced
    # behind one listing. Kept apart from is_system because they are different
    # facts about a listing and the report says something different about each.
    is_bundle: bool = False
    multi_variant: bool = False
    target_price: float | None = None
    target_hit: bool = False
    hunt_name: str = ""
    confidence: str = "low"
    # False when this price must not enter the history log: an unfair sample, a
    # seller we don't trust, or a price so far below the market that it is more
    # likely bait than a bargain. Such a listing is still shown -- your judgment
    # is better than the filter's -- but the distribution never sees it.
    loggable: bool = True

    @property
    def total_price(self) -> float:
        return self.unit_price * self.quantity

    @property
    def score(self) -> tuple[int, bool, float]:
        """Sort key: best verdict, then prices we trust, then cheapest per GB.

        `loggable` sits above dollars-per-GB deliberately. Capping a bait price
        at GOOD isn't enough on its own: a $200 listing beats a real $650 one on
        $/GB by a mile, so within the same verdict the untrustworthy price would
        still take the top slot and the subject line. A price the tool won't
        record is a price it won't rank first either.
        """
        return (int(self.verdict), self.loggable, -self.dollars_per_gb)


def _fmt(amount: float) -> str:
    return money(amount, whole_above=100)


from dealcore.verdict import ago as _ago


def assess(
    *,
    listing_id: str,
    source: str,
    part: Part,
    title: str,
    url: str,
    unit_price: float,
    quantity: int,
    condition: str,
    posted_at: datetime,
    stats: PriceStats,
    thresholds: Thresholds,
    mining_risk: str = "low",
    seller_risk: str = "low",
    seller_note: str = "",
    loggable: bool = True,
    is_system: bool = False,
    is_bundle: bool = False,
    multi_variant: bool = False,
    target_price: float | None = None,
    hunt_name: str = "",
    psu_headroom_w: int = 150,
) -> Assessment | None:
    """Score one listing. Returns None when the price is implausible."""
    # What "implausible" is measured against. The catalog constant is a guess
    # until the log can answer for itself, and on 2026-08-08 the guesses proved
    # to be 35-58% low across the board -- twelve of sixteen sat below the
    # cheapest price ever observed for their part. The 1.6x ceiling therefore
    # landed under the market median and threw away 67% of matched listings as
    # "too expensive", including real single cards. The fix isn't a better
    # constant, it's to stop depending on one: once a part has enough
    # observations to rank against, its own median is the anchor.
    ranked = bool(stats.trustworthy and stats.median)
    anchor = stats.median if ranked else part.reference_price
    # Tolerance follows confidence in the anchor: tight around a median the log
    # earned, loose around a constant nobody has verified.
    ceiling = thresholds.max_price_ratio if ranked else thresholds.reference_max_price_ratio
    ratio = unit_price / anchor
    # A whole machine containing the card is priced for the machine, and a
    # bundle for everything in it. Neither is ever logged, so the ceiling
    # protects nothing here and only hid a real class of listing -- an EPYC box
    # with 4x RTX PRO 6000 read as one absurd card.
    too_dear = ratio > ceiling and not (is_system or is_bundle)
    if too_dear or ratio < thresholds.min_price_ratio:
        # Either a mispriced accessory or a scam. Both are noise, and both would
        # corrupt the history log if they got through.
        return None

    # Plausible enough to look at, too cheap to believe. Shown, never recorded.
    #
    # `loggable` is the single answer to "does this price enter the history".
    # is_system is a prebuilt: a machine's price says nothing about the card
    # inside it. is_bundle is several cards under one price, which cannot be
    # attributed to any one of them. multi_variant is the same failure a step
    # earlier -- the source saying this price belongs to one option out of
    # several sold under one title, without saying which. All three stay
    # visible, since parting out a cheap prebuilt is a real way to buy a GPU
    # and bundles are often where the good deals are, but none is an
    # observation.
    suspicious_price = ratio < thresholds.suspicious_price_ratio
    if (
        suspicious_price
        or seller_risk == "high"
        or condition == "parts"
        or is_system
        or is_bundle
        or multi_variant
    ):
        loggable = False

    dollars_per_gb = unit_price / part.vram_gb
    dollars_per_gb_bandwidth = unit_price / part.capacity_bandwidth
    percentile = stats.percentile_of(unit_price) if stats.trustworthy else None
    before, after, unlock = capability_gain(part)
    fit = check_fit(part, psu_headroom_w=psu_headroom_w)
    target_hit = target_price is not None and unit_price <= target_price + DOLLAR

    verdict, headline, reason = _decide(
        part=part,
        unit_price=unit_price,
        dollars_per_gb=dollars_per_gb,
        dollars_per_gb_bandwidth=dollars_per_gb_bandwidth,
        percentile=percentile,
        stats=stats,
        thresholds=thresholds,
        unlock=unlock,
        before=before,
        after=after,
        mining_risk=mining_risk,
        seller_risk=seller_risk,
        seller_note=seller_note,
        suspicious_price=suspicious_price,
        is_system=is_system,
        is_bundle=is_bundle,
        multi_variant=multi_variant,
        target_hit=target_hit,
        target_price=target_price,
        condition=condition,
    )
    reason = " ".join(reason.split())

    return Assessment(
        listing_id=listing_id,
        source=source,
        part=part,
        title=title,
        url=url,
        unit_price=unit_price,
        quantity=quantity,
        condition=condition,
        posted_at=posted_at,
        verdict=verdict,
        headline=headline,
        reason=reason,
        dollars_per_gb=dollars_per_gb,
        dollars_per_gb_bandwidth=dollars_per_gb_bandwidth,
        percentile=percentile,
        stats=stats,
        vram_before=before,
        vram_after=after,
        unlock=unlock,
        fit=fit,
        mining_risk=mining_risk,
        seller_risk=seller_risk,
        loggable=loggable,
        is_system=is_system,
        is_bundle=is_bundle,
        multi_variant=multi_variant,
        target_price=target_price,
        target_hit=target_hit,
        hunt_name=hunt_name,
        confidence="history" if percentile is not None else "reference",
    )


def _decide(
    *,
    part: Part,
    unit_price: float,
    dollars_per_gb: float,
    dollars_per_gb_bandwidth: float,
    percentile: float | None,
    stats: PriceStats,
    thresholds: Thresholds,
    unlock: str,
    before: float,
    after: float,
    mining_risk: str,
    seller_risk: str,
    seller_note: str,
    suspicious_price: bool,
    is_system: bool,
    is_bundle: bool,
    multi_variant: bool,
    target_hit: bool,
    target_price: float | None,
    condition: str,
) -> tuple[Verdict, str, str]:
    """The actual call, plus the sentences explaining it."""

    class_median = class_median_dollars_per_gb(part.kind)
    value_note = _value_sentence(
        part,
        dollars_per_gb,
        class_median,
        dollars_per_gb_bandwidth,
        class_median_dollars_per_gb_bandwidth(part.kind),
    )

    if percentile is not None:
        verdict, headline, reason = _decide_from_history(
            part, unit_price, percentile, stats, thresholds
        )
    else:
        verdict, headline, reason = _decide_from_reference(
            part, unit_price, dollars_per_gb, class_median, stats, thresholds
        )

    # Both paths lean on `reference_price` -- one as the whole answer, one as
    # the sanity check on the percentile -- so an unverified anchor weakens both
    # equally. Half the catalog is still estimates, and on 2026-08-17 those sat
    # on a visibly different scale from the sold-sourced entries and produced
    # most of the candidate alerts, precisely because nobody had checked them.
    # An estimate can still say "this looks cheap"; it may not ring a phone.
    if part.reference_basis != "sold" and verdict > Verdict.STRONG:
        verdict = Verdict.STRONG
        reason += (
            f" Held below push: the {_fmt(part.reference_price)} it is measured "
            "against is an unverified estimate rather than a sold average."
        )
    # An anchor the market has walked away from is worth no more than an
    # unverified one, and goes quiet the same way until the number is refreshed.
    elif _anchor_is_stale(part, stats, thresholds) and verdict > Verdict.STRONG:
        verdict = Verdict.STRONG
        reason += (
            f" Held below push: the last 30 days of asks median "
            f"{_fmt(stats.recent_median)}, at or below the "
            f"{_fmt(part.reference_price)} sold average this is measured "
            "against, so that anchor is treated as out of date."
        )

    reason = f"{reason} {value_note}"

    # ------------------------------------------------------------ modifiers

    # A part that doesn't grow the pool is a sidegrade at best. This is the
    # rule that keeps 16GB cards out of your notifications entirely.
    # The unlock sentence is deliberately *not* appended here -- it travels as
    # its own field so the report can place it next to the VRAM bar instead of
    # burying it at the end of a paragraph.
    if after <= before + 1:
        verdict = min(verdict, Verdict.GOOD)
        reason += (
            f" Capped: {part.vram_gb}GB against the {before:.0f}GB already in the "
            "desktop is not an upgrade, however good the price."
        )

    if mining_risk == "high":
        verdict = max(Verdict.PASS, Verdict(max(int(verdict) - 1, 0)))
        reason += (
            " Downgraded one level: the listing reads like an ex-mining card. "
            "Worth buying anyway if the seller allows returns, but assume the "
            "fans and thermal pads are finished."
        )
    elif mining_risk == "moderate":
        reason += " Some mining signals in the listing -- ask before buying."

    # Seller trust rides the same downgrade rail as mining risk rather than a
    # hard reject: a legitimate new seller exists, and filtering them out
    # silently would hide real deals while teaching you nothing.
    #
    # One level is enough when the price is ordinary and not nearly enough when
    # it isn't. An untrusted seller asking a suspiciously good price is not two
    # independent facts to be discounted separately, it is the scam profile
    # itself -- and one level down from EXCEPTIONAL lands on STRONG, which is
    # the digest threshold. That is exactly how a zero-feedback account, on an
    # account opened the same month, put a $4,996 Mac Studio in the inbox on
    # 2026-08-17. So when both halves of the profile are present the listing is
    # capped instead: still visible, never alerting.
    if seller_risk == "high":
        alerting_price = unit_price <= part.reference_price * thresholds.reference_strong_ratio
        if alerting_price:
            verdict = min(verdict, Verdict.GOOD)
            reason += (
                f" Capped: {seller_note or 'the seller looks risky'}, and the price "
                "is low enough to alert on. A price that good from a seller with no "
                "record is the shape of bait, so it is shown but never escalated. "
                "Not recorded in the price history either way."
            )
        else:
            verdict = max(Verdict.PASS, Verdict(max(int(verdict) - 1, 0)))
            reason += (
                f" Downgraded one level: {seller_note or 'the seller looks risky'}. "
                "Not recorded in the price history either way."
            )
    elif seller_risk == "moderate" and seller_note:
        reason += f" {seller_note} -- worth a look before you commit."

    # Deliberately not a rejection. The band that scam listings live in is the
    # same band a genuine steal lives in, so this says so plainly and lets you
    # decide, while keeping the number out of the log.
    #
    # Capped rather than downgraded a level, because the mispriced listings are
    # by definition the cheapest thing in the run: they score best and would
    # headline every digest forever. One level down from EXCEPTIONAL is still
    # STRONG, which is the push threshold -- so a $200 water block would ring
    # your phone. GOOD keeps it visible in the digest, off the subject line,
    # and out of push entirely. If the tool won't stake its own history on a
    # price, that price has no business leading your email.
    if suspicious_price:
        verdict = min(verdict, Verdict.GOOD)
        reason += (
            " This is far enough under the going rate to be bait rather than a "
            "bargain, so it is shown but never recorded, and held back from the "
            "top of the digest. Check the seller's history and that the photos "
            "aren't stock images before committing."
        )

    if is_system:
        verdict = min(verdict, Verdict.GOOD)
        reason += (
            " This is a complete system containing the card, not a bare card, so "
            "the price covers a lot more than the GPU and isn't comparable."
        )
    # Its own sentence, because it used to borrow the one above and a listing
    # naming two graphics cards was told it was a complete system.
    elif is_bundle:
        verdict = min(verdict, Verdict.GOOD)
        reason += (
            " This listing names more than one card under a single price, so what "
            "is being asked for the one above can't be separated out. Often worth "
            "it anyway -- read the listing."
        )

    # Not capped, unlike the two above. Where a bare card's title names one
    # card, every option under it is that card in some other condition or
    # capacity, so the price is a real price for a real thing and holding a
    # genuine steal out of push would cost more than the caveat does. Where the
    # title names several cards, or the listing is a whole machine, it never
    # reaches here at all -- match() drops both.
    if multi_variant:
        reason += (
            " The seller offers several options under this one listing and eBay "
            "quotes whichever it chose to show, so confirm which option this "
            "price buys. Not recorded in the price history either way."
        )

    if condition == "parts":
        return (
            Verdict.PASS,
            "Sold for parts",
            "Listed as for-parts or not-working. Not a deal at any price.",
        )

    # An explicit target gets through, the way targets.json did in the Steam
    # project -- you've already decided this price is worth knowing about.
    #
    # Except when we don't believe the price. Every listing flagged above is
    # under target *because* it's mispriced, so an unguarded override would
    # promote precisely the listings just held back, restore them to STRONG --
    # the push threshold -- and ring your phone about a $200 water block. The
    # target says "this price is worth knowing about", not "trust any number
    # below it". The listing still shows, still says it beat the target; it
    # just doesn't get escalated on the strength of a price we won't record.
    untrusted = suspicious_price or seller_risk == "high"
    if target_hit and verdict < Verdict.STRONG and not untrusted:
        verdict = Verdict.STRONG
        headline = f"{_fmt(unit_price)} -- under your {_fmt(target_price)} target"

    return verdict, headline, reason


def _decide_from_history(
    part: Part,
    unit_price: float,
    percentile: float,
    stats: PriceStats,
    thresholds: Thresholds,
) -> tuple[Verdict, str, str]:
    """The real answer, once the log has enough observations to give one.

    Rank alone is not the answer, though. A percentile is a statement about the
    other listings, not about the thing: the cheapest 20% of any distribution is
    the cheapest 20% whether the market is generous or uniformly terrible, so
    ranking by itself promises a steady supply of STRONG buys forever. Worse,
    every price in the log is an *asking* price, and asks run well above what
    things sell for -- so the cheapest decile of asks can still sit above real
    transaction value.

    So the percentile is necessary and not sufficient: the price also has to be
    cheap against what the part is worth, and the weaker of the two answers
    wins. In a market where nothing is a good deal, nothing alerts.
    """
    basis = (
        f"Against {stats.count} recorded {stats.bucket} prices for this part"
        + (f", {stats.sold_count} of them confirmed sales" if stats.sold_count else "")
        + "."
    )
    context = ""
    if stats.all_time_low is not None:
        context = (
            f" The cheapest we have ever seen was {_fmt(stats.all_time_low)} "
            f"({_ago(stats.all_time_low_at)})."
        )
    if stats.recent_median and stats.median:
        drift = (stats.recent_median - stats.median) / stats.median * 100
        if abs(drift) >= 8:
            direction = "rising" if drift > 0 else "falling"
            context += (
                f" Prices are {direction}: the last 30 days median "
                f"{_fmt(stats.recent_median)} against {_fmt(stats.median)} overall."
            )

    if percentile <= thresholds.grail_pct:
        rank_verdict = Verdict.GRAIL
        rank_headline = f"{_fmt(unit_price)} -- cheapest {percentile:.0f}% we have ever logged"
        rank_reason = "Nothing in the log is meaningfully cheaper."
    elif percentile <= thresholds.exceptional_pct:
        rank_verdict = Verdict.EXCEPTIONAL
        rank_headline = f"{_fmt(unit_price)} -- top {percentile:.0f}% of prices seen"
        rank_reason = "Only about one listing in ten comes in this low."
    elif percentile <= thresholds.strong_pct:
        rank_verdict = Verdict.STRONG
        rank_headline = (
            f"{_fmt(unit_price)} -- cheaper than {100 - percentile:.0f}% of listings"
        )
        rank_reason = "Clearly below the going rate."
    elif percentile <= thresholds.good_pct:
        rank_verdict = Verdict.GOOD
        rank_headline = f"{_fmt(unit_price)} -- modestly below the going rate"
        rank_reason = "Better than average, not remarkable."
    else:
        median = stats.median or unit_price
        rank_verdict = Verdict.FAIR if percentile <= 60 else Verdict.PASS
        rank_headline = f"{_fmt(unit_price)} -- around or above the usual {_fmt(median)}"
        rank_reason = "History says wait."

    # The second opinion. Cheap *for what is currently listed* is not the same
    # claim as cheap *for what the thing is worth*, and only the second one is
    # worth waking up for.
    anchor_verdict = _verdict_from_anchor(unit_price, part.reference_price, thresholds)
    if anchor_verdict >= rank_verdict:
        return rank_verdict, rank_headline, f"{basis} {rank_reason}{context}"

    return (
        anchor_verdict,
        f"{_fmt(unit_price)} -- cheap against this listing pool, not against the part",
        f"{basis} {rank_reason} Held back anyway: at "
        f"{unit_price / part.reference_price:.2f}x the {_fmt(part.reference_price)} "
        "this part is worth, the pool it is beating is simply an expensive one."
        f"{context}",
    )


def _verdict_from_anchor(
    unit_price: float, anchor: float, thresholds: Thresholds
) -> Verdict:
    """How good this price is against real transaction value, as a ratio.

    Shared by both paths on purpose. The reference path uses it as the whole
    answer; the history path uses it as a second opinion the percentile has to
    agree with. One definition of "cheap against what it's worth" means the two
    paths cannot drift into disagreeing about the same listing.
    """
    ratio = unit_price / anchor
    if ratio <= thresholds.reference_grail_ratio:
        return Verdict.GRAIL
    if ratio <= thresholds.reference_exceptional_ratio:
        return Verdict.EXCEPTIONAL
    if ratio <= thresholds.reference_strong_ratio:
        return Verdict.STRONG
    if ratio <= thresholds.reference_good_ratio:
        return Verdict.GOOD
    if ratio <= thresholds.reference_fair_ratio:
        return Verdict.FAIR
    return Verdict.PASS


def _anchor_is_stale(part: Part, stats: PriceStats, thresholds: Thresholds) -> bool:
    """Whether recent asking prices have caught up with a sold anchor.

    Asks sit above what a thing sells for, so a sold average they have fallen
    to is describing a market that has moved on. Measured 2026-09-17, after the
    M5 Ultra shipped: Mac Studio M3 Ultra asks sat at 0.95-1.01x their August
    sold averages, while the 512GB part that successor did not replace still
    asked 1.78x its own.
    """
    if part.reference_basis != "sold" or stats.recent_median is None:
        return False
    if stats.recent_count < thresholds.stale_anchor_min_recent:
        return False
    return stats.recent_median <= part.reference_price * thresholds.stale_anchor_ask_ratio


def _decide_from_reference(
    part: Part,
    unit_price: float,
    dollars_per_gb: float,
    class_median: float,
    stats: PriceStats,
    thresholds: Thresholds,
) -> tuple[Verdict, str, str]:
    """The fallback while the log is still filling up.

    Deliberately more conservative than the history path: it tops out at
    EXCEPTIONAL rather than GRAIL, because "cheap against a reference price I
    typed into a config file" is a weaker claim than "cheapest of 200 observed
    listings" and shouldn't be dressed up as the same thing.

    The bands are ratios against *sold* value, and they mean what they say only
    because `reference_price` is sold-sourced. Where it isn't -- see
    `Part.reference_basis` -- the result is capped below push, because an
    estimate is not evidence and shouldn't be allowed to ring a phone.
    """
    ratio = unit_price / part.reference_price
    seen = (
        f"Only {stats.count} price{'s' if stats.count != 1 else ''} logged for this "
        f"part so far, which is too few to rank against"
        if stats.count
        else "No price history logged for this part yet"
    )
    basis = (
        f"{seen}, so this is measured against a {_fmt(part.reference_price)} "
        f"reference rather than real observations."
    )

    # Capped at EXCEPTIONAL on purpose. The anchor helper will hand out GRAIL,
    # but "cheapest thing I have ever recorded" is a claim only the history can
    # make -- against a constant, the honest ceiling is one notch lower.
    verdict = min(
        _verdict_from_anchor(unit_price, part.reference_price, thresholds),
        Verdict.EXCEPTIONAL,
    )

    if verdict >= Verdict.STRONG:
        headline = f"{_fmt(unit_price)} -- {(1 - ratio) * 100:.0f}% under reference"
    elif verdict is Verdict.GOOD:
        headline = f"{_fmt(unit_price)} -- somewhat under reference"
    elif verdict is Verdict.FAIR:
        headline = f"{_fmt(unit_price)} -- about the going rate"
    else:
        headline = (
            f"{_fmt(unit_price)} -- above the {_fmt(part.reference_price)} reference"
        )
    return verdict, headline, basis


def _value_sentence(
    part: Part,
    dollars_per_gb: float,
    class_median: float,
    dollars_per_gb_bandwidth: float,
    class_median_bandwidth: float,
) -> str:
    """Capacity per dollar, then capacity *and speed* per dollar.

    Capacity per dollar on its own is a trap: a 128GB unified box looks four
    times better than a 3090 by that measure and generates tokens a third as
    fast. The docstring used to promise that saying both numbers together was
    the honest version, and then said one number and a caveat. The combined
    index is the second number -- price over GB x TB/s -- so the sentence
    prices the thing the first measure ignores.

    The interesting case is the two disagreeing. Cheap per GB and dear per
    GB-TB/s is the signature of slow memory, which is the purchase this tool
    exists to stop you making by accident at 3am.
    """

    def standing(value: float, median: float) -> tuple[str, float] | None:
        """Where a figure sits against its class, as a phrase and a percentage.

        Lower is better for both measures, so a negative delta is the good
        direction and the phrase says so in words rather than making the reader
        remember which way the sign points.
        """
        if median <= 0:
            return None
        delta = (value - median) / median * 100
        if delta <= -20:
            return f"{abs(delta):.0f}% better than typical for its class", delta
        if delta >= 20:
            return f"{delta:.0f}% worse than typical for its class", delta
        return "about typical for its class", delta

    capacity = standing(dollars_per_gb, class_median)
    combined = standing(dollars_per_gb_bandwidth, class_median_bandwidth)

    clauses = [f"{_fmt(dollars_per_gb)}/GB of VRAM"]
    if capacity:
        clauses.append(capacity[0])
    # Not .capitalize() -- that lowercases the rest of the string and turns
    # "$24/GB of VRAM" into "$24/gb of vram".
    joined = ", ".join(clauses)
    sentence = joined[:1].upper() + joined[1:] + "."

    index = f"{_fmt(dollars_per_gb_bandwidth)} per GB-TB/s"
    sentence += (
        f" Counting bandwidth too, {index}"
        + (f", {combined[0]}." if combined else ".")
    )

    if capacity and combined and capacity[1] <= -20 and combined[1] >= 20:
        sentence += (
            f" Cheap per gigabyte and dear once speed counts, at "
            f"{part.bandwidth_gb_s:,} GB/s: this holds large models rather than "
            "running them quickly."
        )
    elif capacity and combined and combined[1] <= -20 and capacity[1] >= 20:
        sentence += (
            f" Dear per gigabyte but cheap once speed counts, at "
            f"{part.bandwidth_gb_s:,} GB/s: you are buying bandwidth here, not "
            "capacity."
        )
    elif part.kind is Kind.UNIFIED:
        sentence += (
            f" Remember the tradeoff: {part.bandwidth_gb_s} GB/s here against "
            "roughly 1,000 GB/s on a discrete card, so generation is slower per "
            "token even though far more fits."
        )
    return sentence


def summarize_unlock(vram_gb: float) -> str:
    """What a given amount of VRAM can hold, for the digest header."""
    model = largest_model_at(vram_gb)
    if model is None:
        return f"{vram_gb:.0f}GB -- below the smallest model on the ladder at Q4."
    return f"{vram_gb:.0f}GB -- enough for {model.name} at Q4 with context headroom."


def current_ceiling() -> str:
    return summarize_unlock(host_vram_gb())

from dealcore.verdict import money
