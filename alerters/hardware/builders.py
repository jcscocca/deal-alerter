"""Fixed prebuilt configurations from public builder pages; never cart requests.

Catalog prices are discovery evidence only. Product offers require agreement
between the selected SKU, published specifications, price and stock signals.
"""
from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .prebuilt import Offer, dollars, gpu_model
from .retail_http import Deferred, public_url
from .retailers import _products, _text

HOSTS = {"cyberpowerpc": "www.cyberpowerpc.com", "skytech": "skytechgaming.com",
         "ibuypower": "www.ibuypower.com"}


def builder_product(url):
    url = public_url(url)
    p = urlsplit(url)
    # Configuration selectors must not silently become the default configuration.
    if p.query:
        raise ValueError("Builder configuration selectors are not supported")
    patterns = {"cyberpowerpc": r"/system/Prebuilt-PC-[A-Za-z0-9-]+/?",
                "skytech": r"/prebuilt-gaming-pc/st-[a-z0-9-]+/[a-z0-9-]+/[a-z0-9-]+/?",
                "ibuypower": r"/store/rdy-[a-z0-9-]+/?"}
    for source, host in HOSTS.items():
        if p.hostname == host and re.fullmatch(patterns[source], p.path):
            return source, "https://" + host + p.path.rstrip("/")
    raise ValueError("Not a fixed builder product URL")


def discover_cyberpowerpc(body):
    soup = BeautifulSoup(body, "html.parser")
    cards = soup.select(".system[data-system]")
    if not cards:
        raise Deferred("CyberPowerPC prebuilt catalog markup changed", 900)
    urls = []
    for card in cards:
        spec = card.select_one(".system__spec")
        if not spec or not gpu_model(spec.get_text(" ", strip=True)):
            continue
        for link in card.select('a[href^="/system/Prebuilt-PC-"]'):
            try:
                urls.append(builder_product(urljoin("https://www.cyberpowerpc.com", link["href"]))[1])
            except ValueError:
                continue
    return list(dict.fromkeys(urls))


def discover_skytech(body):
    # The public catalog renders its grid in JavaScript. The published sitemap
    # gives stable, exact-SKU URLs without calling undocumented catalog APIs.
    if len(body) > 8_000_000 or re.search(r"<!\s*(?:DOCTYPE|ENTITY)", body, re.I):
        raise Deferred("Skytech sitemap exceeds supported limits", 3600)
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise Deferred("Skytech sitemap unavailable", 3600) from None
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    if root.tag != ns + "urlset":
        raise Deferred("Skytech product sitemap format changed", 3600)
    urls = []
    for node in root.findall(ns + "url/" + ns + "loc"):
        url = node.text or ""
        if not re.search(r"-rtx-(?:5070-?ti|5080|5090)-", url):
            continue
        try:
            source, url = builder_product(url)
            if source == "skytech":
                urls.append(url)
        except ValueError:
            continue
    return list(dict.fromkeys(urls))


def _primary(body, url, source):
    expected, canonical = builder_product(url)
    if source != expected:
        raise Deferred("Builder product host mismatch", 900)
    soup = BeautifulSoup(body, "html.parser")
    heading = soup.select_one("h1")
    products = [p for p in _products(soup) if heading and _text(p.get("name")) == heading.get_text(" ", strip=True)]
    if len(products) != 1:
        raise Deferred("Builder selected product schema/heading missing or ambiguous", 900)
    product = products[0]
    sku, offer = product.get("sku"), product.get("offers")
    if not isinstance(sku, str) or not sku or not isinstance(offer, dict) or offer.get("@type") != "Offer":
        raise Deferred("Builder exact SKU/offer unavailable", 900)
    try:
        if builder_product(offer.get("url", ""))[1] != canonical:
            raise ValueError()
    except ValueError:
        raise Deferred("Builder changed the selected product", 900) from None
    price = dollars(offer.get("price"))
    if offer.get("priceCurrency") != "USD" or price is None or not 0 < price < 100_000:
        raise Deferred("Builder USD price unavailable", 900)
    condition = {"NewCondition": "new", "RefurbishedCondition": "refurbished", "UsedCondition": "used"}.get(
        str(offer.get("itemCondition", "")).rsplit("/", 1)[-1], "unknown")
    stock = {"InStock": "in_stock", "OutOfStock": "out_of_stock", "SoldOut": "out_of_stock",
             "Discontinued": "out_of_stock", "PreOrder": "preorder", "BackOrder": "backorder"}.get(
        str(offer.get("availability", "")).rsplit("/", 1)[-1], "unknown")
    return soup, product, offer, canonical, price, condition, stock


