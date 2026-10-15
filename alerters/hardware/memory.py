"""Standalone DDR5 price-watch identities for laptop and desktop modules."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

from . import sodimm

DESKTOP_MARKET = tomllib.loads(
    (Path(__file__).resolve().parents[2] / "config/desktop-memory-market.toml").read_text(encoding="utf-8")
)
# The third value is a documented retail ask, not an alert threshold or sold value.
DESKTOP_LAYOUTS = {key: (row["modules"], row["module_gb"], row["reference_item_price"])
                   for key, row in DESKTOP_MARKET["reference"].items()}
LAYOUTS = {**sodimm.LAYOUTS, **DESKTOP_LAYOUTS}
SKUS = sodimm.SKUS


def desktop_configuration(title: str) -> str | None:
    text = title.lower().replace("×", "x")
    if not re.search(r"\bddr5\b", text):
        return None
    # Desktop wording alone does not distinguish a memory module from a PC.
    if not re.search(r"\budimm\b|\b288[- ]?pin\b|\bdesktop\s+(?:ram|memory)\b", text):
        return None
    checked = re.sub(r"\b(?:non[- ]?ecc|on[- ]die[- ]ecc)\b", "", text)
    # Retail memory titles say "288-Pin PC RAM"; that phrase is not a whole PC.
    checked = re.sub(r"\b(?:desktop|pc|computer)\s+(?:ram|memory)\b", "memory", checked)
    if re.search(r"\b(?:so[- ]?dimm|rdimm|lrdimm|camm2?|ecc|registered|buffered|ddr[34]|"
                 r"rtx|geforce|ryzen|intel core|intel xeon|ssd|pc|computer|adapter|dummy|heatsink|packaging)\b", checked):
        return None
    if re.search(r"\b(?:choose|select|options|up to|starting|each)\b|\bper\s+(?:stick|module|unit)\b|"
                 r"\d\s*(?:gb)?\s*(?:/|or|-)\s*\d+\s*gb", text):
        return None
    layouts = {(int(n), int(gb)) for n, gb in re.findall(r"\b(\d+)\s*x\s*(\d+)\s*gb\b", text)}
    layouts |= {(int(n), int(gb)) for gb, n in re.findall(r"\b(\d+)\s*gb\s*x\s*(\d+)\b", text)}
    sizes = {int(gb) for gb in re.findall(r"\b(\d+)\s*gb\b", text)}
    if layouts == {(2, 48)}:
        count, size = 2, 48
    elif (not layouts or layouts == {(1, 64)}) and sizes == {64}:
        count, size = 1, 64
    else:
        return None
    if sizes - {size, count * size}:
        return None
    rest = re.sub(r"\b\d+\s*x\s*\d+\s*gb\b|\b\d+\s*gb\s*x\s*\d+\b", "", text)
    if re.search(r"\b\d+\s*x\b|\bx\s*\d+\b|\b\d+\s*(?:pack|pcs|pieces|modules|sticks)\b", rest):
        return None
    if count == 1 and re.search(r"\b(?:kit|pair|lot|pack|modules|sticks)\b", rest):
        return None
    declared = {int(n) for n in re.findall(r"\b(?:kit of|pack of|lot of|quantity\s*[:=]?)\s*(\d+)\b", rest)}
    if declared and declared != {count}:
        return None
    return next(key for key, (n, gb, _) in DESKTOP_LAYOUTS.items() if (n, gb) == (count, size))


def configuration(title: str) -> str | None:
    return desktop_configuration(title) or sodimm.configuration(title)


def standalone_memory(title: str) -> bool:
    return bool(desktop_configuration(title)) or sodimm.standalone_memory(title)


def layout_label(title: str) -> str | None:
    if key := configuration(title):
        count, size, _ = LAYOUTS[key]
        return f"DDR5 {'UDIMM' if key in DESKTOP_LAYOUTS else 'SO-DIMM'} {count}x{size}GB"
    return None
