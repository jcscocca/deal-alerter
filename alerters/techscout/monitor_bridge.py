"""Read-only bridge from the installed monitor's public shopping export."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from urllib.parse import urlsplit, urlunsplit

from alerters.hardware.desktop_profile import DEFAULT_PROFILE, DesktopProfile
from alerters.hardware.prebuilt import Offer, exact_desktop, gpu_model
from alerters.hardware.native.match import extract_price
from .research import cpu_model
from alerters.hardware.prebuilt_specs import public_specs

LABELS = {"newegg": "Newegg", "ebay": "eBay", "apple-refurb": "Apple Refurbished",
          "slickdeals": "Slickdeals", "hp": "HP", "reddit": "Reddit"}
HOSTS = {"newegg": {"www.newegg.com", "newegg.com"}, "ebay": {"www.ebay.com", "ebay.com"},
         "apple-refurb": {"www.apple.com"}, "slickdeals": {"slickdeals.net"},
         "hp": {"www.hp.com"}, "reddit": {"www.reddit.com", "reddit.com"}}


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def stock_state(value):
    """Keep explicit retailer stock separate from incomplete purchase evidence."""
    if not isinstance(value, str):
        return "unknown"
    value = value.strip().lower().replace("_", " ").replace("-", " ")
    if value in ("not available", "unavailable", "out of stock", "sold out"):
        return "out_of_stock"
    if value in ("available", "in stock"):
        return "in_stock"
    if value in ("preorder", "pre order"):
        return "preorder"
    return "unknown"


def stamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.timestamp() if parsed.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def safe_url(value, source):
    if not isinstance(value, str) or len(value) > 2000 or any(ord(c) < 33 for c in value):
        return None
    try:
        url = urlsplit(value)
        if url.scheme != "https" or url.netloc.lower() not in HOSTS[source] or url.username or url.port:
            return None
        # Keep Newegg's selected seller Item; strip tracking and fragments elsewhere.
        query = ""
        if source == "newegg":
            from urllib.parse import parse_qs, urlencode
            item = parse_qs(url.query).get("Item", [])
            if item and re.fullmatch(r"[A-Za-z0-9-]{1,40}", item[0]):
                query = urlencode({"Item": item[0]})
        return urlunsplit(("https", url.netloc.lower(), url.path, query, ""))
    except (ValueError, KeyError):
        return None


def categories(title, is_system=False):
    if re.search(r"\biPad\b|\btablet\b|Galaxy Tab", title, re.I):
        return {"tablets"}
    if is_system or exact_desktop(title) or re.search(r"\b(?:Mac mini|Mac Studio|Mac Pro|MacBook|laptop|notebook|desktop|mini pc)\b", title, re.I):
        return {"computers", "desktop-memory"} if exact_desktop(title) else {"computers"}
    if re.search(r"\b(?:DDR[345]|DIMM|memory kit)\b", title, re.I) and not re.search(r"\bGDDR\d\b", title, re.I):
        return {"memory"}
    return {"supplies"}


def public_row(raw, source, checked, expires, problems, now, profile):
    from .integration import judgment
    is_offer = raw.get("type") == "offer"
    data = raw.get("offer") if is_offer else raw
    if not isinstance(data, dict):
        return None
    title, url = data.get("title"), safe_url(data.get("url"), source)
    if not isinstance(title, str) or not title.strip() or len(title) > 1500 or not url:
        return None
    reasons, warnings = list(problems), []
    fit, total, price, shipping = {}, None, None, None
    community = source in ("slickdeals", "reddit")
    seller = data.get("seller") or ("Apple" if source == "apple-refurb" else "Not published")
    raw_condition = data.get("condition") if isinstance(data.get("condition"), str) else ""
    condition = {"new": "New", "used": "Used", "open_box": "Open box", "refurbished": "Refurbished"}.get(raw_condition, "Not published")
    available, stock = False, "unknown"
    cost_note = "price + shipping · before tax"
    if is_offer:
        try:
            offer = Offer.from_json(data)
            if offer.retailer != source or offer.announcement:
                return None
            fit = asdict(profile.assess_memory(offer))
            price, shipping = number(offer.base_price), number(offer.shipping)
            total = number(offer.total(datetime.fromtimestamp(now, timezone.utc)))
            available = offer.confirmed is True and offer.sale_status(datetime.fromtimestamp(now, timezone.utc)) == "live"
            stock = stock_state(offer.stock)
            if offer.coupon and offer.coupon.active(datetime.fromtimestamp(now, timezone.utc)):
                cost_note = "with confirmed coupon + shipping · before tax"
                warnings.append("Coupon: " + offer.coupon.instructions)
            if offer.required_accessories or offer.coupon and offer.coupon.required_accessories:
                cost_note = "including required extras + shipping · before tax"
            identity = offer.key
        except (ValueError, TypeError, KeyError, ArithmeticError, AttributeError):
            return None
    else:
        identity = str(data.get("id", ""))
        shopping = data.get("shopping") if isinstance(data.get("shopping"), dict) else {}
        price = number(shopping.get("item_price")) if source == "ebay" else number(data.get("price"))
        shipping = number(shopping.get("shipping"))
        available = shopping.get("available") is True if source == "ebay" else source == "apple-refurb"
        if price is not None and shipping is not None:
            total = round(price + shipping, 2)
        if exact_desktop(title):
            fit = asdict(profile.assess_memory(Offer(source, identity, title, url, str(seller), condition,
                                                    {}, price, shipping, "unknown", False, checked)))
        if data.get("multi_variant"):
            reasons.append("Selected variant is unverified")
        if data.get("quantity", 1) != 1:
            reasons.append("Multiple-item lot; compare quantity before purchase")
        if data.get("seller_risk", "low") != "low":
            reasons.append("Seller needs review")
        if isinstance(data.get("seller_note"), str) and data["seller_note"]:
            warnings.append(data["seller_note"][:500])
    if community:
        total, shipping, available = None, None, False
        reasons.append("Community lead; retailer price and availability unverified")
        price = number(extract_price(title))
        cost_note = "community-quoted price · total unverified"
    else:
        if not available:
            reasons.append("Out of stock at last check" if stock == "out_of_stock" else "Unavailable or unconfirmed at last check")
        if price is None or price <= 0 or total is not None and total >= 1_000_000:
            reasons.append("Price unknown")
        if shipping is None or total is None:
            reasons.append("Shipping or required total unknown")
        if seller == "Not published" or condition == "Not published":
            reasons.append("Seller or condition unknown")
    storage = re.findall(r"\b\d+(?:\.\d+)?\s*(?:TB|GB)\s*(?:Gen[345]\s+)?(?:NVMe\s+)?SSD\b", title, re.I)
    kinds = categories(title, data.get("is_system", False))
    product_group = (f"Desktops · RTX {gpu_model(title)} · {fit.get('installed_gb') or '?'}GB" if fit else
                     ("Computers" if "computers" in kinds else "Components") + " · " + str(data.get("product_group") or "Other tech")[:150])
    return {"id": source + ":" + hashlib.sha256(identity.encode()).hexdigest()[:24], "judgment": judgment(raw.get("judgment")),
            "price_history": raw.get("judgment", {}).get("price_history") if isinstance(raw.get("judgment"), dict) else None,
            "build_specs": public_specs(data.get("specs")) if is_offer else {},
            "first_seen": raw.get("first_seen") if stamp(raw.get("first_seen")) is not None else None,
            "title": title, "url": url, "source": source, "retailer": LABELS[source],
            "seller": str(seller)[:250], "condition": condition, "price": price, "shipping": shipping,
            "total": total, "cost_note": cost_note, "available": available, "stock": stock, "gpu": gpu_model(title),
            "cpu": cpu_model(title) or "Not established", "storage": storage[0] if len(storage) == 1 else "Not established",
            "ram": fit.get("installed_gb"), "potential": fit.get("potential_gb"), "eligible": fit.get("eligible", False),
            "fit": fit.get("status", "Not assessed"), "fit_summary": fit.get("summary", ""),
            "layout_documented": fit.get("status") == "POSSIBLE REUSE", "warnings": warnings,
            "rank": None, "reasons": reasons, "checked_at": checked, "expires_at": expires,
            "lead": community, "categories": sorted(kinds), "product_group": product_group,
            "merchant": "Amazon" if community and re.search(r"\bat Amazon\b|\[Amazon\]|\(Amazon\)", title, re.I) else None}


def read_monitor(runtime, category, now):
    result = {"rows": [], "sources": [], "problems": []}
    if runtime is None:
        return result
    try:
        path = runtime / "shopping-sources.json"
        if path.stat().st_size > 12_000_000:
            raise ValueError()
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != 1 or not isinstance(data.get("sources"), list) or len(data["sources"]) > 220:
            raise ValueError()
    except (OSError, ValueError, TypeError, AttributeError):
        result["problems"].append("Monitor shopping export unavailable. The installed monitor may need updating.")
        return result
    heartbeat = number(data.get("heartbeat"))
    alive = heartbeat is not None and 0 <= now - heartbeat <= 90 and data.get("dry_run") is False
    profile, sources, selected = DesktopProfile(DEFAULT_PROFILE), {}, {}
    for batch in data["sources"]:
        if not isinstance(batch, dict) or batch.get("source") not in LABELS:
            continue
        source = batch["source"]
        checked = stamp(batch.get("observed_at"))
        interval = number(batch.get("interval"))
        lifetime = max(900, min(interval or 900, 3600) + 90)
        expires = checked + lifetime if checked is not None else 0
        recent = checked is not None and 0 <= now - checked <= lifetime
        problems = []
        if not alive:
            problems.append("Monitor stopped or heartbeat stale")
        if batch.get("failed") is not False:
            problems.append("Source's latest check failed")
        if not recent:
            problems.append("Availability needs a new monitor check")
        info = sources.setdefault(source, {"source": source, "label": LABELS[source], "jobs": 0,
                                          "ready": 0, "count": 0, "checked_at": None, "truncated": False})
        info["jobs"] += 1
        info["ready"] += int(not problems)
        info["truncated"] |= batch.get("truncated") is True
        if checked is not None and (not info["checked_at"] or checked > stamp(info["checked_at"])):
            info["checked_at"] = batch["observed_at"]
        rows = batch.get("rows")
        if not isinstance(rows, list):
            continue
        for raw in rows[:2500]:
            if not isinstance(raw, dict):
                continue
            row = public_row(raw, source, batch.get("observed_at"), min(expires, heartbeat + 90) if alive else 0,
                             problems, now, profile)
            if not row:
                continue
            previous = selected.get(row["id"])
            if previous is None or (stamp(row["checked_at"]) or 0) > (stamp(previous["checked_at"]) or 0):
                selected[row["id"]] = row
    for row in selected.values():
        sources[row["source"]]["count"] += 1
        if category == "amazon":
            if not row["lead"] or row.get("merchant") != "Amazon":
                continue
        elif category != "monitor" and category not in row["categories"]:
            continue
        if "desktop-memory" in row["categories"] and (not row["eligible"] or row["ram"] not in (32, 64) or not row["gpu"]):
            row["preference_reasons"] = [row["fit_summary"] or "Desktop configuration needs verification"]
        else:
            row["preference_reasons"] = []
        row["verification_reasons"] = list(row["reasons"])
        if category == "desktop-memory":
            row["reasons"] += row["preference_reasons"]
        result["rows"].append(row)
    result["sources"] = list(sources.values())
    for info in result["sources"]:
        info["status"] = ("Monitor heartbeat stale" if not alive else "Current" if info["ready"] == info["jobs"] else
                          "Some checks need attention" if info["ready"] else "Checks need attention" if info["checked_at"] else "No successful check yet")
    # Absent jobs must never look enabled (eBay can be disabled for missing credentials).
    for source, label in LABELS.items():
        if source not in sources:
            result["sources"].append({"source": source, "label": label, "jobs": 0, "ready": 0,
                                      "count": 0, "checked_at": None, "truncated": False, "status": "Not enabled"})
    return result
