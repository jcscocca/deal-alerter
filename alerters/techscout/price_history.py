"""Exact-configuration history captured only by an explicit Walmart research run."""
from dataclasses import asdict
import re

from alerters.hardware.prebuilt import exact_desktop
from alerters.hardware.price_evidence import PriceEvidence, configuration_key, positive


def walmart_key(product, zip_code):
    return configuration_key("walmart", product.get("item_id"), product.get("seller"),
                             product.get("condition"), product.get("title"),
                             product.get("specs", {}), zip_code)


def record_research(directory, research):
    history = PriceEvidence(directory / "walmart-prebuilt-observations.json")
    for product in research.products:
        p = asdict(product)
        if (not exact_desktop(product.title) or not product.available
                or product.stock.lower().replace("_", " ") not in ("available", "in stock")
                or product.condition.lower() not in ("new", "used", "refurbished", "open box", "open_box")
                or not product.seller.strip() or product.seller == "Not published"
                or not positive(product.price) or product.shipping is None
                or re.search(r"\b(?:up to|select your|choose your|various configurations|case only)\b", product.title, re.I)):
            continue
        history.record(walmart_key(p, research.zip_code), round(product.price + product.shipping, 2), research.observed_at)
    if history.rows:
        history.save()
