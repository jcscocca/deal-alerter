"""The current shopping interests: individual computer parts and peripherals.

Apply this to new fetches and saved snapshots alike, so an old desktop search
cannot bring a completed buying project back into the feed.
"""
from __future__ import annotations

import re

PART_KINDS = {"Graphics cards", "Components", "Storage", "Memory"}
SUPPLY_KINDS = {"Docks & hubs", "Keyboards & mice", "Audio", "Networking", "Accessories"}
KINDS = PART_KINDS | SUPPLY_KINDS | {"Monitors"}
# PRODUCT is a price-only judgment category, also used by memory and displays.
# Only explicitly identified computer products should be excluded here.
MACHINE_PRODUCT_KEYS = {"zenbook_duo_2026_x9_388h"}

COMPUTER = re.compile(
    r"\b(?:pre[- ]?built|gaming\s+(?:pc|computer|desktop)|desktop\s+(?:pc|computer|system)|"
    r"mini\s*pc|all[- ]in[- ]one\s+(?:pc|computer)|Mac\s+(?:mini|Studio|Pro)|iMac|"
    r"Framework\s+Desktop|Alienware\s+Aurora|OptiPlex|OMEN\s+(?:MAX\s+)?\d+L|"
    r"MSI\s+(?:Aegis|Codex|Trident|Infinite)|Lenovo\s+Legion\s+Tower|"
    r"HP\s+(?:Envy\s+x360|Victus\s+\d+)|ASUS\s+ROG\s+(?:Strix\s+G\d+|Zephyrus)|"
    r"Skytech\s+(?:Azure|Chronos|Blaze|Shadow|Prism|Archangel|Shiva)|"
    r"CyberPowerPC\s+Gamer|iBUYPOWER\s+(?:RDY|Y40|Y60)|"
    r"(?:workstation|render|compute)\s+(?:pc|node)|DGX\s+(?:Spark|Station))\b", re.I
)
# A component's compatibility target is not the item being sold. Only strip a
# suffix after a recognizable product noun, never the beginning of a PC title.
PRODUCT_NOUN = re.compile(
    r"\b(?:SSD|NVMe|RAM|DDR[345]|SO[- ]?DIMM|UDIMM|memory\s+(?:kit|module)|"
    r"graphics\s+card|video\s+card|GPU|RTX|GTX|Radeon|processor|CPU|motherboard|"
    r"power\s+supply|PSU|cooler|case|monitor|dock|docking|hub|KVM|keyboard|mouse|"
    r"headset|headphones?|speaker|microphone|router|charger|cable|adapter|sleeve|"
    r"backpack|cover|protector|webcam)\b", re.I
)
COMPATIBILITY = re.compile(r"\b(?:for(?!\s+sale\b)(?:\s+use\s+with)?|compatible(?:\s+with)?|works\s+with|designed\s+for|(?:pulled|removed)\s+from)\b", re.I)


def subject_title(title: str) -> str:
    """Return the product wording shared by scope checks and display facets."""
    if not isinstance(title, str):
        return ""
    for match in COMPATIBILITY.finditer(title):
        if PRODUCT_NOUN.search(title[:match.start()]):
            title = title[:match.start()].strip()
            break
    # A case is a component even when its advertised form factor says desktop,
    # gaming PC or tower. Complete configurations are checked independently.
    title = re.sub(r"\b(?:gaming\s+pc|desktop(?:\s+computer)?|computer|mid[- ]?tower|full[- ]?tower)\s+case\b",
                   "PC case", title, flags=re.I)
    return title


def _computer_configuration(title: str) -> bool:
    from alerters.hardware.native.match import CPU_RE, STORAGE_RE

    # A motherboard/CPU/RAM combo is still a collection of individual parts.
    # An explicit whole-PC name always wins over this exception.
    component_bundle = (re.search(r"\bmotherboard\b", title, re.I)
                        and re.search(r"\b(?:bundle|combo)\b", title, re.I))
    cpu = CPU_RE.search(title) or re.search(r"\b(?:Intel\s+)?Core\s+(?:i[3579]|Ultra\s+[579])\b|\b\d{4}X(?:3D)?\b", title, re.I)
    return bool(cpu and STORAGE_RE.search(title) and not component_bundle)


def allowed_title(title: str) -> bool:
    if not isinstance(title, str) or not title.strip():
        return False
    # Import lazily: facet extraction also uses the research title helpers.
    from .facets import product_type
    from alerters.hardware.native.catalog import Kind
    from alerters.hardware.native.match import find_all_parts, is_system_listing

    checked = subject_title(title)
    kind = product_type(checked)
    if kind not in KINDS or _computer_configuration(checked):
        return False
    # Dock/case/cover wording can name the computer it fits without selling it.
    # "Mac mini with a docking station" instead names the whole purchase.
    accessory_subject = (kind in {"Accessories", "Docks & hubs"}
                         and not re.search(r"\b(?:with|includes?|including)\b", checked, re.I))
    if COMPUTER.search(checked) and not accessory_subject:
        return False
    # Catch GPU-based machine identities that need more than generic facets.
    # A bare desktop card may describe its form factor using "desktop".
    checked = re.sub(r"\bdesktop\s+(?=(?:graphics|video)\s+card|gpu\b)", "", checked, flags=re.I)
    parts = find_all_parts(checked)
    if not accessory_subject and any(part.kind is Kind.UNIFIED or part.key in MACHINE_PRODUCT_KEYS for part in parts):
        return False
    return not any(part.kind not in (Kind.UNIFIED, Kind.PRODUCT) and is_system_listing(checked, part)
                   for part in parts)


def in_scope(row: dict) -> bool:
    title = row.get("title")
    if row.get("is_system") is True or not allowed_title(title):
        return False
    name = row.get("product_name")
    if not isinstance(name, str) or not name.strip():
        return True
    # An enriched short name can omit the product noun ("Samsung 990 Pro
    # 2TB"). Keep the titled product unless enrichment positively identifies
    # a computer, rather than requiring the incomplete name to classify alone.
    from .facets import product_type
    checked = subject_title(name)
    kind = product_type(checked)
    if kind == "Other tech":
        return not COMPUTER.search(checked) and not _computer_configuration(checked)
    return allowed_title(name)


def categories(title: str, is_system: bool = False) -> set[str]:
    if is_system or not allowed_title(title):
        return set()
    from .facets import product_type
    kind = product_type(title)
    if kind == "Monitors":
        return {"monitors"}
    if kind == "Memory":
        return {"parts", "memory"}
    return {"parts"} if kind in PART_KINDS else {"supplies"}
