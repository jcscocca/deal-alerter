"""Complete-PC offers and evidence, deliberately separate from loose GPU prices."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

from dealcore.state import atomic_write, parse_time
from .price_evidence import PriceEvidence, offer_key

PACIFIC = ZoneInfo("America/Los_Angeles")
GPU = re.compile(r"\b(?:geforce\s+)?rtx\s*[™®]?\s*(5080|5090)\b", re.I)
NOT_DESKTOP = re.compile(r"laptop|notebook|mobile|\b5090\s*d\b|\b(?:no|without|optional)\s+(?:gpu|graphics|rtx)|up to.{0,30}(?:5080|5090)", re.I)


def gpu_model(text: str) -> str | None:
    if re.search(r"\b(?:5080|5090)\s*(?:[/|]|or)\s*(?:RTX\s*)?(?:5080|5090)\b", text, re.I):
        return None
    models = set(GPU.findall(text))
    return models.pop() if len(models) == 1 and not NOT_DESKTOP.search(text) else None


def exact_desktop(text: str) -> bool:
    return bool(gpu_model(text)
                and re.search(r"desktop|gaming\s+(?:pc|computer)|\bprebuilt\b|\bOMEN\s+(?:MAX\s+)?\d+L\b", text, re.I))


def dollars(value) -> float | None:
    try:
        amount = Decimal(str(value).replace(",", "").replace("$", "").strip())
        if not amount.is_finite() or amount < 0:
            return None
        return float(amount.quantize(Decimal(".01"), rounding=ROUND_HALF_UP))
    except (ValueError, ArithmeticError):
        return None


def priority(price: float | None) -> int:
    return 3 if price is None or price >= 4500 else 4 if price >= 4000 else 5


def pacific_time(value: str | None) -> str:
    return parse_time(value).astimezone(PACIFIC).strftime("%b %d, %Y %I:%M %p %Z") if value else "Start time not published"


@dataclass(frozen=True)
class Coupon:
    code: str
    instructions: str
    discount: float = 0
    # True only for explicit, product-scoped public terms or reviewed eligibility.
    eligible: bool = False
    starts_at: str | None = None
    ends_at: str | None = None
    required_accessories: float | None = 0


    def active(self, now: datetime) -> bool:
        return (self.eligible and self.required_accessories is not None
                and (not self.starts_at or parse_time(self.starts_at) <= now)
                and (not self.ends_at or parse_time(self.ends_at) > now))


@dataclass(frozen=True)
class Offer:
    retailer: str
    sku: str
    title: str
    url: str
    seller: str
    condition: str
    specs: dict[str, str]
    base_price: float | None
    shipping: float | None
    stock: str
    confirmed: bool
    observed_at: str
    coupon: Coupon | None = None
    cashback: str = "Not included; eligibility and payout unverified"
    starts_at: str | None = None
    ends_at: str | None = None
    announcement: bool = False
    evidence: str = ""
    required_accessories: float | None = 0
    notice_type: str = "live-deal"
    claimed_price: float | None = None

    @property
    def gpu(self) -> str | None:
        return gpu_model(" ".join((self.title, self.specs.get("GPU/VGA Type", ""),
                                   self.specs.get("Details", ""),
                                   "RTX " + self.specs.get("Selected GPU", ""))))

    @property
    def key(self) -> str:
        # A different RAM/CPU/configuration or seller must not inherit a receipt.
        config = json.dumps([self.sku] if self.announcement else [self.sku, self.seller, self.condition, self.specs], sort_keys=True)
        return f"prebuilt/{self.retailer}:" + hashlib.sha256(config.encode()).hexdigest()[:24]

    def total(self, now: datetime) -> float | None:
        if self.base_price is None or self.shipping is None or self.required_accessories is None:
            return None
        amount = Decimal(str(self.base_price)) + Decimal(str(self.shipping)) + Decimal(str(self.required_accessories))
        if self.coupon and self.coupon.active(now):
            amount += Decimal(str(self.coupon.required_accessories)) - Decimal(str(self.coupon.discount))
        return dollars(amount) if amount > 0 else None

    def sale_status(self, now: datetime) -> str:
        if self.ends_at and parse_time(self.ends_at) <= now:
            return "ended"
        if self.starts_at and parse_time(self.starts_at) > now:
            return "upcoming"
        if self.announcement:
            return "unverified"
        return "live" if self.confirmed and self.stock == "in_stock" else "unavailable"

    @classmethod
    def from_json(cls, raw: dict):
        raw = dict(raw)
        if raw.get("coupon"):
            raw["coupon"] = Coupon(**raw["coupon"])
        return cls(**raw)


class PrebuiltHistory:
    """One observation per offer/price, with independent condition/configuration keys."""
    def __init__(self, directory: Path):
        self.path = directory / "prebuilt-prices.jsonl"
        self.observations = PriceEvidence(directory / "prebuilt-observations.json")
        self.rows = []
        if self.path.exists():
            self.rows = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.identities = {(r["key"], r["total"]) for r in self.rows}

    def record(self, offer: Offer, now: datetime):
        total = offer.total(now)
        if not offer.confirmed or offer.announcement or total is None or offer.sale_status(now) != "live":
            return
        if offer.condition in ("new", "refurbished", "open_box", "used") and offer.seller.strip():
            self.observations.record(offer_key(offer), total, offer.observed_at)
        identity = (offer.key, total)
        if identity not in self.identities:
            self.rows.append({"key": offer.key, "total": total, "seen_at": now.isoformat(),
                              "condition": offer.condition, "offer": asdict(offer)})
            self.identities.add(identity)

    def summary(self, offer: Offer) -> str:
        prices = [r["total"] for r in self.rows if r["key"] == offer.key]
        return (f"{len(prices)} prior configuration prices; lowest ${min(prices):,.2f} ({offer.condition})"
                if prices else f"No prior price history for this configuration ({offer.condition})")

    def save(self):
        atomic_write(self.path, "".join(json.dumps(r, sort_keys=True) + "\n" for r in self.rows))
        self.observations.save()

    def evidence(self, offer: Offer, now: datetime) -> dict:
        legacy = [r for r in self.rows if r["key"] == offer.key
                  and r.get("offer", {}).get("title") == offer.title
                  and r.get("offer", {}).get("confirmed") is True
                  and r.get("offer", {}).get("stock") == "in_stock"
                  and not r.get("offer", {}).get("announcement")]
        return self.observations.summary(offer_key(offer), now.isoformat(), legacy)


class OfferState:
    """Observation revisions survive outages; delivery is still owned by AlertState."""
    def __init__(self, directory: Path):
        self.path = directory / "prebuilt-offers.json"
        raw = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"version": 1, "offers": {}}
        if raw.get("version") != 1 or not isinstance(raw.get("offers"), dict):
            raise ValueError("Invalid prebuilt offer state")
        self.rows = raw["offers"]

    def observe(self, offer: Offer, now: datetime) -> tuple[str, str]:
        old = self.rows.get(offer.key)
        total, status = offer.total(now), offer.sale_status(now)
        if total is None and offer.announcement:
            total = offer.claimed_price
        coupon = offer.coupon.code if offer.coupon and offer.coupon.active(now) else ""
        changed = old is None
        if old:
            previous = old["price"]
            price_change = ((previous is None) != (total is None) or
                            previous is not None and total is not None and
                            (abs(total - previous) >= max(25, previous * .01)
                             or priority(total) != priority(previous)
                             or (total <= 5000) != (previous <= 5000)))
            # Unknown stock is a parser failure, never a fabricated restock.
            changed = bool(price_change or status != old["status"] or coupon != old["coupon"]
                           or offer.starts_at != old["offer"].get("starts_at"))
        revision = (old["revision"] if old else 0) + int(changed)
        restock = bool(old and old.get("last_known_stock") == "out_of_stock" and offer.stock == "in_stock")
        event = (offer.notice_type if offer.announcement else "upcoming-sale" if status == "upcoming" else
                 "restock" if restock else "live-deal")
        if old and not changed:
            event = old["event"]
        self.rows[offer.key] = {"revision": revision, "price": total if changed else old["price"],
                               "status": status, "coupon": coupon, "event": event,
                               "last_known_stock": offer.stock if offer.stock != "unknown" else (old or {}).get("last_known_stock"),
                               "offer": asdict(offer), "seen_at": now.isoformat(),
                               "start_rechecked": (old or {}).get("start_rechecked")}
        return str(revision), event

    def due_announcements(self, now: datetime) -> list[tuple[str, Offer]]:
        return [(key, Offer.from_json(row["offer"])) for key, row in self.rows.items()
                if row["offer"].get("starts_at") and not row.get("start_rechecked")
                and parse_time(row["offer"]["starts_at"]) <= now
                and now - parse_time(row["offer"]["starts_at"]) < timedelta(days=2)]

    def save(self):
        atomic_write(self.path, json.dumps({"version": 1, "offers": self.rows}, indent=2) + "\n")


def announced_start(text: str, posted: datetime) -> str | None:
    """Only explicit dates/zones. Ambiguous local times stay unverified, not guessed."""
    iso = re.search(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})", text)
    if iso:
        return parse_time(iso[0]).isoformat()
    match = re.search(r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{4})?|tomorrow|today)"
                      r"(?:\s+at)?\s+(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?\s*(PST|PDT|PT|EST|EDT|ET|UTC)\b", text, re.I)
    if not match:
        return None
    date, hour, minute, ampm, zone = match.groups()
    zones = {"PT": "America/Los_Angeles", "ET": "America/New_York", "UTC": "UTC"}
    fixed = {"PST": -8, "PDT": -7, "EST": -5, "EDT": -4}
    tz = ZoneInfo(zones[zone.upper()]) if zone.upper() in zones else timezone(timedelta(hours=fixed[zone.upper()]))
    try:
        if date.lower() in ("today", "tomorrow"):
            day = posted.astimezone(tz).date() + timedelta(days=int(date.lower() == "tomorrow"))
        elif "-" in date:
            day = datetime.strptime(date, "%Y-%m-%d").date()
        else:
            date = date if date.count("/") == 2 else date + f"/{posted.astimezone(tz).year}"
            day = datetime.strptime(date, "%m/%d/%Y").date()
        hour = int(hour)
        if ampm:
            if not 1 <= hour <= 12:
                return None
            hour = hour % 12 + (12 if ampm.upper() == "PM" else 0)
        result = datetime(day.year, day.month, day.day, hour, int(minute or 0), tzinfo=tz)
        # A PT/ET time in the autumn fold or spring gap is not uniquely known.
        if isinstance(tz, ZoneInfo) and result.replace(fold=0).utcoffset() != result.replace(fold=1).utcoffset():
            return None
        return result.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None
