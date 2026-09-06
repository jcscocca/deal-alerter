"""Delivery receipts, not attempted sends. File state is still the authority."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from .types import Assessment
from .verdict import Improvement


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class AlertRecord:
    price: float
    verdict: int
    alerted_at: datetime

    @classmethod
    def from_json(cls, raw: dict) -> AlertRecord:
        return cls(float(raw["price"]), int(raw["verdict"]), parse_time(raw["alerted_at"]))

    def to_json(self) -> dict:
        return {"price": round(self.price, 2), "verdict": self.verdict,
                "alerted_at": self.alerted_at.isoformat(timespec="seconds")}


class AlertState:
    def __init__(self, path: Path, normalise: Callable[[str], str]) -> None:
        self.path, self.normalise = path, normalise
        self.records: dict[str, dict[str, AlertRecord]] = {}
        if not path.exists():
            return
        # Corrupt state must not become an empty history and a notification storm.
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("version", 1) not in (1, 2):
            raise ValueError(f"Unsupported state version in {path}")
        for key, value in raw.get("alerts", {}).items():
            channels = value.get("deliveries")
            if channels is None:
                channels = {}
                # Import both legacy shapes. Old push state cannot identify the
                # transport, so carry its suppression forward to each push path.
                for field, names in (("alerted_at", ("email",)),
                                     ("digested_at", ("email",)),
                                     ("pushed_at", ("ntfy", "discord", "desktop"))):
                    if value.get(field):
                        for name in names:
                            channels[name] = {**value, "alerted_at": value[field]}
            bucket = self.records.setdefault(normalise(key), {})
            for channel, entry in channels.items():
                record = AlertRecord.from_json(entry)
                previous = bucket.get(channel)
                # A collision is two actual receipts, not permission to invent
                # a synthetic cheapest-price/highest-band combination.
                if previous is None or record.alerted_at > previous.alerted_at:
                    bucket[channel] = record

    def is_new(self, item: Assessment, channel: str, policy: Improvement,
               remind_after_days: int, now: datetime) -> bool:
        previous = self.records.get(self.normalise(item.key), {}).get(channel)
        return (previous is None
                or policy.better(item.price, int(item.verdict), previous.price, previous.verdict)
                or now - previous.alerted_at > timedelta(days=remind_after_days))

    def record(self, items: list[Assessment], channel: str, now: datetime) -> None:
        for item in items:
            self.records.setdefault(self.normalise(item.key), {})[channel] = AlertRecord(
                item.price, int(item.verdict), now)

    def forget_missing(self, live: set[str], complete_sources: set[str]) -> None:
        live = {self.normalise(key) for key in live}
        for key in list(self.records):
            if key.partition(":")[0] in complete_sources and key not in live:
                del self.records[key]

    def save(self, now: datetime) -> None:
        raw = {"version": 2, "updated_at": now.isoformat(timespec="seconds"),
               "alerts": {key: {"deliveries": {channel: record.to_json()
                            for channel, record in sorted(receipts.items())}}
                          for key, receipts in sorted(self.records.items())}}
        atomic_write(self.path, json.dumps(raw, indent=2) + "\n")
