"""Personal desktop requirements; hardware layout evidence is not kit validation."""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .prebuilt import Offer, gpu_key


@dataclass(frozen=True)
class MemoryFit:
    status: str
    summary: str
    eligible: bool = True
    potential_gb: int | None = None
    evidence: tuple[str, ...] = ()
    installed_gb: int | None = None


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _one(values):
    values = set(values)
    return next(iter(values)) if len(values) == 1 else None


class DesktopProfile:
    def __init__(self, path: Path):
        self.data = tomllib.loads(path.read_text(encoding="utf-8"))
        self.memory = self.data["memory"]
        self.prices = self.data["price"]
        self.reviewed = self.data.get("reviewed_configuration", [])
        if not (0 < self.memory["minimum_gb"] <= self.memory["preferred_gb"]):
            raise ValueError("Invalid desktop memory targets")
        if self.memory["required_slots"] != 4 or self.memory["owned_modules"] != 2:
            raise ValueError("Desktop reuse profile requires four slots and an owned pair")
        for band in self.prices.values():
            if not (0 < band["urgent"] <= band["target"] <= band["ceiling"]):
                raise ValueError("Invalid desktop price thresholds")

    def price_band(self, fit: MemoryFit, gpu: str = "5080") -> dict:
        # Unknown capacity stays discoverable at the wider limit, but cannot
        # earn elevated urgency until the installed RAM is established.
        return self.prices[f"{gpu_key(gpu)}_{fit.installed_gb or 64}"]

    def ceiling(self, gpu: str, legacy_target: float | None, fit: MemoryFit) -> float | None:
        return self.price_band(fit, gpu)["ceiling"] if gpu in ("5070 Ti", "5080") else legacy_target

    def priority(self, gpu: str, total: float | None, fit: MemoryFit) -> int:
        if total is None:
            return 3
        if gpu in ("5070 Ti", "5080"):
            if fit.installed_gb is None:
                return 3
            band = self.price_band(fit, gpu)
            return 5 if total <= band["urgent"] else 4 if total <= band["target"] else 3
        return 3 if total >= 4500 else 4 if total >= 4000 else 5

    def assess_memory(self, offer: Offer) -> MemoryFit:
        specs = {_key(k): str(v) for k, v in offer.specs.items()}
        evidence = []
        # Exact SKU reviews can fill missing specifications, never silently
        # override the live selected configuration. Conflicts require review.
        reviewed_specs = {}
        for row in self.reviewed:
            if row["retailer"] == offer.retailer and row["sku"] == offer.sku and not offer.announcement:
                reviewed_specs = {_key(k): str(v) for k, v in row["specs"].items()}
                evidence.append(f"Layout source ({row['checked_on']}): {row['source']}")

        def values(keys):
            return [source[key] for source in (specs, reviewed_specs) for key in keys if key in source]

        ram_values = values(("ram", "memory", "memoryram", "memorysize", "totalmemory", "memorycapacity",
                             "systemmemory", "systemmemoryram", "selectedram", "selectedmemory", "memoryconfiguration"))
        capacities = []
        modules = []
        for value in ram_values:
            if re.search(r"\b(?:up to|max(?:imum)?|supports?)\b", value, re.I):
                continue
            pair = re.search(r"\b(\d+)\s*[x×*]\s*(\d+)\s*GB\b", value, re.I)
            if pair:
                modules.append(int(pair[1]))
                capacities.append(int(pair[1]) * int(pair[2]))
            else:
                match = re.search(r"\b(\d+)\s*GB\b", value, re.I)
                if match:
                    capacities.append(int(match[1]))
        # A GPU's "32GB GDDR7" and "supports 128GB" are not installed RAM.
        capacities += [int(m[1]) for m in re.finditer(
            r"\b(\d+)\s*GB\s*(?:DDR[45]\b|RAM\b|(?:system\s+)?memory\b)", offer.title, re.I)
            if not re.search(r"(?:up to|max(?:imum)?|supports?)\s*$", offer.title[max(0, m.start()-20):m.start()], re.I)]
        installed = _one(capacities)
        count = _one(modules)

        def numbers(keys):
            return [int(m[0]) for value in values(keys) if (m := re.search(r"\d+", value))]

        slot_values = numbers(("memoryslots", "memoryslotstotal", "totalmemoryslots", "dimmslots"))
        max_values = numbers(("maximummemory", "maximummemorysupported", "maxmemory", "maxmemorysupported"))
        slots, maximum = _one(slot_values), _one(max_values)
        free_values = numbers(("memoryslotsavailable", "availablememoryslots", "freedimmslots"))
        available = _one(free_values)
        types = set(re.findall(r"\bDDR[45]\b", " ".join(ram_values + values(("memorytype", "memoryspeed")) + [offer.title]), re.I))
        types = {value.upper() for value in types}
        if any(capacity not in (32, 64) for capacity in capacities):
            return MemoryFit("OUTSIDE REUSE WATCH", "This watch only considers factory 32GB or 64GB systems to combine with your existing 64GB.", False)
        if any(number != 2 for number in modules) or any(number != 2 for number in free_values):
            return MemoryFit("NO REUSE PATH", "The requested layout needs two factory modules and two free slots; this configuration does not match.", False)
        conflict = any(len(set(items)) > 1 for items in (capacities, modules, slot_values, max_values, free_values)) or len(types) > 1
        if conflict:
            return MemoryFit("NEEDS SPECS", "Conflicting RAM specifications; verify the exact configuration.", evidence=tuple(evidence))
        if types == {"DDR4"}:
            return MemoryFit("NO REUSE PATH", "DDR4 board cannot accept your DDR5 kit.", False)
        if slots is not None and slots != self.memory["required_slots"]:
            return MemoryFit("NO REUSE PATH", f"{slots} RAM slots; the requested four-slot layout is absent.", False)
        if maximum is not None and maximum < self.memory["minimum_gb"]:
            return MemoryFit("NO REUSE PATH", f"Published maximum is only {maximum}GB.", False)
        if slots == 4 and available == 2:
            count = 2
        potential = installed + self.memory["owned_gb"] if installed is not None else None
        if potential is not None and (potential < self.memory["minimum_gb"] or maximum is not None and potential > maximum):
            return MemoryFit("NO REUSE PATH", "Adding your pair does not reach a supported target capacity.", False)
        if potential is not None and slots == 4 and count == 2 and maximum is not None and types == {"DDR5"}:
            return MemoryFit("POSSIBLE REUSE", f"{installed}GB installed + your {self.memory['owned_gb']}GB = {potential}GB potential; mixed-kit stability unverified.",
                             potential_gb=potential, evidence=tuple(evidence), installed_gb=installed)
        return MemoryFit("NEEDS SPECS", "Verify DDR5, installed stick count, four slots and supported capacity before planning RAM reuse."
                         + (f" Potential total if compatible: {potential}GB." if potential is not None else " Installed RAM capacity unknown."),
                         potential_gb=potential, evidence=tuple(evidence), installed_gb=installed)


DEFAULT_PROFILE = Path(__file__).resolve().parents[2] / "config/desktop-profile.toml"
