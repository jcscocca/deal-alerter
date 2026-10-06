"""Repair exact audited observations and the older title-verified backlog.

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

# Older parser fixes were merged without migrating these exact historical rows.
# A new part key preserves every observed price, timestamp and condition; None
# removes complete machines/mobile hardware from desktop GPU price comparisons.
LEGACY = {
    ("ebay", "v1|147512947333|0", "dgx_spark",
     "ASUS Ascent GX10 Compact Desktop AI Supercomputer 1TB 128 GB NVIDIA DGX  Spark"): "asus_ascent_gx10",
    ("ebay", "v1|198028854618|0", "dgx_spark",
     "ASUS Ascent GX10 Compact Desktop AI Supercomputer 1TB 128 GB NVIDIA DGX  Spark"): "asus_ascent_gx10",
    ("ebay", "v1|188788253355|0", "rtx_3090",
     "MSI Gaming Suprim X GeForce RTX 3090ti 24GB GDRR6X PCIe 4.0 *Mint Condition*"): "rtx_3090_ti",
    ("ebay", "v1|117361479588|0", "rtx_4090",
     "Asus ROG Zephyrus Duo 16 RTX 4090"): None,
    ("ebay", "v1|127929388460|0", "rtx_5090",
     "ROG Strix SCAR 18 (2024) G635 Ultra 9 Processor 275HX 32GB RAM +1TB SSD+RTX 5090"): None,
    ("ebay", "v1|227469245646|0", "rtx_pro_5000_blackwell",
     "nvidia rtx pro 5000 blackwell for dell pro max 18 plus"): None,
    ("ebay", "v1|236742551157|0", "rtx_pro_6000_blackwell",
     "Intel Xeon w7-3565X 2x RTX PRO 6000 Blackwell AI/Machine Learning Workstation"): None,
    ("ebay", "v1|127612384846|0", "rtx_pro_6000_blackwell",
     "NVIDIA RTX PRO 6000 Blackwell 96GB GDDR7 Max-Q Edition New Bulk Packaging"): "rtx_pro_6000_blackwell_maxq",
    ("ebay", "v1|227410975366|0", "rtx_pro_6000_blackwell",
     "NVIDIA RTX PRO 6000 96GB Blackwell Max-Q Workstation Edition"): "rtx_pro_6000_blackwell_maxq",
    ("ebay", "v1|227433753697|0", "rtx_pro_6000_blackwell",
     "NVIDIA RTX PRO 6000 96GB Blackwell Max-Q Workstation Edition"): "rtx_pro_6000_blackwell_maxq",
    ("ebay", "v1|336742858136|0", "rtx_pro_6000_blackwell",
     "NVIDIA RTX PRO 6000 Blackwell 96GB GDDR7 MaxQ Workstation Edition"): "rtx_pro_6000_blackwell_maxq",
    ("ebay", "v1|389764313744|0", "rtx_pro_6000_blackwell",
     "NVIDIA RTX PRO 6000 96GB Blackwell Max-Q Workstation Edition"): "rtx_pro_6000_blackwell_maxq",
    ("ebay", "v1|800270279893|0", "rtx_pro_6000_blackwell",
     "NVIDIA RTX PRO 6000 96GB Blackwell Max-Q Workstation Edition"): "rtx_pro_6000_blackwell_maxq",
    ("ebay", "v1|128022061160|0", "rtx_pro_6000_blackwell",
     "NVIDIA RTX PRO 6000 96GB Blackwell Max-Q Workstation Edition HP PN P20286-002"): "rtx_pro_6000_blackwell_maxq",
}


@dataclass(frozen=True)
class Repair:
    text: str
    removed: tuple[dict, ...]
    moved: tuple[dict, ...]
    quarantined: tuple[dict, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.removed or self.moved or self.quarantined)


def plan(text: str, *, quarantine_unlabelled: bool = False) -> Repair:
    kept, removed, moved, quarantined = [], [], [], []
    for line_number, line in enumerate(text.splitlines(keepends=True), 1):
        if not line.strip():
            kept.append(line)
            continue
        row = json.loads(line)  # A corrupt row must abort, never silently disappear.
        if not isinstance(row, dict):
            raise ValueError(f"Line {line_number} is not an observation object")
        title = row.get("title")
        if quarantine_unlabelled and (title is None or isinstance(title, str) and not title.strip()):
            quarantined.append(row)
            continue
        key = tuple(row.get(field) for field in ("source", "listing_id", "part_key", "title"))
        if not all(isinstance(value, str) for value in key) or key not in AUDITED and key not in LEGACY:
            kept.append(line)
            continue
        bucket = AUDITED.get(key)
        part = LEGACY.get(key)
        if bucket is None and part is None:
            removed.append(row)
        elif part is not None or row.get("bucket") == "used":
            if part is not None:
                moved.append({**row, "new_part_key": part})
                row["part_key"] = part
            else:
                moved.append({**row, "new_bucket": bucket})
                row["bucket"] = bucket
            ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            kept.append(json.dumps(row, sort_keys=True) + ending)
        else:
            kept.append(line)  # Preserve already corrected or unexpected buckets.
    return Repair("".join(kept), tuple(removed), tuple(moved), tuple(quarantined))


def atomic_bytes(path: Path, data: bytes) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def archive_rows(path: Path, rows: tuple[dict, ...]) -> bytes:
    original = path.read_bytes() if path.exists() else b""
    known = set()
    for line in original.decode("utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("Archive contains a non-observation object")
        known.add(json.dumps(row, sort_keys=True))
    extra = []
    for row in rows:
        encoded = json.dumps(row, sort_keys=True)
        if encoded not in known:
            known.add(encoded)
            extra.append(encoded)
    if not extra:
        return original
    separator = b"\n" if original and not original.endswith(b"\n") else b""
    return original + separator + ("\n".join(extra) + "\n").encode("utf-8")


def repair(path: Path, *, backup: Path | None = None, quarantine_unlabelled: bool = False) -> Repair:
    path = path.resolve(strict=True)
    if backup is None:
        return plan(path.read_bytes().decode("utf-8"), quarantine_unlabelled=quarantine_unlabelled)
    if (path.name, path.parent.name, path.parent.parent.name) != ("prices.jsonl", "US", "hardware"):
        raise ValueError("Apply requires a hardware/US/prices.jsonl path")
    backup = backup.resolve()
    if backup == path:
        raise ValueError("Backup must be separate from prices.jsonl")
    with WriterLock(path.parent.parent / ".writer.lock"):
        original = path.read_bytes()
        result = plan(original.decode("utf-8"), quarantine_unlabelled=quarantine_unlabelled)
        if result.changed:
            archive = path.with_name("prices-unaudited.jsonl")
            if archive.resolve().parent != path.parent or archive.is_symlink():
                raise ValueError("Archive must stay beside prices.jsonl")
            archived = archive_rows(archive, result.quarantined) if result.quarantined else None
            with backup.open("xb") as stream:
                stream.write(original)
                stream.flush()
                os.fsync(stream.fileno())
            # Preserve evidence first. A crash between writes can duplicate rows,
            # but cannot lose them; an exact-row dedup makes retry safe.
            if archived is not None:
                atomic_bytes(archive, archived)
            atomic_bytes(path, result.text.encode("utf-8"))
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="hardware/US/prices.jsonl to inspect")
    parser.add_argument("--apply", action="store_true", help="apply with the hardware writer stopped")
    parser.add_argument("--backup", type=Path, help="new backup file required with --apply")
    parser.add_argument("--quarantine-unlabelled", action="store_true",
                        help="archive rows without titles outside active price baselines")
    args = parser.parse_args(argv)
    if args.apply != (args.backup is not None):
        parser.error("--apply and --backup must be supplied together")
    try:
        result = repair(args.path, backup=args.backup, quarantine_unlabelled=args.quarantine_unlabelled)
    except (OSError, ValueError) as exc:
        print(f"Repair refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"applied": args.apply and result.changed,
                      "removed": result.removed, "moved": result.moved,
                      "quarantined": result.quarantined}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
