"""Fast-monitor adapter using the existing core, ntfy transports and receipts."""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from dealcore.types import Assessment, Card, Listing
from .native.history import PriceStats
from .native.verdict import Assessment as NativeAssessment
from .plugin import HardwarePlugin
from .prebuilt import Offer, OfferState, PrebuiltHistory, announced_start, dollars, exact_desktop, pacific_time
from .retailers import canonical_product
from .desktop_profile import DEFAULT_PROFILE, DesktopProfile


def community_offer(listing: Listing) -> Offer | None:
    """Announcements remain useful without a price, but never become confirmed retail offers."""
    if not exact_desktop(listing.title):
        return None
    text = listing.title + " " + listing.body
    start = announced_start(text, listing.posted_at)
    upcoming = bool(start or re.search(r"upcoming|starts?\b|begins?\b|tomorrow|announcement|goes live", text, re.I))
    quoted = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", listing.title)
    claimed_price = listing.price if listing.price is not None else dollars(quoted[1]) if quoted else None
    if not upcoming and listing.price is None and not re.search(r"\$\s*\d", text):
        return None
    urls = [listing.url] + re.findall(r"https://[^\s<>\"\)]+", listing.body)
    purchase = listing.url
    for url in urls:
        try:
            purchase = canonical_product(url)
            break
        except ValueError:
            continue
    # A community post can quote an estimate or net price with unknown eligibility.
    # Do not apply that number to the user's confirmed total thresholds.
    return Offer("community", f"{listing.source}:{listing.listing_id}", listing.title, purchase,
                 "Unverified; see original post", "unknown", {"Claimed configuration": listing.title},
                 None, None, "unknown", False, listing.posted_at.isoformat(), starts_at=start,
                 announcement=True, evidence=f"Unverified announcement via {listing.source}: {listing.url}\n{text}",
                 notice_type="upcoming-sale" if upcoming else "live-deal", claimed_price=claimed_price)


def offer_listing(offer: Offer) -> Listing:
    source, _, identity = offer.key.partition(":")
    return Listing(identity, source, offer.title, offer.url, datetime.fromisoformat(offer.observed_at),
                   price=offer.base_price, extra={"prebuilt_offer": offer}, loggable=True)


@dataclass(frozen=True)
class PrebuiltCandidate:
    listing: Listing
    offer: Offer


