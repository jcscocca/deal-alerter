"""Conservative identity checks for standalone ThinkPad DDR5 memory watches."""
from __future__ import annotations

import re

# A layout is one purchase, including both modules when it is a kit. These
# limits are user-selected notification settings, not market-value estimates.
LAYOUTS = {
    "ddr5_sodimm_32": (1, 32, 200.0),
    "ddr5_sodimm_48": (1, 48, 300.0),
    "ddr5_sodimm_64_kit": (2, 32, 400.0),
    "ddr5_sodimm_96_kit": (2, 48, 600.0),
}
SKUS = {
    "ct32g56c46s5": (1, 32), "ct48g56c46s5": (1, 48),
    "ct2k32g56c46s5": (2, 32), "ct2k48g56c46s5": (2, 48),
    "kcp556sd8-32": (1, 32), "kcp556sd8-48": (1, 48),
    "kcp556sd8k2-64": (2, 32), "kcp556sd8k2-96": (2, 48),
}


def layout_label(title: str) -> str | None:
    if key := configuration(title):
        count, size, _ = LAYOUTS[key]
        return f"DDR5 SO-DIMM {count}x{size}GB"
    return None


def standalone_memory(title: str) -> bool:
    """Display classification only; matching below still verifies the layout."""
    primary = re.split(r"\b(?:compatible with|for (?:lenovo|thinkpad|laptops?|notebooks?))\b", title, maxsplit=1, flags=re.I)[0]
    if re.search(r"\b(?:SSD|RTX|GeForce|Ryzen|Intel Core|ThinkPad|MacBook|i[3579][- ]\d)\b", primary, re.I):
        return False
    without_memory_labels = re.sub(r"\b(?:laptop|notebook|desktop)\s+(?:RAM|memory)\b", "", primary, flags=re.I)
    if re.search(r"\b(?:laptop|notebook|desktop|computer|PC)\b", without_memory_labels, re.I):
        return False
    return bool(re.search(r"\bDDR[345]\b", title, re.I) and re.search(
        r"\bSO[- ]?DIMM\b|\b(?:laptop|notebook|desktop)\s+(?:RAM|memory)\b|\bmemory (?:kit|module)\b", title, re.I))


def configuration(title: str) -> str | None:
    """Return a single/kit key only with explicit, consistent module evidence."""
    text = title.lower().replace("×", "x")
    known = {layout for sku, layout in SKUS.items()
             if re.search(r"(?<![a-z0-9])" + re.escape(sku) + r"(?![a-z0-9])", text)}
    if len(known) > 1:
        return None
    if not known and not (standalone_memory(title) and re.search(r"\bso[- ]?dimm\b", text) and re.search(r"\bddr5\b", text)):
        return None
    # A known module number in a computer or adapter title is not the module.
    primary = re.split(r"\b(?:compatible with|for (?:lenovo|thinkpad|laptops?|notebooks?))\b", text, maxsplit=1)[0]
    if re.search(r"\b(?:SSD|RTX|GeForce|Ryzen|Intel Core|ThinkPad|MacBook|i[3579][- ]\d|adapter|converter|heatsink|heatspreader|dummy|packaging|box only)\b", primary, re.I):
        return None
    without_memory_labels = re.sub(r"\b(?:laptop|notebook|desktop)\s+(?:RAM|memory)\b", "", primary, flags=re.I)
    if re.search(r"\b(?:laptop|notebook|desktop|computer|PC)\b", without_memory_labels, re.I):
        return None
    ecc_text = re.sub(r"\b(?:non[- ]?ecc|on[- ]die[- ]ecc)\b", "", text)
    if re.search(r"\b(?:DDR[34]|UDIMM|RDIMM|LRDIMM|CAMM2?|ECC|registered|buffered|288[- ]?pin)\b", ecc_text, re.I):
        return None
    if re.search(r"\b(?:choose|select|options|up to|starting)\b|\bfrom\s*\$|\d\s*GB\s*(?:[/\-]|or)\s*\d", text, re.I):
        return None
    if re.search(r"\b\d+\s*(?:/|or)\s*\d+\s*gb\b", text):
        return None
    layouts = {(int(n), int(gb)) for n, gb in re.findall(r"\b(\d+)\s*x\s*(\d+)\s*gb\b", text)}
    layouts |= {(int(n), int(gb)) for gb, n in re.findall(r"\b(\d+)\s*gb\s*x\s*(\d+)\b", text)}
    sizes = {int(gb) for gb in re.findall(r"\b(\d+)\s*gb\b", text)}
    if layouts:
        if len(layouts) != 1:
            return None
        count, size = next(iter(layouts))
        if known and known not in ({(count, size)}, {(1, size)}):
            return None
    elif known:
        count, size = next(iter(known))
    elif len(sizes) == 1 and next(iter(sizes)) in (32, 48):
        count, size = 1, next(iter(sizes))
    else:
        return None
    rest = re.sub(r"\b\d+\s*x\s*\d+\s*gb\b|\b\d+\s*gb\s*x\s*\d+\b", "", text)
    if re.search(r"\b\d+\s*x\b|\bx\s*\d+\b|\b\d+\s*(?:pack|pcs|pieces|modules|sticks)\b", rest):
        return None
    # A bare kit/pair or a lot without its module count cannot become one stick.
    if count == 1 and re.search(r"\b(?:kit|pair|lot|pack|modules|sticks)\b", text):
        return None
    declared = {int(n) for n in re.findall(r"\b(?:kit of|pack of|lot of|quantity\s*[:=]?)\s*(\d+)\b", text)}
    if declared and declared != {count}:
        return None
    if sizes - {size, count * size}:
        return None
    return next((key for key, (n, gb, _) in LAYOUTS.items() if (n, gb) == (count, size)), None)