def _shipping(offer):
    shipping = offer.get("shippingDetails", [])
    shipping = [shipping] if isinstance(shipping, dict) else shipping
    rates = set()
    for detail in shipping if isinstance(shipping, list) else []:
        if not isinstance(detail, dict):
            continue
        destinations = detail.get("shippingDestination", [])
        destinations = [destinations] if isinstance(destinations, dict) else destinations
        rate = detail.get("shippingRate", {})
        if (any(isinstance(d, dict) and d.get("addressCountry") == "US" for d in destinations)
                and isinstance(rate, dict) and rate.get("currency") == "USD"):
            value = dollars(rate.get("value"))
            if value is not None:
                rates.add(value)
    return next(iter(rates)) if len(rates) == 1 else None


def parse_cyberpowerpc(body, url, now):
    soup, product, schema, url, price, condition, stock = _primary(body, url, "cyberpowerpc")
    form = soup.select_one("form#config_form")
    def field(name):
        tag = form.select_one(f'input[name="{name}"]') if form else None
        return tag.get("value") if tag else None
    if field("code") != product["sku"] or field("skey") != url.rsplit("/", 1)[-1]:
        raise Deferred("CyberPowerPC selected configuration mismatch", 900)
    if dollars(field("bp")) != price or dollars(field("fp")) != price:
        raise Deferred("CyberPowerPC selected price disagrees with product schema", 900)
    # Repeated mobile/desktop summaries must agree; never scan recommendations.
    specs = {"Model": product["sku"]}
    mapping = {"CPU": "CPU", "VIDEO": "GPU/VGA Type", "MEMORY": "Memory", "HDD": "SSD",
               "HDD2": "Secondary storage", "MOTHERBOARD": "Motherboard", "POWERSUPPLY": "Power Supply",
               "FAN": "CPU Cooler", "SERVICE": "Warranty", "RUSH": "Shipping service"}
    for key, label in mapping.items():
        values = {tag.get_text(" ", strip=True).removesuffix(" (Included)") for tag in
                  soup.select(f'[data-summary-sec="{key}"] [data-type="sumamry-sec-val"]')}
        if len(values) > 1:
            raise Deferred("CyberPowerPC selected specifications disagree", 900)
        if values:
            specs[label] = values.pop()
    if not gpu_model(specs.get("GPU/VGA Type", "")):
        return None
    # Scope availability to the selected product's purchase panel, not the footer.
    panels = soup.select("#content .col-xl-5")
    panels = [p for p in panels if p.select_one('[data-summary-sec="CPU"]')]
    if len(panels) != 1:
        raise Deferred("CyberPowerPC purchase panel unavailable", 900)
    panel = panels[0]
    text = panel.get_text(" ", strip=True)
    if re.search(r"sold out|out of stock|unavailable", text, re.I):
        stock = "out_of_stock"
    elif re.search(r"pre[- ]?order|back[- ]?order|special order", text, re.I):
        stock = "preorder"
    elif stock == "in_stock" and (not re.search(r"\bIn Stock\b", text, re.I)
                                     or not panel.select_one('[data-type="addtocart"]:not([disabled])')):
        stock = "unknown"
    title = "CyberPowerPC " + product["name"] + " · " + " · ".join(specs.get(k, "") for k in ("CPU", "GPU/VGA Type", "Memory", "SSD"))
    return Offer("cyberpowerpc", product["sku"], title, url, "CyberPowerPC", condition, specs,
                 price, _shipping(schema), stock, stock != "unknown" and condition != "unknown", now.isoformat(),
                 evidence="CyberPowerPC selected prebuilt schema, configuration and purchase panel")


