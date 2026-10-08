"""HP OMEN and Newegg ABS/Skytech public HTML adapters.

Only the selected product is evidence. Recommendations, family options and
aggregate/from prices can discover URLs but cannot confirm an offer.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .prebuilt import Coupon, Offer, dollars, exact_desktop, gpu_model
from .retail_http import Deferred, public_url

DESKTOP_BRANDS = {"abs", "skytech", "cyberpowerpc", "ibuypower", "msi", "gigabyte", "stormcraft", "hp"}


def initial_state(body: str) -> dict:
    match = re.search(r"window\.__initialState__\s*=\s*", body)
    if not match:
        raise Deferred("Retailer markup changed: selected product state missing", 300)
    try:
        return json.JSONDecoder().raw_decode(body[match.end():])[0]
    except ValueError:
        raise Deferred("Retailer markup changed: invalid product state", 300) from None


def canonical_product(url: str) -> str:
    url = public_url(html.unescape(url))
    p = urlsplit(url)
    if p.hostname == "www.newegg.com":
        match = re.search(r"/p/([A-Za-z0-9-]+)(?:/|$)", p.path)
        if not match or match[1] == "pl":
            raise ValueError("Not a Newegg product URL")
        item = parse_qs(p.query).get("Item", [None])[0]
        return f"https://www.newegg.com/p/{match[1]}" + ("?" + urlencode({"Item": item}) if item else "")
    if p.hostname == "www.hp.com" and re.match(r"/us-en/shop/(pdp|custom)/", p.path):
        # Preserve configuration selectors; never reduce a customized URL to a base SKU.
        query = {k: v for k, v in parse_qs(p.query).items() if not k.lower().startswith(("utm_", "jumpid", "msockid"))}
        return urlunsplit(("https", p.netloc, p.path, urlencode(query, doseq=True), ""))
    from .builders import builder_product
    return builder_product(url)[1]


def discover_newegg(body: str) -> list[str]:
    state = initial_state(body)
    if not isinstance(state.get("Products"), list):
        raise Deferred("Newegg search product collection missing", 300)
    links = []
    for row in state["Products"]:
        item = row.get("ItemCell") or {}
        title = (item.get("Description") or {}).get("Title", "")
        brand = (item.get("ItemManufactory") or {}).get("Manufactory", "").lower()
        if brand in DESKTOP_BRANDS and exact_desktop(title) and item.get("Item"):
            links.append(f"https://www.newegg.com/p/{item.get('ParentItem') or item['Item']}?Item={item['Item']}")
    return list(dict.fromkeys(links))


def discover_hp(body: str) -> list[str]:
    soup = BeautifulSoup(body, "html.parser")
    if not soup.find(string=re.compile(r"OMEN", re.I)):
        raise Deferred("HP discovery page has no OMEN content", 300)
    links = []
    for anchor in soup.select("a[href]"):
        url = urljoin("https://www.hp.com", anchor["href"])
        if "omen" not in url.lower():
            continue
        try:
            links.append(canonical_product(url))
        except ValueError:
            pass
    return list(dict.fromkeys(links))


def _text(value) -> str:
    return BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)


def _explicit_time(value) -> str | None:
    if not isinstance(value, str) or not re.search(r"T\d{2}:\d{2}.*(?:Z|[+-]\d{2}:\d{2})$", value):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def parse_newegg(body: str, url: str, now: datetime) -> Offer | None:
    data = initial_state(body)
    item = data.get("ItemDetail")
    if not isinstance(item, dict) or not item.get("Item"):
        raise Deferred("Newegg selected ItemDetail missing", 300)
    requested = parse_qs(urlsplit(url).query).get("Item", [None])[0]
    if requested and item["Item"] != requested:
        raise Deferred("Newegg changed the selected seller/item", 300)
    desc, feature = item.get("Description") or {}, item.get("Feature") or {}
    if item.get("CountryCode") != "USA":
        raise Deferred("Newegg offer is not confirmed as US pricing", 300)
    title = html.unescape(desc.get("Title") or "")
    brand = (item.get("ItemManufactory") or {}).get("Manufactory", "").lower()
    if brand not in DESKTOP_BRANDS or not exact_desktop(title):
        return None
    specs = {}
    for line in re.split(r"<br\s*/?>", item.get("ViewDescription") or "", flags=re.I):
        key, sep, value = _text(line).partition(":")
        if sep:
            specs[key.strip()] = value.strip()
    # The selected property is separate from the list of available alternatives.
    for group in (data.get("PropertyCollection") or {}).get("PropertyGroups", []):
        selected = (group.get("SelectedProperty") or {}).get("Description")
        if selected:
            specs["Selected " + group.get("GroupDescription", "option")] = selected
        if group.get("GroupDescription", "").lower() == "gpu" and selected:
            selected_model = re.fullmatch(r"(?:GeForce\s+RTX\s+)?(5080|5090)", selected, re.I)
            if not selected_model or selected_model[1] != gpu_model(title):
                raise Deferred("Selected GPU conflicts with the product title", 300)
    gpu = specs.get("GPU/VGA Type", "")
    if gpu_model(gpu) != gpu_model(title):
        raise Deferred("Desktop RTX GPU not confirmed in selected specifications", 300)
    specs["Model"] = item.get("Model") or item["Item"]
    specs["Included components"] = _text(desc.get("BulletDescription"))
    condition = ("open_box" if feature.get("IsOpenBoxed") else "refurbished" if feature.get("IsRefurbished")
                 else "new" if feature.get("IsNew") else "unknown")
    seller_data = item.get("Seller") or {}
    seller = seller_data.get("SellerName") or "Unknown seller"
    # Direct Newegg inventory can leave the structured seller blank. Require
    # its primary product's explicit "Sold by Newegg" label; shipping by
    # Newegg or a recommendation elsewhere cannot establish who sells it.
    if seller == "Unknown seller" and seller_data.get("SellerId") in ("0", "", None):
        labels = BeautifulSoup(body, "html.parser").select(".product-seller-box .product-seller-sold-by")
        if len(labels) == 1 and re.fullmatch(r"sold\s+by\s+newegg", labels[0].get_text(" ", strip=True), re.I):
            seller = "Newegg"
    # Do not trust a marketplace seller merely because the product is on Newegg.
    trusted = ((seller == "Skytech" and seller_data.get("SellerId") == "A1HJ")
               or (seller == "Newegg" and seller_data.get("SellerId") in ("0", "", None)))
    stock = "in_stock" if item.get("Instock") is True else "out_of_stock" if item.get("Instock") is False else "unknown"
    if item.get("IsActivated") is False or item.get("Active") in ("0", 0) or item.get("IsVacationSeller"):
        stock = "out_of_stock"
    if item.get("CanPreorder") or item.get("CanPreLaunch") or item.get("IsBlockSeller"):
        stock = "preorder" if item.get("CanPreorder") else "unknown"
    base = dollars(item.get("UnitCost"))
    rebate = dollars(item.get("InstantRebateAmount", 0))
    if base is not None and rebate is not None:
        base = dollars(base - rebate)
    if base is None or base <= 0 or item.get("NoItemPriceDataMark") or item.get("PriceHideMark") not in (None, "0", 0):
        raise Deferred("Newegg price missing or requires cart verification", 300)
    shipping = 0.0 if (item.get("ItemTagFlags") or {}).get("FreeShipping") else dollars(item.get("ShippingCharge"))
    promo = item.get("PromotionInfo") or {}
    code = promo.get("PCode") or ""
    coupon = None
    if code:
        terms = _text(promo.get("DisplayPromotionText") or promo.get("PromotionText"))
        discount = dollars(item.get("PcodeDiscount"))
        restricted = re.search(r"cardholder|new customer|subscriber|membership|combo|bundle|student|email", terms, re.I)
        # PcodeDiscount is an amount; undocumented numeric PCodeType is never guessed.
        coupon = Coupon(code, f"Apply {code} at checkout. {terms}", discount or 0,
                        eligible=bool(discount and terms and not restricted))
    final = dollars(item.get("FinalPrice"))
    if not final:
        raise Deferred("Newegg final price unavailable", 300)
    if coupon:
        # FinalPrice may already include PcodeDiscount. Reconcile both shapes
        # against the undiscounted item cost so a code is never deducted twice.
        if all(abs(final - expected) > .02 for expected in (base, base - coupon.discount)):
            raise Deferred("Newegg price/coupon fields disagree", 300)
    else:
        base = final
    return Offer("newegg", item["Item"], title, canonical_product(url), seller, condition,
                 specs, base, shipping, stock, trusted and condition != "unknown" and stock != "unknown",
                 now.isoformat(), coupon=coupon, evidence="Newegg selected ItemDetail and selected GPU property",
                 starts_at=_explicit_time(item.get("ScheduleStartTime")),
                 ends_at=_explicit_time(item.get("ScheduleEndTime")))


def _products(soup):
    def walk(value):
        if isinstance(value, list):
            for child in value:
                yield from walk(child)
        elif isinstance(value, dict):
            if value.get("@type") == "Product":
                yield value
            for child in value.get("@graph", []):
                yield from walk(child)
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            yield from walk(json.loads(script.string or script.get_text()))
        except ValueError:
            continue


def parse_hp(body: str, url: str, now: datetime) -> Offer | None:
    soup = BeautifulSoup(body, "html.parser")
    heading = soup.find("h1")
    if not heading:
        raise Deferred("HP selected product heading missing", 300)
    title = heading.get_text(" ", strip=True)
    if "omen" not in title.lower():
        return None
    page = soup.get_text(" ", strip=True)
    products = list(_products(soup))
    # A primary product must match h1. Accessory JSON-LD cannot supply the price.
    products = [p for p in products if _text(p.get("name")) == title]
    if len(products) != 1:
        raise Deferred("HP primary product/price unavailable; dynamic configuration unverified", 300)
    product = products[0]
    sku = str(product.get("sku") or product.get("mpn") or "")
    if not sku:
        raise Deferred("HP exact SKU unavailable", 300)
    specs = {}
    for prop in product.get("additionalProperty", []):
        if isinstance(prop, dict) and prop.get("name"):
            specs[str(prop["name"])] = _text(prop.get("value"))
    # Schema describing a configurable base SKU does not prove a selected upgrade.
    configurable = "/custom/" in url or bool(re.search(r"AV(?:[_#-]|$)|\b(?:customizable|configure|up to)\b", sku + " " + title, re.I))
    description = _text(product.get("description"))
    primary = " ".join((title, description, *[v for k, v in specs.items() if "graphics" in k.lower()]))
    if not exact_desktop(primary):
        raise Deferred("HP selected desktop RTX GPU not proven; base/family price ignored", 300)
    if configurable:
        raise Deferred("HP configurable SKU requires a fixed selected-configuration offer", 900)
    specs["Configuration"] = title
    specs["Details"] = description
    specs["Selected GPU"] = gpu_model(primary)
    for key, value in specs.items():
        if "graphics" in key.lower() and gpu_model(value) != gpu_model(primary):
            raise Deferred("HP selected graphics conflict with title", 300)
    offers = product.get("offers")
    offers = offers if isinstance(offers, list) else [offers]
    if len(offers) != 1 or not isinstance(offers[0], dict) or offers[0].get("@type") == "AggregateOffer":
        raise Deferred("HP price describes multiple configurations", 300)
    offer = offers[0]
    price = dollars(offer.get("price"))
    if offer.get("priceCurrency") != "USD" or not price:
        raise Deferred("HP USD price unavailable (zero/placeholders rejected)", 300)
    stock = {"InStock": "in_stock", "OutOfStock": "out_of_stock", "SoldOut": "out_of_stock", "PreOrder": "preorder"}.get(str(offer.get("availability", "")).rsplit("/", 1)[-1], "unknown")
    condition = {"NewCondition": "new", "RefurbishedCondition": "refurbished", "UsedCondition": "used"}.get(str(offer.get("itemCondition", product.get("itemCondition", ""))).rsplit("/", 1)[-1], "unknown")
    if re.search(r"open[ -]box", title, re.I):
        condition = "open_box"
    elif re.search(r"refurbished", title, re.I):
        condition = "refurbished"
    # HP's fixed consumer retail SKUs are new unless explicitly labelled otherwise.
    elif condition == "unknown" and not re.search(r"used|renewed", title, re.I):
        condition = "new"
    shipping = 0.0 if re.search(r"free\s+(?:storewide\s+shipping|shipping\s+storewide)", page, re.I) else None
    for entry in offer.get("shippingDetails", []) if isinstance(offer.get("shippingDetails"), list) else [offer.get("shippingDetails")]:
        if isinstance(entry, dict):
            rate = entry.get("shippingRate") or {}
            if rate.get("currency") == "USD":
                shipping = dollars(rate.get("value"))
    seller = (offer.get("seller") or {}).get("name", "HP")
    confirmed = seller.lower() in ("hp", "hp store", "hp inc.") and stock != "unknown"
    # Coupon badges in Recommended Accessories are intentionally never applied.
    return Offer("hp", sku, title, canonical_product(url), seller, condition, specs, price, shipping,
                 stock, confirmed, now.isoformat(), evidence="HP primary fixed-SKU Product/Offer schema",
                 starts_at=_explicit_time(offer.get("validFrom") or offer.get("availabilityStarts")),
                 ends_at=_explicit_time(offer.get("validThrough") or offer.get("priceValidUntil")))


def reviewed_coupon(offer: Offer, body: str, rules: list[dict], now: datetime) -> Offer:
    """Optional exact-SKU terms reviewed by the owner, expiring by explicit date.

    No membership, student or card eligibility is assumed. Rules without all
    costs/terms stay informational. Code must still be published on this page.
    """
    from dataclasses import replace
    from dealcore.state import parse_time
    for rule in rules:
        if rule.get("retailer") != offer.retailer or rule.get("sku") != offer.sku:
            continue
        if not rule.get("ends_at") or parse_time(rule["ends_at"]) <= now:
            continue
        if rule.get("code", "") not in _text(body):
            continue
        discount = dollars(rule.get("discount"))
        accessories = dollars(rule.get("required_accessories"))
        eligible = rule.get("eligibility_confirmed") is True and discount is not None and accessories is not None
        return replace(offer, coupon=Coupon(rule["code"], rule["instructions"], discount or 0, eligible,
                                           rule.get("starts_at"), rule["ends_at"], accessories))
    return offer
