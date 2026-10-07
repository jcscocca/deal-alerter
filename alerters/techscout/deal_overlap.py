"""Conservative product matching for unverified publisher reports, never inventory."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re
import unicodedata
from urllib.parse import parse_qs, unquote, urlsplit


def card_id(value):
    return "deal:" + hashlib.sha256(value.encode()).hexdigest()[:24]


def amazon_asin(value):
    """Read a US Amazon product ID, including an embedded destination URL. No I/O."""
    if not isinstance(value, str) or len(value) > 4000:
        return None
    for _ in range(3):
        try:
            url = urlsplit(value)
            if url.hostname in {"amazon.com", "www.amazon.com", "smile.amazon.com"} and not url.username:
                match = re.search(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})(?:/|$)", url.path, re.I)
                return match[1].upper() if match else None
            nested = [v for values in parse_qs(url.query).values() for v in values if "amazon.com/" in unquote(v)]
            if len(nested) != 1:
                return None
            value = unquote(nested[0])
        except ValueError:
            return None
    return None


def product_name(title):
    """Remove only the trailing price/shipping clause; retain all variant words."""
    text = unicodedata.normalize("NFKC", title).casefold()
    text = re.sub(r"^(?:prime members?\s*:\s*|\[prime\]\s*)", "", text)
    text = re.split(r"\s+(?:for\s+|from\s+|at\s+|[-–—]\s*)?\$\d", text, maxsplit=1)[0]
    text = re.sub(r"\bw/", "with ", text)
    return " ".join(re.findall(r"[a-z0-9]+", text))


def name_key(row):
    # Exact names only. Editorial roundups and short generic names aren't products.
    name = product_name(row.get("product_name") or row["title"])
    if len(name.split()) < 4 or not re.search(r"\d", name) or re.search(r"\b(?:deals|sale|save|up to|starting|more|roundup|off)\b", name):
        return None
    return name


def condition(title):
    for word in ("refurbished", "renewed", "open box", "used"):
        if word in re.sub(r"[-_]", " ", title.casefold()):
            return word
    return "unspecified"


VARIANTS = (r"\b\d+(?:\.\d+)?\s*(?:TB|GB)\b", r"\b\d+[- ](?:pack|count)\b",
            r"\b(?:black|white|silver|blue|red|pink|purple|gr[ae]y|green|gold)\b",
            r"\b\d+(?:\.\d+)?[ -]?(?:inch|inches)\b")


def variants(title):
    return [{re.sub(r"[\s-]+", "", v).lower().replace("grey", "gray") for v in re.findall(pattern, title, re.I)}
            for pattern in VARIANTS]


def compatible(left, right):
    if left.get("merchant") != right.get("merchant") or not left.get("merchant"):
        return False
    if condition(left["title"]) != condition(right["title"]):
        return False
    if left.get("asin") and right.get("asin") and left["asin"] != right["asin"]:
        return False
    # The same ASIN with contradicting capacities/quantities is still ambiguous.
    for a, b in zip(variants(left["title"]), variants(right["title"])):
        if a and b and a != b:
            return False
    return True


def combine_leads(rows):
    """One card per well-evidenced product; preserve every quote and source URL."""
    groups = []
    for row in sorted(rows, key=lambda r: (r.get("asin") or "", r["id"]), reverse=True):
        name = name_key(row)
        matches = [g for g in groups if all(compatible(row, other) for other in g)
                   and any((row.get("asin") and row.get("asin") == other.get("asin"))
                           or (name and name == name_key(other)) for other in g)]
        # A vague name must not bridge two distinct ASIN groups.
        if len(matches) == 1:
            matches[0].append(row)
        else:
            groups.append([row])
    cards = []
    for group in groups:
        group.sort(key=lambda r: (r.get("published_at") or r.get("checked_at") or "", r["id"]), reverse=True)
        card = deepcopy(group[0])
        asins = {r["asin"] for r in group if r.get("asin")}
        names = sorted({name_key(r) for r in group if name_key(r)})
        merchant = card.get("merchant")
        variant = ":".join(sorted({v for r in group for values in variants(r["title"]) for v in values}))
        key = f"{merchant}:asin:{next(iter(asins))}:{condition(card['title'])}:{variant}" if len(asins) == 1 else (
            f"{merchant}:name:{names[0]}:{condition(card['title'])}" if merchant and names else None)
        # Contradictory ASIN variants can have identical identity keys; disambiguate.
        if key and any(c["id"] == card_id(key) for c in cards):
            key += ":" + product_name(card["title"])
        card["id"] = card_id(key) if key else card["id"]
        card["aliases"] = sorted({r["id"] for r in group} | {card["id"]} |
                                 {card_id(f"{merchant}:name:{n}:{condition(card['title'])}") for n in names})
        card["sources"] = sorted({r["source"] for r in group})
        card["reports"] = [{k: r.get(k) for k in ("id", "source", "retailer", "title", "url", "price",
                            "published_at", "checked_at", "expires_at", "description", "terms", "reasons")}
                           for r in group]
        card["match_basis"] = ("Same Amazon product ID" if all(r.get("asin") for r in group) else "Amazon product ID and exact product name") if len(asins) == 1 and len(group) > 1 else (
            "Exact product name and retailer" if len(group) > 1 else "Single source report")
        prices = sorted({r["price"] for r in group if r.get("price") is not None})
        card["reported_prices"] = prices
        card["price"] = prices[0] if len(prices) == 1 else None
        card["expires_at"] = max((r.get("expires_at") or 0 for r in group), default=0)
        card["retailer"] = merchant or card["retailer"]
        card["total"], card["available"], card["rank"] = None, False, None
        card["reasons"] = ["Publisher reports; Amazon price, seller and availability need confirmation" if merchant == "Amazon"
                           else "Community reports; retailer price and availability need confirmation"]
        cards.append(card)
    return sorted(cards, key=lambda r: (len(r["sources"]), r.get("published_at") or r.get("checked_at") or ""), reverse=True)
