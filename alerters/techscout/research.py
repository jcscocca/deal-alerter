"""Current shopping evidence. No monitor, notifier, or price-history writes."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from statistics import mean

from dealcore.report import render_html
from dealcore.types import Card, Report
from alerters.hardware.desktop_profile import DEFAULT_PROFILE, DesktopProfile
from alerters.hardware.prebuilt import Offer, dollars, exact_desktop, gpu_model, pacific_time

from .walmart import WalmartError, item_ids

PRESETS = {
    "desktop-memory": ("RTX 5080 gaming desktop", "RTX 5090 gaming desktop"),
    "tablets": ("Apple iPad tablet", "Samsung Galaxy Tab tablet"),
    "computers": ("laptop computer", "desktop computer"),
    "supplies": ("USB C docking station", "computer monitor"),
    "memory": ("DDR5 SO-DIMM 32GB", "DDR5 SO-DIMM 48GB", "DDR5 SO-DIMM 96GB 2x48GB", "DDR5 desktop memory kit"),
}
# An already researched desktop remains visible even when search omits it.
DESKTOP_SEEDS = ("20707507998",)


def cpu_model(title: str) -> str | None:
    matches = re.findall(r"\b(?:[1-9]\d{3}X3D|[1-9]\d{3}[XF]|i[3579][-\s]\d{4,5}[A-Z]{0,3}|Ultra\s+[579]\s+\d{3}[A-Z]{0,2}(?:\s+Plus)?)\b", title, re.I)
    models = {re.sub(r"\s+", " ", value.upper()) for value in matches}
    return next(iter(models)) if len(models) == 1 else None


def text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def capacity_mismatch(category: str, title: str, queries: list[str]) -> bool:
    if category != "tablets":
        return False
    def capacities(value):
        return {float(amount) * (1000 if unit.lower() == "tb" else 1)
                for amount, unit in re.findall(r"\b(\d+(?:\.\d+)?)\s*(GB|TB)\b", value, re.I)}
    requested = [capacities(query) for query in queries]
    selected = capacities(title)
    # Some searches match a parent listing but lookup returns its default variant.
    return bool(selected and requested and all(values and not values & selected for values in requested))


def specs_from(row: dict) -> dict[str, str]:
    attributes = row.get("attributes")
    if not isinstance(attributes, dict):
        return {}
    aliases = {"rammemory": "RAM", "rammemorysize": "Memory Size", "systemmemory": "System Memory",
               "memorytype": "Memory Type", "memoryslots": "Memory Slots",
               "maximummemorysupported": "Maximum Memory Supported",
               "memoryslotsavailable": "Memory Slots Available"}
    result = {}
    for name, value in attributes.items():
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            continue
        normal = re.sub(r"[^a-z0-9]", "", name.lower())
        label = aliases.get(normal, name)
        # Keep conflicting aliases for the profile to detect, not last-write-wins.
        if label in result and result[label] != str(value):
            label = name
        result[label] = str(value)
    return result


@dataclass
class Product:
    item_id: str
    title: str
    seller: str
    condition: str
    price: float | None
    shipping: float | None
    stock: str
    available: bool
    model: str
    specs: dict[str, str]
    queries: list[str]
    memory_fit: dict | None = None
    comparison_key: tuple[str, ...] | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def url(self):
        # Do not trust arbitrary URLs in third-party API data.
        return f"https://www.walmart.com/ip/{self.item_id}"


def normalize(row: dict, queries: list[str], category: str, profile: DesktopProfile,
              observed_at: str) -> Product | None:
    try:
        item_id = item_ids([row.get("itemId")])[0]
    except ValueError:
        return None
    title = text(row.get("name"))
    if not title:
        return None
    specs = specs_from(row)
    stock = text(row.get("stock")) or "Not published"
    available = row.get("availableOnline") is True and stock.lower() in {"available", "in stock", "in_stock"}
    price, shipping = dollars(row.get("salePrice")), dollars(row.get("standardShipRate"))
    product = Product(item_id, title, text(row.get("sellerInfo")) or "Not published",
                      text(row.get("conditionName")) or "Not published", price, shipping,
                      stock, available, text(row.get("modelNumber")), specs, queries)
    if shipping is None:
        product.warnings.append("Shipping not published; the displayed price is not a delivered total.")
    if not available:
        product.warnings.append("Online availability is unconfirmed or unavailable for this ZIP; excluded from averages.")
    ambiguous = bool(re.search(r"\b(?:up to|select your|choose your|various configurations)\b", title, re.I))
    if ambiguous:
        product.warnings.append("Selected configuration is ambiguous; excluded from averages.")
    mismatch = capacity_mismatch(category, title, queries)
    if mismatch:
        product.warnings.append("The selected item's capacity differs from the requested search; verify the variant. Excluded from averages.")

    if category == "desktop-memory":
        owned_model = profile.memory["owned_kit"].split()[-1]
        if owned_model.casefold() in (title + " " + product.model).casefold():
            product.warnings.append("Owned-kit reference only; no additional kit is included in the desktop budget.")
        elif exact_desktop(title) and not re.search(r"\b(?:case only|case for|enclosure|waterblock)\b", title, re.I):
            offer = Offer("walmart", item_id, title, product.url, product.seller, product.condition,
                          specs, price, shipping, "in_stock" if available else "unknown", available, observed_at)
            fit = profile.assess_memory(offer)
            product.memory_fit = asdict(fit)
            # Keep off-plan configurations visible with their rejection reason.
            product.warnings.append(fit.summary)
            memory_type = " ".join([title, *(specs.get(key, "") for key in
                                           ("RAM", "Memory Type", "Memory Size", "System Memory"))])
            if fit.eligible and fit.installed_gb in (32, 64) and re.search(r"\bDDR5\b", memory_type, re.I):
                # Require an exact CPU and one stated SSD capacity for build cohorts.
                cpu = cpu_model(title)
                storage = re.findall(r"\b(\d+(?:\.\d+)?)\s*(TB|GB)\s*(?:Gen[345]\s+)?(?:NVMe\s+)?SSD\b", title, re.I)
                if cpu and len(storage) == 1:
                    amount, unit = storage[0]
                    capacity = float(amount) * (1000 if unit.upper() == "TB" else 1)
                    product.comparison_key = ("desktop", f"RTX {gpu_model(title)}", cpu,
                                              f"{fit.installed_gb}GB DDR5 RAM", f"{capacity:g}GB SSD",
                                              product.condition.lower())
        else:
            return None
    # Generic categories compare the same published model and title, not unlike devices.
    if product.memory_fit is None and product.model:
        product.comparison_key = ("model", product.model.casefold(), " ".join(title.casefold().split()),
                                  product.condition.lower(), json_specs(specs))
    if ambiguous or mismatch or not available or price is None or price <= 0 or product.seller == "Not published" or product.condition == "Not published":
        product.comparison_key = None
    return product


def json_specs(specs: dict) -> str:
    # Equal marketing names/model families may still have different variants.
    return json.dumps({key.casefold(): value.casefold() for key, value in specs.items()}, sort_keys=True)


@dataclass
class Research:
    category: str
    zip_code: str
    observed_at: str
    queries: list[str]
    coverage: list[dict]
    products: list[Product]
    problems: list[str]
    excluded: int = 0

    def averages(self) -> list[dict]:
        groups = defaultdict(list)
        for product in self.products:
            if product.comparison_key:
                groups[product.comparison_key].append(product)
        return [{"configuration": list(key), "count": len(rows),
                 "mean_item_price": round(mean(p.price for p in rows), 2),
                 "min_item_price": min(p.price for p in rows), "max_item_price": max(p.price for p in rows),
                 "item_ids": [p.item_id for p in rows]}
                for key, rows in groups.items() if len(rows) >= 2]

    def document(self):
        return {**asdict(self), "averages": self.averages()}

    def html(self) -> str:
        cards = []
        for product in self.products:
            fit = product.memory_fit
            badge = fit["status"] if fit else "PRODUCT RESEARCH"
            cards.append(Card(
                title=product.title, url=product.url,
                price=f"${product.price:,.2f} before tax" if product.price is not None else "Price not published",
                badge=badge,
                headline="Available online" if product.available else "Unavailable / needs availability check",
                reason="Current Walmart product lookup for ZIP " + self.zip_code,
                facts=(f"Seller: {product.seller} · Condition: {product.condition}",
                       f"Item {product.item_id} · Model: {product.model or 'not published'}",
                       f"Shipping: ${product.shipping:,.2f}" if product.shipping is not None else "Shipping: unknown",
                       "Found through: " + "; ".join(product.queries)),
                warnings=tuple(product.warnings),
            ))
        averages = self.averages()
        comparison = [f"Selected-sample average: ${row['mean_item_price']:,.2f} across {row['count']} current offers — "
                      + ", ".join(row["configuration"][1:]) + ". Item prices before shipping and tax."
                      for row in averages]
        if not averages:
            comparison = ["No comparable cohort with at least two available, identified offers. No average calculated."]
        coverage = [f"Search {row['query']!r}: {row['returned']} of {row['total'] if row['total'] is not None else 'unknown'} results inspected."
                    for row in self.coverage]
        purpose = ("Start with factory 32GB/64GB RTX 5080/5090 desktops and assess reuse of your owned 64GB DDR5 kit. "
                   if self.category == "desktop-memory" else "Compare the products returned by your selected shopping searches. ")
        report = Report(
            subject="TechScout shopping research", heading="TechScout · " + self.category.replace("-", " & "),
            summary=purpose + f"{len(cards)} product cards · ZIP {self.zip_code} · checked {pacific_time(self.observed_at)}.",
            footer="Bounded current snapshot, not a market-wide average. Availability and checkout totals can change. "
                   "Build cohorts match CPU, GPU, RAM capacity and SSD capacity; other components can differ. "
                   "No purchase or RAM compatibility guarantee. No automated alerts or historical price tracking.",
            buys=tuple(cards), problems=tuple(self.problems + comparison + coverage +
                                            ([f"{self.excluded} unmatched or invalid products omitted."] if self.excluded else [])))
        return render_html(report).replace("<html>", '<html lang="en"><head><meta charset="utf-8">'
                                          '<meta name="viewport" content="width=device-width,initial-scale=1">'
                                          '<title>TechScout shopping research</title></head>')


def research(client, category: str = "desktop-memory", *, queries=None, seeds=None,
             limit: int = 10, profile: DesktopProfile | None = None, now=None) -> Research:
    if category not in PRESETS:
        raise ValueError("Unknown shopping category")
    profile = profile or DesktopProfile(DEFAULT_PROFILE)
    default_queries = list(PRESETS[category])
    if category == "desktop-memory":
        default_queries.append(profile.memory["owned_kit"].split()[-1])
    queries = list(dict.fromkeys(default_queries if queries is None else queries))
    if not 1 <= len(queries) <= 4 or any(not isinstance(q, str) or not q.strip() or len(q) > 200 for q in queries):
        raise ValueError("Choose one to four searches of 1-200 characters")
    if not 1 <= limit <= 25:
        raise ValueError("Search limit must be between 1 and 25")
    seeds = (DESKTOP_SEEDS if category == "desktop-memory" else ()) if seeds is None else seeds
    seeds = item_ids(seeds) if seeds else []
    observed_at = (now or datetime.now(timezone.utc)).isoformat()
    result = Research(category, client.zip_code, observed_at, queries, [], [], [])
    found = {item_id: ["Saved desktop candidate"] for item_id in seeds}
    for query in queries:
        try:
            rows, total = client.search(query, limit)
        except WalmartError as error:
            result.problems.append(str(error))
            if client.stopped:
                break
            continue
        result.coverage.append({"query": query, "returned": len(rows), "total": total})
        for row in rows:
            try:
                item_id = item_ids([row.get("itemId")])[0]
            except ValueError:
                result.excluded += 1
                continue
            found.setdefault(item_id, []).append(query)
    ids = list(found)
    seen = set()
    for start in range(0, len(ids), 20):
        if client.stopped:
            break
        batch = ids[start:start + 20]
        try:
            rows = client.lookup(batch)
        except WalmartError as error:
            result.problems.append(str(error))
            if client.stopped:
                break
            continue
        returned = {str(row.get("itemId")) for row in rows}
        missing = set(batch) - returned
        if missing:
            result.problems.append(f"Localized lookup omitted {len(missing)} requested products; search prices were not substituted.")
        for row in rows:
            item_id = str(row.get("itemId"))
            if item_id in seen:
                continue
            seen.add(item_id)
            product = normalize(row, found[item_id], category, profile, observed_at)
            if product:
                result.products.append(product)
            else:
                result.excluded += 1
    result.products.sort(key=lambda p: (not p.available, bool(p.memory_fit and not p.memory_fit["eligible"]),
                                        p.price is None, p.price or 0, p.item_id))
    return result
