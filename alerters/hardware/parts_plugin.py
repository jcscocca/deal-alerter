"""Active component and display price watches, independent of build completion."""
from __future__ import annotations

import re
import math
import tomllib
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from dealcore.types import Assessment, Card
from .native.verdict import Assessment as NativeAssessment
from .plugin import HardwarePlugin
from .prebuilt import pacific_time
from .memory import LAYOUTS as SODIMM_LAYOUTS, DESKTOP_LAYOUTS

DEFAULT_WATCHES = Path(__file__).resolve().parents[2] / "config/parts-watch.toml"


def fresh_item_stock(shopping, now, key):
    try:
        age = (now - datetime.fromisoformat(shopping.get("availability_checked_at"))).total_seconds()
    except (TypeError, ValueError):
        return False
    return (0 <= age <= 1200 and shopping.get("available") is True
            and shopping.get("verified_price_watch") == key)


class PartsHardwarePlugin(HardwarePlugin):
    track_complete_systems = False
    require_capacity_upgrade = False

    def __init__(self, *args, now=None, price_watches=None, **kwargs):
        super().__init__(*args, **kwargs)
        # The retained Apple adapter watches complete Mac systems only.
        self.sources = tuple(source for source in self.sources if source.name != "apple-refurb")
        self._fixed_now = now is not None
        self.now = now or datetime.now(timezone.utc)
        self.card_prices = tomllib.loads((price_watches or DEFAULT_WATCHES).read_text(encoding="utf-8"))["price"]
        for band in self.card_prices.values():
            if not (0 < band["urgent"] <= band["target"] <= band["ceiling"]):
                self.close()
                raise ValueError("Invalid component price thresholds")
        self.card_price_watches, self.card_stock = {}, {}
        self.sodimm_watches, self.sodimm_stock = {}, {}
        self.verified_offers = {}
        # CLI runs and monitor runs share the same verified-standout default.
        self.options = replace(self.options, notify_filter=self.notification_allowed, include_others=False)

    def prepare(self, listing):
        from alerters.techscout.scope import allowed_title
        if not allowed_title(listing.title):
            self.seen += 1
            return None
        return super().prepare(listing)

    def add_manual(self, **fields):
        from alerters.techscout.scope import allowed_title
        if not allowed_title(fields.get("title", "")):
            raise ValueError("Hardware watches standalone parts and displays; complete machines are retired")
        return super().add_manual(**fields)

    def judge(self, candidate, stats):
        if not self._fixed_now:
            self.now = datetime.now(timezone.utc)
        assessment = self._judge(candidate, stats)
        if assessment is None:
            return None
        listing, detail = candidate.listing, assessment.detail
        key = detail.part.key
        if assessment.key in self.display_watches:
            key = self.display_watches[assessment.key][0].model
        shopping = listing.extra.get("shopping", {})
        shipping, price = shopping.get("shipping"), shopping.get("item_price")
        known_cost = (type(shipping) in (int, float) and math.isfinite(shipping) and shipping >= 0
                      and type(price) in (int, float) and math.isfinite(price) and price > 0
                      and abs(price + shipping - assessment.price) < 0.02)
        self.verified_offers[assessment.key] = bool(
            listing.source == "ebay" and fresh_item_stock(shopping, self.now, key)
            and shopping.get("stock") == "in_stock" and known_cost
            and listing.extra.get("seller") and listing.seller_risk == "low"
            and detail.condition in ("new", "open_box", "used", "refurbished")
            and detail.quantity == 1 and not listing.sold and not listing.multi_variant
            and not detail.is_system and not detail.is_bundle)
        return assessment

    def notification_allowed(self, assessment, *, include_target_notices=False):
        if not self.verified_offers.get(assessment.key, False):
            return False
        from .shopping_activity import standout_basis
        if standout_basis(self, assessment, True):
            return True
        return include_target_notices and assessment.target_override

    def _judge(self, candidate, stats):
        if candidate.match.part.key in SODIMM_LAYOUTS:
            return self.judge_sodimm(candidate)
        assessment = super().judge(candidate, stats)
        if assessment is None:
            return None
        item, listing = assessment.detail, candidate.listing
        shopping = listing.extra.get("shopping", {})
        band = self.card_prices.get(item.part.key)
        if item.is_system or item.is_bundle:
            return assessment
        if band is None:
            if listing.source == "ebay" and not item.part.is_product:
                verified = (fresh_item_stock(shopping, self.now, item.part.key)
                            and item.seller_risk == "low" and not item.multi_variant and not listing.sold)
                self.card_stock[assessment.key] = {name: shopping.get(name) for name in
                                                 ("available", "stock", "availability_checked_at", "availability_note")}
                return replace(assessment, alertable=assessment.alertable and verified,
                               target_override=assessment.target_override and verified)
            return assessment
        # Explicit new-card price notices are separate from the native
        # model-capacity recommendation. Keep its factual grade/history,
        # and never bypass identity, condition, seller or source vetoes.
        # Every eBay card notice needs fresh exact-item stock evidence.
        # Best Match asks are loggable; that does not establish availability.
        verified = listing.source == "ebay" and fresh_item_stock(shopping, self.now, item.part.key)
        anchor = stats.median if stats.trustworthy and stats.median else item.part.reference_price
        credible = item.unit_price >= anchor * self.cfg.thresholds.suspicious_price_ratio
        eligible = (item.condition == "new" and item.quantity == 1 and credible
                    and (verified if listing.source == "ebay" else item.loggable and listing.loggable)
                    and not listing.sold
                    and shopping.get("available") is not False
                    and not item.multi_variant and item.seller_risk == "low"
                    and item.mining_risk == "low")
        hit = eligible and item.unit_price <= band["ceiling"]
        self.card_price_watches[assessment.key] = band
        if listing.source == "ebay":
            self.card_stock[assessment.key] = {name: shopping.get(name) for name in
                                             ("available", "stock", "availability_checked_at", "availability_note")}
        return replace(assessment, alertable=hit, target_override=hit,
                       rank=(int(item.part.key == "rtx_5090"), -item.unit_price),
                       axes=(("cheapness", f"Explicit new-card price watch through ${band['ceiling']:,.0f}"),
                             ("value", "Listed card price before tax; verify delivery and checkout"),
                             ("capability", item.unlock)))

    def judge_sodimm(self, candidate):
        listing, part = candidate.listing, candidate.match.part
        shopping = listing.extra.get("shopping", {})
        price, limit = candidate.match.unit_price, candidate.hunt.target
        if price is None or not 0 < price < 100000 or limit is None:
            return None
        count, size, _ = SODIMM_LAYOUTS[part.key]
        eligible = (candidate.condition in ("new", "open_box", "used", "refurbished")
                    and not listing.sold and not listing.multi_variant
                    and listing.seller_risk == "low"
                    and shopping.get("available") is True
                    and (listing.source != "ebay" or fresh_item_stock(shopping, self.now, part.key))
                    and not re.search(r"\b(?:rebate|cashback|trade[- ]?in|monthly|deposit|down payment)\b", listing.title, re.I)
                    and not (count > 1 and re.search(r"\beach\b|\bper\s+(?:stick|module|unit)\b", listing.title, re.I)))
        hit = eligible and price <= limit
        verdict = self.bands.STRONG if hit else self.bands.GOOD
        kind = "desktop UDIMM" if part.key in DESKTOP_LAYOUTS else "SO-DIMM"
        reason = f"Explicit {kind} price watch; not a market-value or compatibility guarantee."
        reason += " " + shopping.get("availability_note", "Stock verified" if shopping.get("available") is True else "Stock unconfirmed") + "."
        if shopping.get("availability_checked_at"):
            reason += " Stock checked: " + pacific_time(shopping["availability_checked_at"]) + "."
        detail = NativeAssessment(listing.listing_id, listing.source, part, listing.title, listing.url,
                                  price, 1, candidate.condition, listing.posted_at, verdict,
                                  "Within your memory alert limit" if hit else "Outside the memory alert criteria",
                                  reason, 0, target_price=limit, target_hit=hit, loggable=False,
                                  reference_trusted=False, seller_risk=listing.seller_risk,
                                  unlock=f"{count} x {size}GB DDR5 {kind}; {count * size}GB purchase total.")
        result = Assessment(self.key(listing), price, verdict, detail, rank=(-price,),
                            alertable=hit, target_override=hit, loggable=False,
                            axes=(("cheapness", f"Selected alert limit ${limit:,.0f}"),
                                  ("value", "Listed purchase price; verify shipping and checkout"),
                                  ("capability", detail.unlock)))
        self.sodimm_watches[result.key] = detail
        self.sodimm_stock[result.key] = {name: shopping.get(name) for name in
                                       ("available", "stock", "availability_checked_at", "availability_note")}
        return result

    def card(self, assessment, signal=None):
        if item := self.sodimm_watches.get(assessment.key):
            desktop = item.part.key in DESKTOP_LAYOUTS
            memory_warnings = ("Verify module type, capacity, board support and kit compatibility before buying.",)
            return Card(item.part.name, item.url, f"${item.unit_price:,.2f}", "DESKTOP RAM PRICE WATCH" if desktop else "SO-DIMM PRICE WATCH",
                        item.headline, item.reason,
                        (item.title, f"via {item.source}; {item.condition}", item.unlock,
                         f"Alert limit ${item.target_price:,.0f} for the complete purchase."),
                        ("Verify seller, stock, shipping and the exact module specifications before buying.",
                         *memory_warnings), priority=3)
        if band := self.card_price_watches.get(assessment.key):
            item = assessment.detail
            stock = self.card_stock.get(assessment.key)
            stock_facts = ()
            if stock is not None:
                stock_facts = (stock.get("availability_note") or "Item stock has not been verified",)
                if stock.get("availability_checked_at"):
                    stock_facts += ("Stock checked: " + pacific_time(stock["availability_checked_at"]),)
            return Card(item.part.name, item.url, f"${item.unit_price:,.2f}",
                        "CARD PRICE WATCH" + (" · URGENT TARGET" if assessment.target_override and item.unit_price <= band["urgent"] else ""),
                        "Listed price meets your watch limit" if assessment.target_override else "Outside the new-card alert criteria",
                        "Price notice; not a sold-price valuation or a claim of increased model capacity.",
                        (item.title, f"via {item.source}; {item.condition}",
                         f"Alert through ${band['ceiling']:,.0f}; priority target ${band['target']:,.0f}; urgent target ${band['urgent']:,.0f}.",
                         *stock_facts,
                         "Verify seller, availability, shipping and checkout total before buying."),
                        ("Confirm card clearance and power cabling for the existing tower.",),
                        priority=5 if item.part.key == "rtx_5090" and assessment.target_override or item.unit_price <= band["urgent"] else 4 if item.unit_price <= band["target"] else 3)
        return super().card(assessment, signal)

    def promote(self, assessments):
        return assessments

    def arbitrage(self, assessments):
        return {}

    def report(self, buys, others, problems):
        report = super().report(buys, others, problems)
        subject = report.subject if len(report.buys) == 1 else f"{len(report.buys)} new parts and display deals"
        return replace(report, subject=subject, heading="Parts and display deals")