class MonitorHardwarePlugin(HardwarePlugin):
    def __init__(self, *args, now=None, desktop_profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.desktop_profile = DesktopProfile(desktop_profile or DEFAULT_PROFILE)
        self.now = now or datetime.now(timezone.utc)
        self.pc_history = PrebuiltHistory(self.state_dir)
        self.offers = OfferState(self.state_dir)
        self.pc_details = {}
        self.memory_fits = {}

    def prepare(self, listing):
        if offer := listing.extra.get("prebuilt_offer"):
            self.seen += 1
            self.matched += 1
            return PrebuiltCandidate(listing, offer)
        return super().prepare(listing)

    def read_history(self, candidate):
        if isinstance(candidate, PrebuiltCandidate):
            return self.pc_history.summary(candidate.offer)
        return super().read_history(candidate)

    def judge(self, candidate, stats):
        if not isinstance(candidate, PrebuiltCandidate):
            return super().judge(candidate, stats)
        offer = candidate.offer
        if offer.gpu not in ("5080", "5090"):
            raise ValueError("Selected desktop GPU is ambiguous or unsupported")
        revision, event = self.offers.observe(offer, self.now)
        total, status = offer.total(self.now), offer.sale_status(self.now)
        gpu = offer.gpu
        hunt = self.watched.get("rtx_" + gpu)
        fit = self.desktop_profile.assess_memory(offer)
        target = self.desktop_profile.ceiling(gpu, hunt.target if hunt else None, fit)
        self.memory_fits[offer.key] = fit
        memory_ok = fit.eligible and self.desktop_profile.memory["allow_unverified"]
        trusted = (offer.confirmed and total is not None and total > 0 and status == "live"
                   and offer.condition in ("new", "refurbished", "open_box", "used"))
        target_hit = trusted and memory_ok and target is not None and total <= target
        upcoming = memory_ok and (status == "upcoming" or status == "unverified" and offer.announcement)
        advertised = offer.claimed_price if offer.announcement else total
        if target is not None and advertised is not None and advertised > target:
            upcoming = False
        verdict = self.bands.STRONG if target_hit or upcoming else self.bands.GOOD
        part = next(p for p in self.catalog.PARTS if p.key == "rtx_" + gpu)
        # Complete-PC prices never use a loose-GPU percentile or catalog anchor.
        # Target qualification and the existing same-condition 5% promotion remain.
        detail = NativeAssessment(candidate.listing.listing_id, candidate.listing.source, part,
                                  offer.title, offer.url, total or 0, 1, offer.condition,
                                  candidate.listing.posted_at, verdict, event.upper(), stats,
                                  (total or 0) / part.usable_vram_gb, is_system=True, target_price=target,
                                  target_hit=target_hit, loggable=False, reference_trusted=trusted,
                                  promotion_ceiling=self.bands.GRAIL if trusted and memory_ok else self.bands.GOOD)
        self.pc_details[offer.key] = (offer, event, stats)
        return Assessment(offer.key, total or 0, verdict, detail,
                          rank=(int((fit.potential_gb or 0) >= self.desktop_profile.memory["preferred_gb"]), int(fit.status == "POSSIBLE REUSE"), -(total or 0)),
                          target_override=bool(target_hit or upcoming), alertable=bool(memory_ok and (trusted or upcoming)),
                          loggable=trusted, axes=(("cheapness", stats), ("value", "Complete PC total before tax"),
                                                 ("capability", f"Desktop RTX {gpu}; {fit.summary}")),
                          alert_revision=revision)

    def append(self, pairs):
        ordinary = []
        for candidate, assessment in pairs:
            if isinstance(candidate, PrebuiltCandidate):
                self.pc_history.record(candidate.offer, self.now)
            else:
                ordinary.append((candidate, assessment))
        super().append(ordinary)
        # Save transitions before sending. If delivery fails, the same revision
        # retries; a crash cannot roll stock state back behind a saved receipt.
        self.offers.save()
        self.pc_history.save()

    def undercuts(self, assessments):
        # The core's nonnegative numeric sentinel for a price-less notice is
        # never a $0 computer and must not participate in the native comparison.
        usable = [item for item in assessments if item.key not in self.pc_details
                  or (self.pc_details[item.key][0].confirmed
                      and self.pc_details[item.key][0].total(self.now) is not None
                      and self.pc_details[item.key][0].sale_status(self.now) == "live")]
        yield from super().undercuts(usable)

    def card(self, assessment, signal=None):
        if assessment.key not in self.pc_details:
            return super().card(assessment, signal)
        offer, event, history = self.pc_details[assessment.key]
        total = offer.total(self.now)
        confirmed = offer.confirmed and not offer.announcement and offer.sale_status(self.now) == "live"
        if offer.announcement:
            badge = f"{event.upper()} · UNVERIFIED ANNOUNCEMENT"
        elif offer.stock == "out_of_stock":
            badge = "OUT OF STOCK · SAVED PRICE"
        elif confirmed:
            badge = f"{event.upper()} · CONFIRMED OFFER"
        elif offer.stock == "preorder":
            badge = "PREORDER · AVAILABILITY UNCONFIRMED"
        elif offer.sale_status(self.now) == "upcoming":
            badge = "UPCOMING-SALE · OFFER UNCONFIRMED"
        else:
            badge = "OFFER UNCONFIRMED"
        fit = self.memory_fits[offer.key]
        badge += " · RAM: " + fit.status
        facts = [offer.title, f"Seller: {offer.seller}; condition: {offer.condition}; stock: {offer.stock}"]
        if not offer.announcement:
            facts.append("Price and stock checked: " + pacific_time(offer.observed_at))
        facts.extend(f"{key}: {value}" for key, value in offer.specs.items() if value)
        cost = lambda amount: f"${amount:,.2f}" if amount is not None else "unknown"
        facts += [f"PC: {cost(offer.base_price)}; shipping: {cost(offer.shipping)}; required accessories: {cost(offer.required_accessories)}",
                  "Before tax. Cashback shown separately and excluded from the total.", "Cashback: " + offer.cashback]
        warnings = []
        facts += ["RAM goal: 128GB preferred / 96GB acceptable", fit.summary,
                  "Owned RAM: " + self.desktop_profile.memory["owned_kit"], *fit.evidence]
        warnings.append("Adding your existing 2x32GB kit is not a guaranteed RAM upgrade. Mixed kits may need lower speeds or fail stability testing.")
        if offer.gpu == "5080":
            band = self.desktop_profile.price_band(fit)
            lane = f"Factory {fit.installed_gb}GB" if fit.installed_gb else "Factory RAM unknown"
            facts.append(f"{lane}: watch through ${band['ceiling']:,.0f}; strong-price target ${band['target']:,.0f}. Provisional alert settings, not a purchase recommendation.")
            if total is not None and total > band["target"]:
                facts.append("Within the watch range; above this RAM tier's strong-price target.")
        if offer.coupon:
            facts.append("Coupon: " + offer.coupon.instructions)
            facts.append(f"Coupon discount: {cost(offer.coupon.discount)}; additional required accessories: {cost(offer.coupon.required_accessories)}")
            if not offer.coupon.active(self.now):
                warnings.append("Coupon eligibility/validity unconfirmed; discount excluded from total.")
        else:
            facts.append("Coupon: none confirmed")
        if offer.claimed_price is not None:
            facts.append(f"Community-quoted price: ${offer.claimed_price:,.2f}; total and eligibility unverified")
        if offer.starts_at or offer.announcement:
            facts.append(pacific_time(offer.starts_at))
        if offer.ends_at:
            facts.append("Ends: " + pacific_time(offer.ends_at))
        if not confirmed:
            warnings.append("Verify configuration, seller, stock and checkout total. This is not a confirmed offer.")
            warnings.append(offer.evidence)
        if signal:
            warnings.append(signal)
        return Card(f"RTX {offer.gpu} prebuilt", offer.url, cost(total) if total is not None else "Total unverified",
                    badge, f"{cost(total)} before tax" if total is not None else "Advance/community notice; recheck required",
                    history, tuple(facts), tuple(warnings), priority=self.desktop_profile.priority(offer.gpu, total, fit) if confirmed else 3)

    def persist(self):
        super().persist()
        self.offers.save()
        self.pc_history.save()
