"""Bounded UI subscriptions. They narrow delivery, never change deal judgments."""
from __future__ import annotations

import hashlib
import json
import math
import re

from alerters.techscout.facets import attributes

CATEGORIES = {"monitor", "amazon", "desktop-memory", "computers", "tablets", "memory", "supplies"}
FACETS = {"kind", "gpu", "ram", "cpu", "storage", "condition", "memory_layout"}


def defaults():
    return {"version": 1, "mode": "all", "watches": []}


def validate(data):
    if not isinstance(data, dict) or set(data) != {"version", "mode", "watches"} or data["version"] != 1 or data["mode"] not in ("all", "watches", "paused"):
        raise ValueError("Invalid watch settings")
    if not isinstance(data["watches"], list) or len(data["watches"]) > 40:
        raise ValueError("At most 40 watches are supported")
    ids = set()
    for watch in data["watches"]:
        if not isinstance(watch, dict) or set(watch) != {"id", "name", "enabled", "category", "filters", "source", "budget", "reuse", "product_id"}:
            raise ValueError("Invalid watch fields")
        if not isinstance(watch["id"], str) or not re.fullmatch(r"[a-f0-9]{16,32}", watch["id"]) or watch["id"] in ids:
            raise ValueError("Invalid watch ID")
        ids.add(watch["id"])
        if not isinstance(watch["name"], str) or not 1 <= len(watch["name"].strip()) <= 80 or any(ord(c) < 32 for c in watch["name"]):
            raise ValueError("Watch name must have 1–80 characters")
        if type(watch["enabled"]) is not bool or type(watch["reuse"]) is not bool or watch["category"] not in CATEGORIES:
            raise ValueError("Invalid watch preference")
        if not isinstance(watch["filters"], dict) or set(watch["filters"]) - FACETS or any(not isinstance(v, str) or not 1 <= len(v) <= 100 for v in watch["filters"].values()):
            raise ValueError("Invalid watch filters")
        if not isinstance(watch["source"], str) or not re.fullmatch(r"[a-z-]{1,40}", watch["source"]):
            raise ValueError("Invalid source")
        budget = watch["budget"]
        if budget is not None and (type(budget) not in (int, float) or not math.isfinite(budget) or not 0 <= budget <= 999999):
            raise ValueError("Invalid maximum price")
        if not isinstance(watch["product_id"], str) or watch["product_id"] and not re.fullmatch(r"(?:\d{1,20}|[a-z-]+:[a-f0-9]{24})", watch["product_id"]):
            raise ValueError("Invalid product")
    return data


def read_controls(path):
    if not path.exists():
        return defaults(), None
    try:
        if path.stat().st_size > 64000:
            raise ValueError()
        return validate(json.loads(path.read_text(encoding="utf-8-sig"))), None
    except (OSError, ValueError, TypeError, KeyError):
        return {"version": 1, "mode": "paused", "watches": []}, "Watch settings could not be read; notifications are paused until repaired."


def product_identity(item):
    if item.key.startswith("prebuilt/"):
        source = item.key.split("/", 1)[1].split(":", 1)[0]
        identity = item.key
    else:
        source = item.detail.source.split("/", 1)[0]
        identity = str(item.detail.listing_id)
    return source, source + ":" + hashlib.sha256(identity.encode()).hexdigest()[:24]


def matches(watch, item, plugin):
    from alerters.techscout.monitor_bridge import categories
    source, identity = product_identity(item)
    detail = item.detail
    if not watch["enabled"] or watch["source"] not in ("all", source) or watch["product_id"] and watch["product_id"] != identity:
        return False
    kinds = categories(detail.title, detail.is_system)
    if watch["category"] != "monitor" and watch["category"] not in kinds:
        return False
    if watch["budget"] is not None and (item.price <= 0 or detail.total_price > watch["budget"]):
        return False
    fit = getattr(plugin, "memory_fits", {}).get(item.key)
    facets = attributes({"title": detail.title, "condition": detail.condition,
                         "ram": getattr(fit, "installed_gb", None)})
    if any(facets[key] != value for key, value in watch["filters"].items()):
        return False
    if watch["reuse"] and facets["kind"] == "Desktops":
        if not fit or not fit.eligible:
            return False
    return True


def delivery_filter(data, plugin):
    if data["mode"] == "all":
        return None
    return lambda item: data["mode"] == "watches" and any(matches(w, item, plugin) for w in data["watches"])
