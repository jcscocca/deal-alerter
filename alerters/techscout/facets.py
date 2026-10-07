"""Display-only attributes for independent shopping filters, never ranking evidence."""
from __future__ import annotations

import re

from alerters.hardware.native.catalog import Kind
from alerters.hardware.native.match import find_all_parts
from .research import cpu_model

UNKNOWN = "Not established"


def one(values):
    values = {value for value in values if value}
    return next(iter(values)) if len(values) == 1 else None


def gpu(title):
    # An option/roundup naming several models cannot claim one selected GPU.
    if re.search(r"\b\d{4}\s*(?:/|\bor\b)\s*(?:RTX\s*)?\d{4}\b", title, re.I):
        return None
    consumer = re.findall(r"\b(RTX|GTX|RX)\s*[- ]?\s*(\d{4}(?:\s*(?:TI|SUPER|XTX|XT))*)\b", title, re.I)
    if consumer:
        return one(family.upper() + " " + re.sub(r"\s+", " ", re.sub(r"(?<=\d)(?=[A-Z])", " ", model.upper())) for family, model in consumer)
    # Catalog matching also covers professional and datacenter cards. Require
    # GPU context so a Dell OptiPlex 5090 is not treated as an RTX 5090.
    if not re.search(r"\b(?:RTX|GTX|Radeon|NVIDIA|GeForce|Quadro|Tesla|GPU|[AHL]\d{2,3})\b", title, re.I):
        return None
    return one(re.sub(r"\s+\d+GB\b", "", part.name).upper()
               for part in find_all_parts(title) if part.kind != Kind.UNIFIED)


def ram(title):
    # Explicit RAM/DDR/unified-memory evidence only: 32GB GDDR7 is GPU VRAM,
    # and an unqualified 256GB tablet capacity is normally storage.
    if re.search(r"\b(?:up to|max(?:imum)?|choose|select)\b", title, re.I):
        return None
    if re.search(r"\b\d+\s*GB\s*(?:/|\bor\b)\s*\d+\s*GB\b", title, re.I):
        return None
    kit_pattern = r"\b(\d+)\s*[x×]\s*(\d+)\s*GB\s*(?:DDR[345]\b|RAM\b)"
    kits = re.findall(kit_pattern, title, re.I)
    without_kits = re.sub(kit_pattern, "", title, flags=re.I)
    matches = re.findall(r"(?<![\w.])(\d+)\s*GB\s*(?:\(\s*\d+\s*[x×]\s*\d+\s*GB\s*\)\s*)?(?:DDR[345]\b|RAM\b|(?:system|unified)\s+memory\b)", without_kits, re.I)
    values = {int(value) for value in matches} | {int(count) * int(size) for count, size in kits}
    capacity = one(values)
    return f"{capacity}GB" if capacity and capacity <= 4096 else None


def storage(title):
    values = {float(size) * (1000 if unit.upper() == "TB" else 1)
              for size, unit in re.findall(r"\b(\d+(?:\.\d+)?)\s*(TB|GB)\s*(?:Gen[345]\s+)?(?:NVMe\s+)?SSD\b", title, re.I)}
    capacity = one(values)
    if not capacity:
        return None
    return f"{capacity / 1000:g}TB SSD" if capacity >= 1000 else f"{capacity:g}GB SSD"


def attributes(row):
    """Use projected specs where available and conservative title evidence elsewhere.

    Merged reports contribute only when their stated values agree. These fields
    describe listings; they never establish availability or memory compatibility.
    """
    titles = [report["title"] for report in row.get("reports", [])] or [row["title"]]
    condition = re.sub(r"[-_\s]+", " ", row.get("condition", "").strip().lower())
    condition = {"new": "New", "used": "Used", "open box": "Open box", "refurbished": "Refurbished"}.get(condition, condition.capitalize())
    if condition in ("", "Not published", "Unknown", "Not established"):
        condition = UNKNOWN
    return {
        "gpu": one(gpu(title) for title in titles) or UNKNOWN,
        "ram": f"{row['ram']}GB" if type(row.get("ram")) is int and row["ram"] > 0 else one(ram(title) for title in titles) or UNKNOWN,
        "cpu": one(cpu_model(title) for title in titles) or UNKNOWN,
        "storage": one(storage(title) for title in titles) or UNKNOWN,
        "condition": condition,
    }