def _sky_state(soup, sku):
    script = soup.select_one("#__NUXT_DATA__")
    try:
        data = json.loads(script.string) if script else None
        if not isinstance(data, list) or len(data) > 100_000:
            raise ValueError()
        def value(index, depth=0):
            if type(index) != int or index < 0 or index >= len(data) or depth > 12:
                raise ValueError()
            node = data[index]
            if isinstance(node, dict):
                return {k: value(v, depth+1) for k, v in node.items()}
            if isinstance(node, list):
                return [value(v, depth+1) for v in node]
            return node
        candidates = []
        for node in data:
            if not isinstance(node, dict):
                continue
            for key, index in node.items():
                if key.startswith("api:/products/" + sku + "?") and type(index) == int and 0 <= index < len(data):
                    raw = data[index]
                    if isinstance(raw, dict) and "sku" in raw and value(raw["sku"]) == sku:
                        # Decode only the selected fields, not the entire reference graph.
                        fields = ("sku", "source", "published", "is_deleted", "price", "in_stock", "stock",
                                  "quantity_available", "product_option_mark", "product_options")
                        candidates.append({k: value(raw[k]) for k in fields if k in raw})
        if len(candidates) != 1:
            raise ValueError()
        return candidates[0]
    except (ValueError, TypeError, KeyError, RecursionError):
        raise Deferred("Skytech selected product state unavailable", 900) from None


def parse_skytech(body, url, now):
    soup, product, schema, url, price, condition, stock = _primary(body, url, "skytech")
    if product["sku"].lower() != urlsplit(url).path.split("/")[2]:
        raise Deferred("Skytech changed the selected SKU", 900)
    state = _sky_state(soup, product["sku"])
    if (state.get("source") != "Complete" or type(state.get("published")) is not bool
            or state.get("is_deleted") is not False):
        raise Deferred("Skytech fixed complete PC unavailable", 900)
    unpublished = state["published"] is False
    if dollars(state.get("price")) != price:
        raise Deferred("Skytech selected price disagrees with product schema", 900)
    options = state.get("product_options") or {}
    if (not isinstance(options, dict) or set(options) - {"warranty"}
            or options.get("warranty") and not any(isinstance(w, dict) and w.get("open_mark") is True
                and dollars(w.get("price")) == 0 for w in options["warranty"])):
        raise Deferred("Skytech hardware/options require configuration review", 900)
    specs = {"Model": product["sku"]}
    for prop in product.get("additionalProperty", []):
        if isinstance(prop, dict) and prop.get("name") in {"CPU", "GPU", "RAM", "Storage", "Case", "CPU Cooler", "Motherboard", "Power Supply", "Warranty"}:
            key = {"GPU": "GPU/VGA Type", "RAM": "Memory"}.get(prop["name"], prop["name"])
            specs[key] = _text(prop.get("value"))
    if not gpu_model(specs.get("GPU/VGA Type", "")):
        return None
    if re.search(r"NVMe|SSD", specs.get("Storage", ""), re.I):
        specs["SSD"] = specs.pop("Storage")
    specs["Included components"] = "Component brands may vary; refer to published specifications."
    panel = soup.select_one('section[aria-labelledby="product-overview-heading"]')
    if panel is None:
        raise Deferred("Skytech selected product panel unavailable", 900)
    text = panel.get_text(" ", strip=True)
    buttons = [b for b in panel.select("button") if b.get_text(" ", strip=True).upper() == "ADD TO CART" and not b.has_attr("disabled")]
    evidence = "Skytech selected SKU schema and product state"
    if unpublished:
        unavailable_button = any(b.has_attr("disabled") and b.get_text(" ", strip=True).upper() in
                                 ("OUT OF STOCK", "SOLD OUT") for b in panel.select("button"))
        if stock != "out_of_stock" or not unavailable_button or buttons:
            raise Deferred("Skytech unpublished product availability conflicts or is unknown", 900)
        # A recognized withdrawn listing is a successful read, but its price
        # remains unverified and cannot enter history or produce a deal alert.
        evidence = "Skytech unpublished selected SKU; schema and disabled purchase button show out of stock"
    if state.get("in_stock") is False or re.search(r"sold out|out of stock", text, re.I):
        stock = "out_of_stock"
    elif re.search(r"pre[- ]?order|back[- ]?order|special order", text, re.I):
        stock = "preorder"
    elif stock == "in_stock":
        # Some pages advertise InStock with zero quantity_available. Treat that
        # disagreement as unknown, not an available PC or a restock event.
        qty, warehouse = state.get("quantity_available"), state.get("stock")
        if (state.get("in_stock") is not True or type(qty) not in (int, float) or not math.isfinite(qty) or qty <= 0
                or type(warehouse) not in (int, float) or not math.isfinite(warehouse) or warehouse <= 0 or not buttons):
            stock = "unknown"
            evidence = "Skytech stock signals incomplete or conflicting; availability needs confirmation"
    description = _text(product.get("description"))
    shipping = _shipping(schema)
    if shipping is None and re.search(r"\bfree shipping\b", description, re.I):
        shipping = 0.0
    title = "Skytech " + product["name"] + " Gaming PC · " + specs.get("Memory", "") + " · " + specs.get("SSD", "")
    return Offer("skytech", product["sku"], title, url, "Skytech", condition, specs, price, shipping,
                 stock, not unpublished and stock != "unknown" and condition != "unknown", now.isoformat(), evidence=evidence)


