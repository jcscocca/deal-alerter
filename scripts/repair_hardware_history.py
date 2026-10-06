"""Repair only the exact observations audited in PRs #22, #32 and #33.

Dry run by default. Applying requires the hardware writer lock and creates an
exclusive backup before atomically replacing prices.jsonl. Receipts are untouched.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dealcore.locking import WriterLock


# Exact source/id/part/title matches prevent rewriting an unrelated observation
# if a seller later repurposes a listing. All price variants of a match qualify.
AUDITED = {
    ("ebay", "v1|389929023162|0", "a100_40",
     "Gigabyte NVIDIA HPC/AI Server - G292-Z20 + 2x A100 40GB PCIE + 256gb RAM"): None,
    ("ebay", "v1|404932819870|0", "rtx_4090",
     "Ryzen 58003XD PC NVIDIA RTX 4090 - 64GB DDR4 RGB! 3600Mhz RAM+2TB SSD+WiFi 6"): None,
    ("ebay", "v1|820195368426|0", "rtx_4090",
     "Fractal Custom PC 3.0GHz 64GB RAM 2TB SSD Nvidia GeForce RTX 4090"): None,
    ("ebay", "v1|298728188892|0", "rtx_5090",
     "Intel Ultra 9 Assembled Computer 8GB RAM 240GB Gaming W11 Pro RTX5090 32GB PC"): None,
    ("slickdeals", "20088846", "rtx_5090",
     "ASUS GeForce RTX 5090 PCI Express 5 32GB GDDR7 Gaming Graphics Card, "
     "2437 MHz Core, 28000 MHz, Multicolored (TUF-RTX5090-32G-G) $4267.99"): "new",
    ("slickdeals", "19883949", "rtx_5090",
     "$4399.99 | MSI GeForce RTX 5090 32G SUPRIM LIQUID SOC (Factory Reconditioned) at Woot!"): "refurb",
}


@dataclass(frozen=True)
class Repair:
    text: str
    removed: tuple[dict, ...]
    moved: tuple[dict, ...]

    @property
    def changed(self) -> bool:
        return bool(self.removed or self.moved)


def plan(text: str) -> Repair:
    kept, removed, moved = [], [], []
    for line_number, line in enumerate(text.splitlines(keepends=True), 1):
        if not line.strip():
            kept.append(line)
            continue
        row = json.loads(line)  # A corrupt row must abort, never silently disappear.
        if not isinstance(row, dict):
            raise ValueError(f"Line {line_number} is not an observation object")
        key = tuple(row.get(field) for field in ("source", "listing_id", "part_key", "title"))
        if key not in AUDITED:
            kept.append(line)
            continue
        bucket = AUDITED[key]
        if bucket is None:
            removed.append(row)
        elif row.get("bucket") == "used":
            moved.append({**row, "new_bucket": bucket})
            row["bucket"] = bucket
            ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            kept.append(json.dumps(row, sort_keys=True) + ending)
        else:
            kept.append(line)  # Preserve already corrected or unexpected buckets.
    return Repair("".join(kept), tuple(removed), tuple(moved))


def repair(path: Path, *, backup: Path | None = None) -> Repair:
    path = path.resolve(strict=True)
    if backup is None:
        return plan(path.read_bytes().decode("utf-8"))
    if (path.name, path.parent.name, path.parent.parent.name) != ("prices.jsonl", "US", "hardware"):
        raise ValueError("Apply requires a hardware/US/prices.jsonl path")
    backup = backup.resolve()
    if backup == path:
        raise ValueError("Backup must be separate from prices.jsonl")
    with WriterLock(path.parent.parent / ".writer.lock"):
        original = path.read_bytes()
        result = plan(original.decode("utf-8"))
        if result.changed:
            with backup.open("xb") as stream:
                stream.write(original)
                stream.flush()
                os.fsync(stream.fileno())
            fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(result.text.encode("utf-8"))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="hardware/US/prices.jsonl to inspect")
    parser.add_argument("--apply", action="store_true", help="apply with the hardware writer stopped")
    parser.add_argument("--backup", type=Path, help="new backup file required with --apply")
    args = parser.parse_args(argv)
    if args.apply != (args.backup is not None):
        parser.error("--apply and --backup must be supplied together")
    try:
        result = repair(args.path, backup=args.backup)
    except (OSError, ValueError) as exc:
        print(f"Repair refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"applied": args.apply and result.changed,
                      "removed": result.removed, "moved": result.moved}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
