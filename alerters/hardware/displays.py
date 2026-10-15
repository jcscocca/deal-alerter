"""Conservative 27-inch 4K display identity and explicit purchase-price watches.

Specifications may come from an exact documented model or the listing title.
Prices across models are purchase limits, never a common market-value history.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

from dealcore.config import read_config

CONFIG = read_config(Path(__file__).resolve().parents[2] / "config/monitor-watch.toml")
REQUIREMENTS = CONFIG["requirements"]
WATCHES = {row["key"]: row for row in CONFIG["watch"]}
MODELS = CONFIG["model"]
MODEL_PATTERN = re.compile("|".join(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"
                                    for row in MODELS for alias in row["aliases"]), re.I)
DISCOUNT = Decimal(str(CONFIG["pricing"]["discount_percent"]))
if not 0 < DISCOUNT < 100:
    raise ValueError("Monitor discount_percent must be between 0 and 100")
LIMITS = {key: float((Decimal(str(row["benchmark"])) * (1 - DISCOUNT / 100))
                     .quantize(Decimal("0.01"), rounding=ROUND_DOWN)) for key, row in WATCHES.items()}

ACCESSORY = re.compile(
    r"\b(?:replacement|protector|screen\s+panel|panel\s+only|stand\s+only|"
    r"monitor\s+(?:arm|stand|mount)|(?:cable|adapter|adaptor|cover|case)\s+(?:for|only)|"
    r"(?:main|power|logic|control)\s*board|power\s+supply|charger|"
    r"repair|cracked|dead\s+pixels?|burn[- ]?in(?!\s+(?:warranty|coverage|protection))|scratches?|scratched|"
    r"displayport\s+(?:broken|faulty|not\s+working)|hdmi[- ]only|"
    r"choose|select\s+(?:size|model)|bundle|gaming\s+pc|desktop\s+pc|laptop|notebook)\b"
    r"|^\s*(?:for|fits)\b(?!\s+sale\b)", re.I)
SIZE = re.compile(r'(?<![\w.])(\d{2}(?:\.\d)?)\s*(?:["\u201d\u2033]|[- ]?(?:inch(?:es)?|in)\b)', re.I)
HZ = re.compile(r"\b(\d{2,3})\s*hz\b", re.I)
DP = re.compile(r"\b(?:display\s*port|dp)(?:\s*v?([12]\.\d[a-z]?))?\b", re.I)
RESOLUTION = re.compile(r"\b(\d{4})\s*[x\u00d7]\s*(\d{4})\b", re.I)
LOT = re.compile(r"\b(?:lot|pack|set)\s+of\s+[2-9]\b|\b[2-9][- ]?pack\b|^\s*[2-9]\s*[x\u00d7]\s", re.I)
DP_FAULT = re.compile(
    r"\b(?:no|without)\s+(?:display\s*port|dp)\b(?!\s*(?:v?[12]\.\d[a-z]?\s*)?(?:cable|adapter)\b)"
    r"|\b(?:display\s*port|dp)(?:\s*v?[12]\.\d[a-z]?)?(?:\s+port)?\s+(?:is\s+)?"
    r"(?:broken|faulty|dead|not\s+working|does(?:n't|\s+not)\s+work)\b|\bhdmi[- ]only\b", re.I)
OTHER_HARDWARE = re.compile(r"\b(?:rtx\s*\d{4}|rx\s*\d{4}|ryzen\s+\d|i[3579][- ]?\d{4,5}[a-z]{0,2}|core\s+ultra\s+\d)\b", re.I)


def _port_text(text):
    # A cable in the purchase, or USB-C's DP Alt Mode, does not prove the
    # separate DisplayPort input the user requires.
    return re.sub(r"\b(?:display\s*port|dp)(?:\s*v?[12]\.\d[a-z]?)?\s+(?:alt[- ]?mode|cable|adapter)\b", "", text, flags=re.I)


@dataclass(frozen=True)
class Display:
    key: str
    refresh_hz: int
    panel: str
    ports: str
    model: str = ""

    @property
    def summary(self):
        return f'27-inch class; 3840 x 2160; {self.refresh_hz}Hz; {self.panel}'


def _present(alias, text):
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text, re.I))


def candidate(text):
    return bool(re.search(r"\bmonitors?\b", text, re.I) or MODEL_PATTERN.search(text))


def specifications(text):
    """No guessing from UHD alone, HDMI/USB-C alone, or a low-res fast mode."""
    if not candidate(text) or ACCESSORY.search(text) or LOT.search(text) or DP_FAULT.search(text) or OTHER_HARDWARE.search(text):
        return None
    if (re.search(r"\b(?:cable|cord)\b", text, re.I)
            and not re.search(r"\b(?:with|includes?|included)\b", text, re.I)):
        return None
    models = [row for row in MODELS if any(_present(alias, text) for alias in row["aliases"])]
    if len(models) > 1:
        return None
    sizes = {float(size) for size in SIZE.findall(text)}
    # 26.5/26.7-inch OLED panels are marketed as 27-inch class. Never accept
    # 28/32-inch panels or a menu mentioning both sizes.
    if sizes and not all(26.5 <= size <= REQUIREMENTS["size_class_inches"] for size in sizes):
        return None
    resolutions = {(int(w), int(h)) for w, h in RESOLUTION.findall(text)}
    native = tuple(REQUIREMENTS["resolution"])
    # Known dual-mode models legitimately advertise FHD beside native 4K.
    dual = bool(models and models[0].get("dual_mode") and
                re.search(r"dual[- ]?(?:mode|resolution)|(?:fhd|1080p)\s*\d{3}\s*hz", text, re.I))
    if resolutions - ({native, (1920, 1080)} if dual else {native}):
        return None
    if re.search(r"\b(?:1440p|qhd|wqhd|2k)\b", text, re.I):
        return None
    if re.search(r"\b(?:1080p|fhd)\b", text, re.I) and not dual:
        return None
    rates = {int(rate) for rate in HZ.findall(text)}
    # Explicitly slow native mode contradicts a generic high-refresh claim.
    native_rates = re.findall(r"\b(?:4k|3840\s*[x\u00d7]\s*2160)\s*(?:@|at|/|[-,])?\s*(\d{2,3})\s*hz", text, re.I)
    if any(int(rate) < REQUIREMENTS["min_refresh_hz"] for rate in native_rates):
        return None
    if rates and max(rates) < REQUIREMENTS["min_refresh_hz"]:
        return None
    if models:
        row = models[0]
        if ("OLED" in row["panel"] and re.search(r"\b(?:ips|va|tn)\b", text, re.I)
                or "OLED" not in row["panel"] and re.search(r"\boled\b", text, re.I)):
            return None
        panel, rate, ports, model = row["panel"], row["refresh_hz"], row["ports"], row["aliases"][0]
    else:
        # An unknown product needs every requirement stated explicitly in its
        # title. A model number alone cannot establish its ports or resolution.
        if not sizes or not (native in resolutions or re.search(r"\b4k\b", text, re.I)):
            return None
        if re.search(r"\b(?:supports?|accepts?|upscaled?)\s+(?:up\s+to\s+)?4k\b|\b4k\s+(?:input|compatible|upscal)", text, re.I):
            return None
        if len(rates) != 1 or not DP.search(_port_text(text)):
            return None
        rate = next(iter(rates))
        panel = "OLED" if re.search(r"\b(?:(?:qd|w)[- ]?)?oled\b", text, re.I) else "IPS" if re.search(r"\bips\b", text, re.I) else "VA" if re.search(r"\bva\b", text, re.I) else "Panel not specified"
        dp = DP.search(_port_text(text))
        ports = "DP" + (" " + dp[1] if dp[1] else "")
        if re.search(r"\bhdmi\b", text, re.I):
            ports += "; HDMI"
        if re.search(r"\busb[- ]?c\b", text, re.I):
            ports += "; USB-C (capabilities not specified)"
        model = ""
    key = "monitor_4k_27_oled" if "OLED" in panel else "monitor_4k_27_standard"
    if rate < REQUIREMENTS["min_refresh_hz"] or REQUIREMENTS["displayport_required"] and not DP.search(ports):
        return None
    return Display(key, rate, panel, ports, model)


def configuration(text):
    display = specifications(text)
    return display.key if display else None


def judge_display(plugin, candidate):
    from datetime import datetime, timezone
    from dealcore.types import Assessment
    from .native.verdict import Assessment as NativeAssessment

    listing, result = candidate.listing, candidate.match
    display = specifications(listing.title)
    price = result.unit_price
    if display is None or price is None or not 0 < price < 100000:
        return None
    shopping = listing.extra.get("shopping", {})
    now = getattr(plugin, "now", datetime.now(timezone.utc))
    try:
        fresh = 0 <= (now - datetime.fromisoformat(shopping.get("availability_checked_at"))).total_seconds() <= 1200
    except (TypeError, ValueError):
        fresh = False
    verified = (listing.source == "ebay" and shopping.get("verified_price_watch") == display.key
                and shopping.get("available") is True and fresh)
    community = listing.source in ("slickdeals", "reddit/buildapcsales") and listing.loggable
    text = listing.title + "\n" + listing.body
    restricted = re.search(r"\b(?:rebate|cashback|trade[- ]?in|monthly|deposit|down payment|"
                           r"members?[- ]only|student[- ]only|sold\s+out|out\s+of\s+stock|expired)\b", text, re.I)
    broken_port = DP_FAULT.search(text)
    absent = re.search(r"\b(?:monitor|display|screen)\s+(?:is\s+)?not\s+included\b|\b(?:stand|mount|cable|panel)\s+only\b", text, re.I)
    watch = WATCHES[display.key]
    limit = candidate.hunt.target if candidate.hunt.target is not None else LIMITS[display.key]
    # Keep the existing hard plausibility floor, seller/condition/variant vetoes,
    # and require fresh exact-item evidence for eBay's selected search results.
    eligible = (candidate.condition == REQUIREMENTS["condition"] and not listing.sold
                and not listing.multi_variant and listing.seller_risk == "low"
                and not result.is_system and not result.is_bundle and result.quantity == 1
                and price >= watch["benchmark"] * plugin.cfg.thresholds.min_price_ratio
                and shopping.get("available") is not False and not restricted and not broken_port and not absent
                and (verified or community))
    hit = bool(eligible and price <= limit)
    verdict = plugin.bands.STRONG if hit else plugin.bands.GOOD
    reason = ("Explicit monitor purchase-price watch; different models are not comparable sold-value history. "
              + ("Community-quoted price; retailer stock, shipping and checkout are unverified."
                 if community else str(shopping.get("availability_note") or "Availability has not been verified") + "."))
    detail = NativeAssessment(listing.listing_id, listing.source, result.part, listing.title, listing.url,
                              price, 1, candidate.condition, listing.posted_at, verdict,
                              "Within your 4K monitor alert limit" if hit else "Outside the monitor alert criteria",
                              reason, 0, target_price=limit, target_hit=hit, loggable=False,
                              reference_trusted=False, seller_risk=listing.seller_risk,
                              unlock=display.summary, confidence="price_watch")
    assessment = Assessment(plugin.key(listing), price, verdict, detail, rank=(-price,),
                            alertable=hit, target_override=hit, loggable=False,
                            axes=(("cheapness", f"Monitor alert limit ${limit:,.2f}"),
                                  ("value", "Purchase-price notice; not a per-model discount claim"),
                                  ("capability", display.summary)))
    plugin.display_watches[assessment.key] = (display, community)
    return assessment


def display_card(plugin, assessment):
    from dealcore.types import Card
    display, community = plugin.display_watches[assessment.key]
    item = assessment.detail
    return Card(display.model or item.part.name, item.url, f"${item.unit_price:,.2f}",
                "4K MONITOR PRICE WATCH" + (" · COMMUNITY LEAD" if community else ""),
                item.headline, item.reason,
                (item.title, display.summary, "Ports: " + display.ports,
                 f"Alert limit ${item.target_price:,.2f}; via {item.source}; {item.condition}"),
                ("Verify retailer checkout, delivery and warranty before buying.",), priority=3)