def parse_ibuypower_catalog(body, now):
    soup = BeautifulSoup(body, "html.parser")
    script = soup.select_one("#__NEXT_DATA__")
    try:
        data = json.loads(script.string)["props"]["pageProps"]
        if not all(isinstance(data.get(k), list) for k in ("models", "soldOutModels")):
            raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError):
        raise Deferred("iBUYPOWER RDY catalog schema unavailable", 900) from None
    offers = {}
    for group in ("models", "soldOutModels"):
        for row in data[group][:200]:
            model = row.get("FullContent", {}) if isinstance(row, dict) else {}
            if not isinstance(model, dict) or model.get("Prebuild") is not True or model.get("IsDesktop") is not True:
                continue
            try:
                _, url = builder_product("https://www.ibuypower.com/store/" + model.get("Link", ""))
            except (ValueError, TypeError):
                continue
            specs = {"Model": str(model.get("ModelId", ""))}
            skus = model.get("Skus", {})
            mapping = {"Processor": "CPU", "Video Card": "GPU/VGA Type", "Memory": "Memory",
                       "Primary Storage": "SSD", "Motherboard": "Motherboard", "Power Supply": "Power Supply",
                       "Processor Cooling": "CPU Cooler", "Warranty": "Warranty"}
            for component in skus.values() if isinstance(skus, dict) else []:
                if isinstance(component, dict) and component.get("Option") in mapping:
                    specs[mapping[component["Option"]]] = _text(component.get("Name"))
            if not gpu_model(specs.get("GPU/VGA Type", "")):
                continue
            price = dollars(model.get("Price"))
            if not specs["Model"] or price is None or not 0 < price < 100_000:
                continue
            title = "iBUYPOWER " + _text(model.get("Name")) + " Gaming PC · " + _text(model.get("ShortDescription"))
            stock = "out_of_stock" if group == "soldOutModels" or row.get("stock") == 0 else "unknown"
            offer = Offer("ibuypower", specs["Model"], title, url, "iBUYPOWER", "unknown", specs,
                          price, None, stock, False, now.isoformat(),
                          evidence="RDY catalog quote only; product-page price, condition, shipping and stock unverified")
            if url in offers and offers[url] != offer:
                raise Deferred("iBUYPOWER catalog contains conflicting configurations", 900)
            offers[url] = offer
    return list(offers.values())
