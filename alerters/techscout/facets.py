"""Display-only attributes for independent shopping filters, never ranking evidence."""
from __future__ import annotations

import re

from alerters.hardware.native.catalog import Kind
from alerters.hardware.native.match import find_all_parts
from alerters.hardware.memory import standalone_memory, configuration as sodimm_configuration, LAYOUTS, layout_label
from alerters.hardware.displays import specifications as display_specifications
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
               for part in find_all_parts(title) if part.kind not in (Kind.UNIFIED, Kind.PRODUCT))


def ram(title):
    if key := sodimm_configuration(title):
        count, size, _ = LAYOUTS[key]
        return f"{count * size}GB"
    # Explicit RAM/DDR/unified-memory evidence only: 32GB GDDR7 is GPU VRAM,
    # and an unqualified 256GB tablet capacity is normally storage.
    if re.search(r"\b(?:choose|select)\b|\b(?:up to|max(?:imum)?|supports?)\s+\d+\s*GB\b", title, re.I):
        return None
    if re.search(r"\b\d+\s*GB\s*(?:/|\bor\b)\s*\d+\s*GB\b", title, re.I):
        return None
    kit_pattern = r"\b(\d+)\s*[x×]\s*(\d+)\s*GB\s*(?:DDR[345]\b|RAM\b)"
    kits = re.findall(kit_pattern, title, re.I)
    without_kits = re.sub(kit_pattern, "", title, flags=re.I)
    matches = re.findall(r"(?<![\w.])(\d+)\s*GB\s*(?:\(\s*\d+\s*[x×]\s*\d+\s*GB\s*\)\s*)?(?:DDR[345]\b|RAM\b|(?:system|unified)\s+memory\b)", without_kits, re.I)
    values = {int(value) for value in matches} | {int(count) * int(size) for count, size in kits}
    values |= {int(value) for value in re.findall(r"\bDDR[345]\s+(\d+)\s*GB(?=\s*(?:\(|RAM\b|memory\b|$))", title, re.I)}
    capacity = one(values)
    return f"{capacity}GB" if capacity and capacity <= 4096 else None


def storage(title):
    values = {float(size) * (1000 if unit.upper() == "TB" else 1)
              for size, unit in re.findall(r"\b(\d+(?:\.\d+)?)\s*(TB|GB)\s*(?:Gen[345]\s+)?(?:NVMe\s+)?SSD\b", title, re.I)}
    capacity = one(values)
    if not capacity:
        return None
    return f"{capacity / 1000:g}TB SSD" if capacity >= 1000 else f"{capacity:g}GB SSD"


def product_type(title):
    from .scope import subject_title
    title = subject_title(title)
    if standalone_memory(title) or sodimm_configuration(title):
        return "Memory"
    if re.search(r"\bmonitor\s+(?:arm|stand|mount|power\s+(?:supply|adapter))\b", title, re.I):
        return "Accessories"
    if (display_specifications(title)
            or re.search(r"\b\d{2}(?:\.\d)?[- ]?(?:inch|in)\b.*\bmonitor\b", title, re.I)
            and not re.search(r"\b(?:dock|docking|dual\s+monitor|monitor\s+(?:arm|stand|mount))\b", title, re.I)):
        return "Monitors"
    # Form-factor words describe individual products too. They must not turn
    # desktop memory, a desktop CPU or a laptop dock into a complete computer.
    for label, pattern in (
        ("Memory", r"\b(?:desktop|laptop|PC)\s+(?:RAM|memory)\b|\b(?:SO[- ]?DIMM|UDIMM)\b"),
        ("Graphics cards", r"\bdesktop\s+(?:(?:graphics|video)\s+card|GPU)\b"),
        ("Components", r"\bdesktop\s+(?:CPU|processor|power supply|PSU|cooler)\b|\b(?:PC|ATX|ITX|micro[- ]?ATX)\s+case\b"),
        ("Storage", r"\b(?:desktop|laptop|PC)\s+(?:NVMe\s+)?SSD\b"),
        ("Monitors", r"\bdesktop\s+monitor\b"),
    ):
        if re.search(pattern, title, re.I):
            return label
    for label, pattern in (
        ("Accessories", r"\b(?:backpack|sleeve|case for|cover for|bag|insect bite|screen protector)\b|\b(?:iPad|tablet|laptop|MacBook|Galaxy Tab(?:\s+(?!(?:with|includes?|including)\b)\w+){0,3})\s+(?:keyboard\s+cover|case|cover|stand)\b"),
        ("Docks & hubs", r"\b(?:dock|docking|hub|KVM)\b"),
        ("Tablets", r"\b(?:iPad|tablet|Galaxy Tab)\b"),
        ("Laptops", r"\b(?:laptop|notebook|MacBook)\b"),
        ("Desktops", r"\b(?:desktop|gaming (?:PC|computer)|mini PC|Mac mini|Mac Studio|Mac Pro|workstation PC|AI workstation)\b"),
        ("Monitors", r"\b(?:monitor|UltraWide|display)\b"),
        ("Storage", r"\b(?:SSD|NVMe|hard drive|flash drive|microSD|SD card|NAS)\b"),
        ("Components", r"\b(?:motherboard|PSU|power supply|CPU|processor|cooler|Ryzen|Threadripper|PC case|computer case)\b|\b(?:Intel\s+)?Core\s+(?:i[3579]|Ultra)\b"),
        ("Graphics cards", r"\b(?:GDDR\d|GPU|graphics card|GeForce|Radeon|RTX|GTX)\b"),
        ("Memory", r"\b(?:DDR[345]|DIMM|memory kit|RAM)\b"),
        ("Keyboards & mice", r"\b(?:keyboard|mouse|mice|trackpad)\b"),
        ("Audio", r"\b(?:headphone|headphones|earbuds|AirPods|speaker|headset|microphone)\b"),
        ("Networking", r"\b(?:router|modem|mesh|network switch|Wi[- ]?Fi|Ethernet)\b"),
        ("Accessories", r"\b(?:USB|Thunderbolt|charger|charging|power bank|power strip|webcam)\b"),
    ):
        if re.search(pattern, title, re.I):
            return label
    return "Other tech"


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
    kind = product_type(row.get("product_name") or row["title"])
    if kind == "Other tech":
        kind = product_type(row["title"])
    if row.get("is_system") is True and kind not in ("Laptops", "Tablets"):
        kind = "Desktops"
    return {
        "kind": kind,
        "gpu": one(gpu(title) for title in titles) or UNKNOWN,
        "ram": f"{row['ram']}GB" if type(row.get("ram")) is int and row["ram"] > 0 else one(ram(title) for title in titles) or UNKNOWN,
        "cpu": one(cpu_model(title) for title in titles) or UNKNOWN,
        "storage": one(storage(title) for title in titles) or UNKNOWN,
        "condition": condition,
        "memory_layout": one(layout_label(title) for title in titles) or UNKNOWN,
        "ports": one(display.ports for title in titles if (display := display_specifications(title))) or UNKNOWN,
    }
